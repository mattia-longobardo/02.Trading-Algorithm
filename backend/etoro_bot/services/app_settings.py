"""Impostazioni runtime (§10): precedenza app_settings DB > settings.yaml > default.

I guardrail sul passaggio verso l'ambiente real sono enforced QUI, lato
backend: la UI non è mai l'unica difesa. Il passaggio verso demo è sempre
permesso, senza conferme. Non esiste più una modalità dry-run/live: gli
ordini approvati dal risk gate vengono sempre eseguiti per davvero
nell'ambiente scelto; kill switch e circuit breaker restano gli unici freni.

Due impostazioni sono di sola presentazione e non toccano l'esecuzione:
`timezone` (lo scheduling è sempre in UTC — vedi services/scheduler.py) e
`currency` (il journal resta in USD — vedi services/fx.py).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from etoro_bot.config import RiskRules, load_risk_rules, load_settings
from etoro_bot.db.repo import Repository
from etoro_bot.safety import CircuitBreaker, kill_switch_active
from etoro_bot.services.fx import SUPPORTED_CURRENCIES

LIVE_CONFIRMATION = True

_SCHEDULE_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# Default hardcoded: ultimo fallback se anche settings.yaml manca.
_DEFAULTS: dict[str, Any] = {
    "environment": "demo",
    "schedule_utc": "08:30",
    "timezone": "Europe/Rome",
    "currency": "USD",
    "weekdays_only": True,
    "live_ack": None,
    "risk_limits": None,
}

# Chiavi modificabili via update(); live_ack è gestita internamente.
_MUTABLE_KEYS = (
    "environment",
    "schedule_utc",
    "timezone",
    "currency",
    "weekdays_only",
    "risk_limits",
)
_RISK_FIELDS = (
    "max_position_pct_equity",
    "max_total_exposure_pct",
    "max_sector_exposure_pct",
    "max_open_positions",
    "max_orders_per_run",
    "max_orders_per_day",
    "min_cash_buffer_pct",
)


def risk_limits_dict(rules: RiskRules) -> dict[str, Any]:
    return {key: getattr(rules, key) for key in _RISK_FIELDS}


def effective_risk_rules(repo: Repository) -> RiskRules:
    base = load_risk_rules()
    stored = repo.get_setting("risk_limits")
    if not isinstance(stored, dict):
        return base
    values = {**base.__dict__, **{key: stored[key] for key in _RISK_FIELDS if key in stored}}
    return RiskRules(**values)


class SettingsValidationError(Exception):
    """Cambio impostazioni respinto dai guardrail: l'API risponde 422."""

    status_code = 422

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AppSettingsService:
    def __init__(self, repo: Repository):
        self._repo = repo

    # --- lettura ------------------------------------------------------------
    def get_effective(self) -> dict[str, Any]:
        """Impostazioni effettive: app_settings (DB) > settings.yaml > default."""
        yaml_cfg = load_settings()
        effective: dict[str, Any] = {}
        for key, default in _DEFAULTS.items():
            if key == "risk_limits":
                effective[key] = risk_limits_dict(effective_risk_rules(self._repo))
                continue
            db_value = self._repo.get_setting(key)
            if db_value is not None:
                effective[key] = db_value
            else:
                effective[key] = yaml_cfg.get(key, default)
        return effective

    # --- scrittura con guardrail (§10) --------------------------------------
    def update(
        self,
        changes: dict[str, Any],
        source: str = "api",
        *,
        etoro_configured: bool | None = None,
    ) -> dict[str, Any]:
        changes = dict(changes)
        confirmation = changes.pop("confirmation", None)

        unknown = set(changes) - set(_MUTABLE_KEYS)
        if unknown:
            raise SettingsValidationError(
                f"chiavi non modificabili o sconosciute: {', '.join(sorted(unknown))}"
            )

        current = self.get_effective()
        target = {**current, **changes}
        self._validate_values(target)

        # Pericoloso: si va verso l'ambiente real (muove denaro vero).
        dangerous = target["environment"] == "real" and current["environment"] != "real"

        if dangerous:
            if confirmation is not LIVE_CONFIRMATION:
                raise SettingsValidationError(
                    "il passaggio verso l'ambiente real richiede confirmation: true"
                )
            self._check_safety_for_real(etoro_configured)

        for key, value in changes.items():
            if value != current[key]:
                self._repo.set_setting(key, value, source=source)
        if dangerous:
            self._repo.set_setting(
                "live_ack", datetime.now(timezone.utc).isoformat(), source=source
            )

        return self.get_effective()

    # --- helper -------------------------------------------------------------
    def _check_safety_for_real(self, etoro_configured: bool | None) -> None:
        if not etoro_configured:
            raise SettingsValidationError(
                "chiavi eToro mancanti: configurale in Impostazioni → Chiavi API "
                "personali prima di passare a real"
            )
        if kill_switch_active():
            raise SettingsValidationError("kill switch attivo: impossibile passare a real")
        breaker = CircuitBreaker(effective_risk_rules(self._repo).circuit_breaker)
        if breaker.blocks_openings():
            raise SettingsValidationError(
                "circuit breaker scattato: impossibile passare a real"
            )

    @staticmethod
    def _validate_values(target: dict[str, Any]) -> None:
        if target["environment"] not in ("demo", "real"):
            raise SettingsValidationError("environment deve essere 'demo' o 'real'")
        if not isinstance(target["schedule_utc"], str) or not _SCHEDULE_RE.match(
            target["schedule_utc"]
        ):
            raise SettingsValidationError("schedule_utc deve avere formato HH:MM")
        try:
            ZoneInfo(str(target["timezone"]))
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise SettingsValidationError("timezone IANA non valida") from exc
        if target["currency"] not in SUPPORTED_CURRENCIES:
            raise SettingsValidationError(
                f"valuta non supportata: scegli fra {', '.join(SUPPORTED_CURRENCIES)}"
            )
        if not isinstance(target["weekdays_only"], bool):
            raise SettingsValidationError("weekdays_only deve essere booleano")
        limits = target["risk_limits"]
        if not isinstance(limits, dict) or set(limits) != set(_RISK_FIELDS):
            raise SettingsValidationError("risk_limits deve contenere tutti i limiti modificabili")
        for key in _RISK_FIELDS:
            value = limits[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise SettingsValidationError(f"{key} deve essere un numero")
            if value < 0 or (key != "min_cash_buffer_pct" and value == 0):
                raise SettingsValidationError(f"{key} deve essere maggiore di zero")
        for key in ("max_position_pct_equity", "max_total_exposure_pct",
                    "max_sector_exposure_pct", "min_cash_buffer_pct"):
            if float(limits[key]) > 100:
                raise SettingsValidationError(f"{key} non può superare 100")
        for key in ("max_open_positions", "max_orders_per_run", "max_orders_per_day"):
            if int(limits[key]) != limits[key]:
                raise SettingsValidationError(f"{key} deve essere un intero")
