"""Risk score composito 1-10 del portafoglio bot (§11.4).

NIENTE LLM: solo funzioni deterministiche e riproducibili, calcolate SOLO
sulle posizioni bot (§7). Pesi e soglie vivono in config/risk_score.yaml;
ogni componente è normalizzata 0-10 con interpolazione lineare tra low e high.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from etoro_bot.config import RiskRules, load_risk_rules, load_risk_score_config, load_settings
from etoro_bot.db.repo import Repository
from etoro_bot.domain import Position
from etoro_bot.safety import CircuitBreaker
from etoro_bot.services.backtest import daily_returns

VOLATILITY_WINDOW_DAYS = 90
SUGGESTION_THRESHOLD = 7.0

_LABELS = {
    "position_concentration": "Concentrazione per posizione",
    "sector_concentration": "Concentrazione settoriale",
    "exposure": "Esposizione",
    "cash_buffer": "Cash buffer",
    "realized_volatility_90d": "Volatilità realizzata 90g",
    "current_drawdown": "Drawdown corrente",
    "beta_vs_spy": "Beta vs SPY",
    "safety_state": "Stato safety",
}

_SUGGESTIONS = {
    "position_concentration": "riduci le posizioni più pesanti per distribuire il rischio",
    "sector_concentration": "diversifica su più settori prima di nuove aperture",
    "exposure": "l'esposizione è vicina al limite: evita nuove aperture",
    "cash_buffer": "ricostituisci la liquidità sopra il buffer minimo",
    "realized_volatility_90d": "la volatilità è elevata: riduci la dimensione degli ordini",
    "current_drawdown": "drawdown marcato: valuta di ridurre l'esposizione",
    "beta_vs_spy": "il portafoglio amplifica il mercato: privilegia titoli difensivi",
    "safety_state": "safety layer sotto stress: attendi il cooloff prima di riaprire",
}


# --- funzioni pure ----------------------------------------------------------


def hhi(weights: list[float]) -> float:
    """Indice Herfindahl-Hirschman sui pesi (normalizzati alla loro somma)."""
    total = sum(weights)
    if total <= 0:
        return 0.0
    return float(sum((w / total) ** 2 for w in weights))


def normalize(value: float, low: float, high: float) -> float:
    """Mappa lineare di value su [0, 10] tra low (→0) e high (→10), con clamp."""
    if high <= low:
        return 10.0 if value >= high else 0.0
    return float(min(10.0, max(0.0, (value - low) / (high - low) * 10.0)))


@dataclass
class RiskScoreResult:
    score: float
    band: str
    breakdown: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _band_for(score: float, bands: dict[str, Any]) -> str:
    for name in ("low", "medium", "high", "extreme"):
        bounds = bands.get(name)
        if bounds and score <= float(bounds[1]):
            return name
    return "extreme"


def _annualized_volatility(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    return float(np.std(returns, ddof=1) * np.sqrt(252))


def _current_drawdown(returns: list[float]) -> float | None:
    if not returns:
        return None
    curve = np.cumprod(np.asarray(returns) + 1.0)
    peak = float(np.max(curve))
    if peak <= 0:
        return None
    return float(1.0 - curve[-1] / peak)


def _beta(returns: list[float], benchmark_returns: list[float] | None) -> float | None:
    if benchmark_returns is None or len(returns) != len(benchmark_returns) or len(returns) < 2:
        return None
    x = np.asarray(benchmark_returns)
    var_x = float(np.var(x))
    if var_x == 0:
        return None
    return float(np.cov(x, np.asarray(returns), ddof=0)[0, 1] / var_x)


def compute_risk_score(
    positions: list[Position],
    cash_usd: float,
    equity_returns: list[float],
    spy_returns: list[float] | None,
    breaker_state: dict[str, Any],
    risk_rules: RiskRules,
    cfg: dict[str, Any],
) -> RiskScoreResult:
    """Score composito deterministico: media pesata delle componenti 0-10."""
    weights: dict[str, float] = cfg.get("weights", {})
    thresholds: dict[str, Any] = cfg.get("thresholds", {})
    bands: dict[str, Any] = cfg.get("bands", {"low": [1, 3], "medium": [4, 6],
                                              "high": [7, 8], "extreme": [9, 10]})

    exposure_usd = sum(p.amount_usd for p in positions)
    equity_usd = cash_usd + exposure_usd
    amounts = [p.amount_usd for p in positions]
    sector_totals: dict[str, float] = {}
    for p in positions:
        sector_totals[p.sector] = sector_totals.get(p.sector, 0.0) + p.amount_usd

    # --- valori grezzi per componente (None = dati insufficienti → 0) --------
    raw: dict[str, float | None] = {}
    explanations: dict[str, str] = {}

    raw["position_concentration"] = hhi(amounts) if amounts else 0.0
    explanations["position_concentration"] = (
        f"HHI dei pesi su {len(positions)} posizioni: {raw['position_concentration']:.2f} "
        "(0.10 ≈ 10 posizioni equal-weight, 1.00 = tutto in una)"
        if positions
        else "nessuna posizione aperta: concentrazione nulla"
    )

    raw["sector_concentration"] = hhi(list(sector_totals.values())) if sector_totals else 0.0
    if sector_totals and equity_usd > 0:
        top_sector, top_amount = max(sector_totals.items(), key=lambda kv: kv[1])
        top_pct = top_amount / equity_usd * 100.0
        verso = "oltre" if top_pct > risk_rules.max_sector_exposure_pct else "entro"
        explanations["sector_concentration"] = (
            f"il settore {top_sector} pesa il {top_pct:.0f}%: {verso} la soglia "
            f"del {risk_rules.max_sector_exposure_pct:.0f}%"
        )
    else:
        explanations["sector_concentration"] = "nessuna posizione aperta: concentrazione nulla"

    if equity_usd > 0:
        exposure_pct = exposure_usd / equity_usd * 100.0
        raw["exposure"] = exposure_pct / risk_rules.max_total_exposure_pct
        explanations["exposure"] = (
            f"esposizione {exposure_pct:.0f}% dell'equity, "
            f"{raw['exposure'] * 100:.0f}% del limite di {risk_rules.max_total_exposure_pct:.0f}%"
        )
    else:
        raw["exposure"] = 0.0
        explanations["exposure"] = "equity nulla: nessuna esposizione"

    if equity_usd > 0:
        cash_pct = cash_usd / equity_usd * 100.0
        buffer_min = risk_rules.min_cash_buffer_pct
        if cash_pct <= buffer_min:
            raw["cash_buffer"] = 1.0
        else:
            raw["cash_buffer"] = max(0.0, (100.0 - cash_pct) / (100.0 - buffer_min))
        explanations["cash_buffer"] = (
            f"liquidità {cash_pct:.0f}% dell'equity (buffer minimo {buffer_min:.0f}%)"
        )
    else:
        raw["cash_buffer"] = 0.0
        explanations["cash_buffer"] = "equity nulla: cash buffer non valutabile"

    vol = _annualized_volatility(equity_returns)
    raw["realized_volatility_90d"] = vol
    explanations["realized_volatility_90d"] = (
        f"volatilità annualizzata {vol * 100:.1f}% sugli ultimi {len(equity_returns)} rendimenti"
        if vol is not None
        else "serie equity insufficiente per stimare la volatilità"
    )

    dd = _current_drawdown(equity_returns)
    raw["current_drawdown"] = dd
    explanations["current_drawdown"] = (
        f"drawdown corrente {dd * 100:.1f}% dal massimo storico"
        if dd is not None
        else "serie equity insufficiente per stimare il drawdown"
    )

    beta = _beta(equity_returns, spy_returns)
    raw["beta_vs_spy"] = beta
    explanations["beta_vs_spy"] = (
        f"beta {beta:.2f} vs SPY"
        if beta is not None
        else "dati benchmark insufficienti per stimare il beta"
    )

    max_losses = risk_rules.circuit_breaker.max_consecutive_losses
    consecutive = int(breaker_state.get("consecutive_losses", 0))
    if breaker_state.get("tripped"):
        raw["safety_state"] = 1.0
        explanations["safety_state"] = "circuit breaker scattato: aperture bloccate"
    else:
        raw["safety_state"] = min(1.0, consecutive / max_losses) if max_losses > 0 else 0.0
        explanations["safety_state"] = (
            f"{consecutive} perdite consecutive su una soglia breaker di {max_losses}"
        )

    # --- normalizzazione, breakdown e media pesata ---------------------------
    breakdown: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for key, weight in weights.items():
        th = thresholds.get(key, {"low": 0.0, "high": 1.0})
        value = raw.get(key)
        value_0_10 = normalize(value, float(th["low"]), float(th["high"])) if value is not None else 0.0
        weighted_sum += weight * value_0_10
        weight_total += weight
        breakdown.append(
            {
                "key": key,
                "label": _LABELS.get(key, key),
                "weight_pct": round(weight * 100.0, 1),
                "value_0_10": round(value_0_10, 2),
                "explanation": explanations.get(key, ""),
                "suggestion": _SUGGESTIONS.get(key) if value_0_10 > SUGGESTION_THRESHOLD else None,
            }
        )

    score = weighted_sum / weight_total if weight_total > 0 else 0.0
    score = max(1.0, round(score, 1))
    return RiskScoreResult(score=score, band=_band_for(score, bands), breakdown=breakdown)


# --- servizio ---------------------------------------------------------------


class RiskScoreService:
    """Assembla gli input dal repo e persiste lo snapshot giornaliero dello score."""

    def __init__(
        self,
        repo: Repository,
        risk_rules: RiskRules | None = None,
        cfg: dict[str, Any] | None = None,
        state_dir: str | Path | None = None,
    ):
        self._repo = repo
        self._rules = risk_rules or load_risk_rules()
        self._cfg = cfg or load_risk_score_config()
        self._state_dir = state_dir

    def compute_and_store(
        self, day: date | None = None, spy_returns: list[float] | None = None
    ) -> RiskScoreResult:
        positions = [
            Position(
                etoro_position_id=p.etoro_position_id,
                symbol=p.symbol,
                instrument_id=p.instrument_id,
                amount_usd=p.amount_usd,
                entry_price=p.entry_price,
                opened_at=p.opened_at,
                sector=p.sector,
            )
            for p in self._repo.open_positions()
        ]

        snaps = self._repo.equity_series()
        if snaps:
            cash_usd = snaps[-1].cash_usd
        else:
            cash_usd = 0.0
        window = snaps[-(VOLATILITY_WINDOW_DAYS + 1):]
        equity_returns = daily_returns([(s.date, s.equity_usd) for s in window])

        breaker = CircuitBreaker(self._rules.circuit_breaker, state_dir=self._state_dir)
        result = compute_risk_score(
            positions=positions,
            cash_usd=cash_usd,
            equity_returns=equity_returns,
            spy_returns=spy_returns,
            breaker_state=asdict(breaker.state),
            risk_rules=self._rules,
            cfg=self._cfg,
        )
        self._repo.record_risk_score(
            day or datetime.now(timezone.utc).date(),
            result.score,
            {"band": result.band, "breakdown": result.breakdown},
        )
        return result
