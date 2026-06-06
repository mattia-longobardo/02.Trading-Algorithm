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
        """Pairwise correlation shrunk toward a constant prior for stability."""
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
