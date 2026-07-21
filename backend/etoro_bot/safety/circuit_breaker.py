"""Circuit breaker persistente su file JSON (volume ./state).

Scatta per perdita giornaliera oltre soglia o N perdite consecutive; blocca le
APERTURE (mai le chiusure) per cooloff_hours; sopravvive al riavvio. Come il
kill switch, non dipende da Postgres: il percorso di sicurezza resta vivo
anche con il database giù.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from etoro_bot.config import CircuitBreakerRules

STATE_FILENAME = "circuit_breaker.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class BreakerState:
    tripped: bool = False
    reason: str | None = None
    tripped_at: str | None = None       # ISO 8601 UTC
    cooloff_until: str | None = None    # ISO 8601 UTC
    consecutive_losses: int = 0
    day: str | None = None              # giorno UTC del conteggio perdita giornaliera
    daily_pnl_usd: float = 0.0


class CircuitBreaker:
    def __init__(self, rules: CircuitBreakerRules, state_dir: str | Path | None = None):
        self.rules = rules
        base = Path(state_dir or os.environ.get("KILL_SWITCH_DIR", "."))
        self.path = base / STATE_FILENAME
        self.state = self._load()

    def _load(self) -> BreakerState:
        if self.path.exists():
            try:
                return BreakerState(**json.loads(self.path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError):
                # File corrotto: fail-safe, breaker scattato finché non si interviene
                return BreakerState(
                    tripped=True,
                    reason="stato breaker illeggibile: intervento manuale richiesto",
                    tripped_at=_now().isoformat(),
                    cooloff_until=None,
                )
        return BreakerState()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self.state), indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def blocks_openings(self) -> bool:
        """True se le aperture sono bloccate. Le chiusure passano SEMPRE."""
        if not self.state.tripped:
            return False
        if self.state.cooloff_until is None:
            return True  # trip permanente (es. stato corrotto) finché non resettato
        if _now() >= datetime.fromisoformat(self.state.cooloff_until):
            self.reset()
            return False
        return True

    def record_closed_trade(self, realized_pnl_usd: float, equity_usd: float) -> None:
        """Aggiorna i contatori a ogni trade chiuso e fa scattare il breaker se serve."""
        today = _now().date().isoformat()
        if self.state.day != today:
            self.state.day = today
            self.state.daily_pnl_usd = 0.0
        self.state.daily_pnl_usd += realized_pnl_usd

        if realized_pnl_usd < 0:
            self.state.consecutive_losses += 1
        elif realized_pnl_usd > 0:
            self.state.consecutive_losses = 0

        if self.state.consecutive_losses >= self.rules.max_consecutive_losses:
            self._trip(f"{self.state.consecutive_losses} perdite consecutive")
        elif (
            equity_usd > 0
            and -self.state.daily_pnl_usd / equity_usd * 100 >= self.rules.max_daily_loss_pct
        ):
            self._trip(
                f"perdita giornaliera {self.state.daily_pnl_usd:.2f} USD oltre "
                f"{self.rules.max_daily_loss_pct}% dell'equity"
            )
        else:
            self._save()

    def _trip(self, reason: str) -> None:
        self.state.tripped = True
        self.state.reason = reason
        self.state.tripped_at = _now().isoformat()
        self.state.cooloff_until = (
            _now() + timedelta(hours=self.rules.cooloff_hours)
        ).isoformat()
        self._save()

    def reset(self) -> None:
        self.state = BreakerState(day=self.state.day, daily_pnl_usd=self.state.daily_pnl_usd)
        self._save()
