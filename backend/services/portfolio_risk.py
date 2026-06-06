"""Composite portfolio risk score and risk-based position sizing.

Pure computation: depends only on plain position dicts, account equity, and an
injected ``history_provider(symbol, limit) -> list[bar dict]`` callable (in
production ``DataManager.get_symbol_history``). No DB/broker imports here so the
math stays unit-testable in isolation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any, Callable

from core.utils import AppConfig

_TRADING_DAYS = {"STOCK": 252.0, "CRYPTO": 365.0}

HistoryProvider = Callable[[str, int], list[dict[str, Any]]]


@dataclass(slots=True)
class RiskAssessment:
    score: float
    portfolio_vol: float
    budget_vol: float
    components: dict[str, float]
    hhi: float
    n_eff: float
    avg_correlation: float
    exposure: float
    per_position_risk_contribution: dict[str, float]
    low_confidence: bool
    over_alert: bool
    over_hard: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PortfolioRiskService:
    """Compute the portfolio risk score and risk-based sizes."""

    def __init__(self, config: AppConfig, logger: logging.Logger, history_provider: HistoryProvider) -> None:
        self.config = config
        self.logger = logger.getChild("portfolio_risk")
        self._history = history_provider

    # -- low-level statistics (all static, pure) --------------------------

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    @staticmethod
    def _closes_by_ts(bars: list[dict[str, Any]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for bar in bars:
            ts = bar.get("timestamp")
            raw = bar.get("close")
            if ts is None or raw in (None, ""):
                continue
            try:
                close = float(raw)
            except (TypeError, ValueError):
                continue
            if close > 0:
                out[str(ts)] = close
        return out

    @staticmethod
    def _returns_by_ts(closes_by_ts: dict[str, float]) -> dict[str, float]:
        items = sorted(closes_by_ts.items())
        out: dict[str, float] = {}
        for (_, prev), (ts, cur) in zip(items, items[1:]):
            if prev > 0 and cur > 0:
                out[ts] = math.log(cur / prev)
        return out

    @staticmethod
    def _annualized_vol(returns: list[float], category: str) -> float | None:
        n = len(returns)
        if n < 2:
            return None
        mean = sum(returns) / n
        variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
        return math.sqrt(variance) * math.sqrt(_TRADING_DAYS.get(str(category).upper(), 252.0))

    @staticmethod
    def _pearson(returns_a: dict[str, float], returns_b: dict[str, float]) -> float | None:
        common = sorted(set(returns_a) & set(returns_b))
        n = len(common)
        if n < 3:
            return None
        xa = [returns_a[t] for t in common]
        xb = [returns_b[t] for t in common]
        ma = sum(xa) / n
        mb = sum(xb) / n
        sab = sum((a - ma) * (b - mb) for a, b in zip(xa, xb))
        saa = sum((a - ma) ** 2 for a in xa)
        sbb = sum((b - mb) ** 2 for b in xb)
        if saa <= 0 or sbb <= 0:
            return None
        return sab / math.sqrt(saa * sbb)

    def _default_vol(self, category: str) -> float:
        if str(category).upper() == "CRYPTO":
            return self.config.risk_default_crypto_vol
        return self.config.risk_default_stock_vol

    def _symbol_stats(
        self, symbol_categories: list[tuple[str, str]]
    ) -> tuple[dict[str, float], dict[str, dict[str, float]], bool]:
        """Return (annualized vols, returns-by-ts per symbol, low_confidence)."""
        vols: dict[str, float] = {}
        returns_map: dict[str, dict[str, float]] = {}
        low_confidence = False
        lookback = self.config.risk_lookback_days
        for symbol, category in symbol_categories:
            bars = self._history(symbol, lookback) or []
            returns = self._returns_by_ts(self._closes_by_ts(bars))
            returns_map[symbol] = returns
            vol = self._annualized_vol(list(returns.values()), category)
            if vol is None or vol <= 0:
                vols[symbol] = self._default_vol(category)
                low_confidence = True
            else:
                vols[symbol] = vol
        return vols, returns_map, low_confidence

    def _shrunk_correlation(
        self, sym_a: str, sym_b: str, returns_map: dict[str, dict[str, float]]
    ) -> float:
        """Pairwise correlation shrunk toward a constant 0.5 prior for stability.

        ``risk_corr_shrinkage`` (lam) is the weight on the *sample* correlation:
        result = lam*sample + (1-lam)*prior. So lam=1 keeps the raw sample, lam=0
        ignores it entirely.
        """
        prior = 0.5
        lam = self.config.risk_corr_shrinkage
        if sym_a == sym_b:
            return 1.0
        sample = self._pearson(returns_map.get(sym_a, {}), returns_map.get(sym_b, {}))
        if sample is None:
            return prior
        return lam * sample + (1.0 - lam) * prior

    def _portfolio_vol(
        self,
        weights: dict[str, float],
        vols: dict[str, float],
        returns_map: dict[str, dict[str, float]],
    ) -> float:
        symbols = list(weights.keys())
        variance = 0.0
        for a in symbols:
            for b in symbols:
                rho = 1.0 if a == b else self._shrunk_correlation(a, b, returns_map)
                variance += weights[a] * weights[b] * rho * vols[a] * vols[b]
        return math.sqrt(variance) if variance > 0 else 0.0

    def _budget_vol(self) -> float:
        rt = self._clamp(float(self.config.risk_tolerance), 1.0, 10.0)
        lo = self.config.risk_budget_vol_min
        hi = self.config.risk_budget_vol_max
        return lo + (rt - 1.0) / 9.0 * (hi - lo)

    def _normalized_weights(self) -> tuple[float, float, float, float]:
        raw = (
            self.config.risk_weight_vol,
            self.config.risk_weight_concentration,
            self.config.risk_weight_correlation,
            self.config.risk_weight_exposure,
        )
        total = sum(raw)
        if total <= 0:
            return (0.25, 0.25, 0.25, 0.25)
        return tuple(w / total for w in raw)  # type: ignore[return-value]

    def assess(self, positions: list[dict[str, Any]], equity: float) -> RiskAssessment:
        budget = self._budget_vol()
        empty = RiskAssessment(
            score=0.0, portfolio_vol=0.0, budget_vol=budget,
            components={"vol": 0.0, "concentration": 0.0, "correlation": 0.0, "exposure": 0.0},
            hhi=0.0, n_eff=0.0, avg_correlation=0.0, exposure=0.0,
            per_position_risk_contribution={}, low_confidence=(equity <= 0),
            over_alert=False, over_hard=False,
        )
        valid = [p for p in positions if float(p.get("value") or 0.0) > 0 and p.get("symbol")]
        if not valid or equity <= 0:
            return empty

        invested = sum(float(p["value"]) for p in valid)
        symbol_categories = [(str(p["symbol"]).upper(), str(p.get("category") or "STOCK")) for p in valid]
        vols, returns_map, low_conf = self._symbol_stats(symbol_categories)

        eq_weights = {str(p["symbol"]).upper(): float(p["value"]) / equity for p in valid}
        hold_weights = {str(p["symbol"]).upper(): float(p["value"]) / invested for p in valid}

        sigma_p = self._portfolio_vol(eq_weights, vols, returns_map)
        vol_score = self._clamp(sigma_p / budget * 50.0, 0.0, 100.0) if budget > 0 else 0.0

        hhi = sum(w * w for w in hold_weights.values())
        n_eff = (1.0 / hhi) if hhi > 0 else 0.0
        target = max(self.config.max_open_trades_stock + self.config.max_open_trades_crypto, 1)
        if target > 1:
            conc_score = self._clamp((hhi - 1.0 / target) / (1.0 - 1.0 / target) * 100.0, 0.0, 100.0)
        else:
            conc_score = 100.0 if hhi > 0 else 0.0

        symbols = list(hold_weights.keys())
        pair_num = 0.0
        pair_den = 0.0
        for i in range(len(symbols)):
            for j in range(i + 1, len(symbols)):
                a, b = symbols[i], symbols[j]
                rho = self._shrunk_correlation(a, b, returns_map)
                weight = hold_weights[a] * hold_weights[b]
                pair_num += weight * rho
                pair_den += weight
        avg_corr = (pair_num / pair_den) if pair_den > 0 else 0.0
        corr_score = self._clamp((avg_corr - 0.2) / (0.8 - 0.2) * 100.0, 0.0, 100.0)

        exposure = invested / equity
        exp_score = self._clamp(exposure * 100.0, 0.0, 100.0)

        wv, wc, wr, we = self._normalized_weights()
        score = round(wv * vol_score + wc * conc_score + wr * corr_score + we * exp_score, 2)

        contributions: dict[str, float] = {}
        if sigma_p > 0:
            variance = sigma_p * sigma_p
            for a in symbols:
                marginal = sum(
                    eq_weights[b] * (1.0 if a == b else self._shrunk_correlation(a, b, returns_map))
                    * vols[a] * vols[b]
                    for b in symbols
                )
                contributions[a] = round(eq_weights[a] * marginal / variance * 100.0, 2)

        return RiskAssessment(
            score=score, portfolio_vol=round(sigma_p, 4), budget_vol=round(budget, 4),
            components={"vol": round(vol_score, 2), "concentration": round(conc_score, 2),
                        "correlation": round(corr_score, 2), "exposure": round(exp_score, 2)},
            hhi=round(hhi, 4), n_eff=round(n_eff, 2), avg_correlation=round(avg_corr, 4),
            exposure=round(exposure, 4), per_position_risk_contribution=contributions,
            low_confidence=low_conf, over_alert=score >= self.config.risk_alert_threshold,
            over_hard=score >= self.config.risk_hard_threshold,
        )
