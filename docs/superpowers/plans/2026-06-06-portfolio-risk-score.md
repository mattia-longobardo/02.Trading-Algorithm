# Portfolio Risk Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a composite 0-100 portfolio risk score (volatility + concentration + correlation + exposure) with risk-based position sizing, wired into entry decisions, GPT prompts, and a dashboard API.

**Architecture:** A new pure-ish `PortfolioRiskService` (`backend/services/portfolio_risk.py`) computes the score and risk-based sizes from injected positions + a price-history callable (`DataManager.get_symbol_history`) and account equity. `TradeManager` owns an instance and uses it for sizing + an entry gate (falling back to equal-slot when data is missing); `gpt_client` receives a `portfolio_risk` context block; a `/api/risk` endpoint exposes the assessment.

**Tech Stack:** Python 3.14, stdlib `unittest` + `unittest.mock`, stdlib `math` only (no numpy), SQLite-backed OHLCV via `DataManager`.

---

## Conventions

**Working directory:** worktree root `/home/mattia/docker/projects/trading/.claude/worktrees/portfolio-risk` (branch `worktree-portfolio-risk`, based on `dev-2.0`).

**Test command (source-mounted; service name is `backend`; run from worktree root):**
```bash
docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.<module> -v
```
The compose service does NOT mount source by default, so the `-v "$PWD/backend:/app"` bind is required. Unrelated `data/`/`logs/`/`run/` dir-permission errors are a known env issue (chmod 777 them if needed). Intentional `Exception("no gpt")` tracebacks in some tests are expected; check the final `OK`.

**Full suite:**
```bash
docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest discover -s tests -v
```

**Commit cadence:** one commit per task after its tests pass. End every commit message with:
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

---

## File Structure

- **Create** `backend/services/portfolio_risk.py` — `RiskAssessment` dataclass + `PortfolioRiskService` (statistics helpers, `assess`, `suggest_size`, `project`). One clear responsibility: portfolio risk math. No DB/broker imports — depends on an injected history callable and plain position dicts.
- **Modify** `backend/core/utils.py` — risk config fields + env loading.
- **Modify** `backend/services/trade_manager.py` — own a `PortfolioRiskService`, build positions/equity, risk-based allocation + entry gate, GPT context, `portfolio_risk_snapshot()`.
- **Modify** `backend/clients/gpt_client.py` — optional `portfolio_risk` block in entry/batch constraints + one prompt sentence each.
- **Modify** `backend/api/api_server.py` — `GET /api/risk`.
- **Create** `backend/tests/test_portfolio_risk.py` — service unit tests.
- **Modify** `backend/tests/test_trade_manager_etoro.py` — sizing/gate tests (or a new `tests/test_trade_manager_risk.py` if cleaner).

---

## Task 1: Risk config knobs

**Files:**
- Modify: `backend/core/utils.py`
- Test: `backend/tests/test_etoro_config.py`

- [ ] **Step 1: Write the failing test**

Add to `class EtoroConfigTests` in `backend/tests/test_etoro_config.py`:

```python
    def test_risk_defaults(self):
        config = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        self.assertEqual(config.risk_weight_vol, 0.30)
        self.assertEqual(config.risk_weight_concentration, 0.30)
        self.assertEqual(config.risk_weight_correlation, 0.25)
        self.assertEqual(config.risk_weight_exposure, 0.15)
        self.assertEqual(config.risk_budget_vol_min, 0.10)
        self.assertEqual(config.risk_budget_vol_max, 0.45)
        self.assertEqual(config.risk_lookback_days, 120)
        self.assertEqual(config.risk_alert_threshold, 70.0)
        self.assertEqual(config.risk_hard_threshold, 85.0)
        self.assertEqual(config.risk_sizing_corr_floor, 0.30)
        self.assertEqual(config.risk_max_position_pct, 0.25)
        self.assertEqual(config.risk_default_stock_vol, 0.30)
        self.assertEqual(config.risk_default_crypto_vol, 0.60)
        self.assertEqual(config.risk_corr_shrinkage, 0.6)

    def test_load_config_reads_risk_env(self):
        env = {
            "OPENAI_API_KEY": "o",
            "RISK_WEIGHT_CONCENTRATION": "0.4",
            "RISK_LOOKBACK_DAYS": "90",
            "RISK_HARD_THRESHOLD": "80",
            "RISK_MAX_POSITION_PCT": "0.2",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.risk_weight_concentration, 0.4)
        self.assertEqual(config.risk_lookback_days, 90)
        self.assertEqual(config.risk_hard_threshold, 80.0)
        self.assertEqual(config.risk_max_position_pct, 0.2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_config -v`
Expected: FAIL with `AttributeError: 'AppConfig' object has no attribute 'risk_weight_vol'`.

- [ ] **Step 3: Add dataclass fields**

In `backend/core/utils.py`, inside `class AppConfig`, immediately after the `universe_crypto_shortlist: int = 150` line, add:

```python
    risk_weight_vol: float = 0.30
    risk_weight_concentration: float = 0.30
    risk_weight_correlation: float = 0.25
    risk_weight_exposure: float = 0.15
    risk_budget_vol_min: float = 0.10
    risk_budget_vol_max: float = 0.45
    risk_lookback_days: int = 120
    risk_corr_shrinkage: float = 0.6
    risk_alert_threshold: float = 70.0
    risk_hard_threshold: float = 85.0
    risk_sizing_corr_floor: float = 0.30
    risk_max_position_pct: float = 0.25
    risk_default_stock_vol: float = 0.30
    risk_default_crypto_vol: float = 0.60
```

- [ ] **Step 4: Wire env loading**

In `backend/core/utils.py`, inside `load_config`, immediately after the `universe_crypto_shortlist=...` line, add:

```python
        risk_weight_vol=max(0.0, float(os.getenv("RISK_WEIGHT_VOL", "0.30"))),
        risk_weight_concentration=max(0.0, float(os.getenv("RISK_WEIGHT_CONCENTRATION", "0.30"))),
        risk_weight_correlation=max(0.0, float(os.getenv("RISK_WEIGHT_CORRELATION", "0.25"))),
        risk_weight_exposure=max(0.0, float(os.getenv("RISK_WEIGHT_EXPOSURE", "0.15"))),
        risk_budget_vol_min=max(0.01, float(os.getenv("RISK_BUDGET_VOL_MIN", "0.10"))),
        risk_budget_vol_max=max(0.02, float(os.getenv("RISK_BUDGET_VOL_MAX", "0.45"))),
        risk_lookback_days=max(20, int(os.getenv("RISK_LOOKBACK_DAYS", "120"))),
        risk_corr_shrinkage=min(1.0, max(0.0, float(os.getenv("RISK_CORR_SHRINKAGE", "0.6")))),
        risk_alert_threshold=float(os.getenv("RISK_ALERT_THRESHOLD", "70")),
        risk_hard_threshold=float(os.getenv("RISK_HARD_THRESHOLD", "85")),
        risk_sizing_corr_floor=min(1.0, max(0.0, float(os.getenv("RISK_SIZING_CORR_FLOOR", "0.30")))),
        risk_max_position_pct=min(1.0, max(0.01, float(os.getenv("RISK_MAX_POSITION_PCT", "0.25")))),
        risk_default_stock_vol=max(0.01, float(os.getenv("RISK_DEFAULT_STOCK_VOL", "0.30"))),
        risk_default_crypto_vol=max(0.01, float(os.getenv("RISK_DEFAULT_CRYPTO_VOL", "0.60"))),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_config -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/core/utils.py backend/tests/test_etoro_config.py
git commit -m "feat(risk): add portfolio-risk config knobs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Statistics helpers (returns, volatility, correlation)

**Files:**
- Create: `backend/services/portfolio_risk.py`
- Test: `backend/tests/test_portfolio_risk.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_portfolio_risk.py`:

```python
import logging
import math
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig
from services.portfolio_risk import PortfolioRiskService


def _bars(closes, start_ts=1):
    # ascending daily bars; timestamps as zero-padded ints so string sort == time order
    return [{"timestamp": f"{start_ts + i:04d}", "close": c} for i, c in enumerate(closes)]


def _service():
    cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
    return PortfolioRiskService(cfg, logging.getLogger("t"), history_provider=lambda s, l: [])


class StatHelperTests(unittest.TestCase):
    def test_closes_and_returns_by_ts(self):
        svc = _service()
        closes = svc._closes_by_ts(_bars([10.0, 11.0, 0.0, 12.0]))
        self.assertEqual(closes["0001"], 10.0)
        self.assertNotIn("0003", closes)  # close 0.0 dropped
        rets = svc._returns_by_ts({"0001": 10.0, "0002": 11.0})
        self.assertAlmostEqual(rets["0002"], math.log(11.0 / 10.0))

    def test_annualized_vol(self):
        svc = _service()
        rets = [0.01, -0.01, 0.02, -0.02, 0.0, 0.01]
        vol = svc._annualized_vol(rets, "STOCK")
        self.assertIsNotNone(vol)
        self.assertGreater(vol, 0.0)
        # crypto annualizes with 365 vs 252 → strictly larger for same series
        self.assertGreater(svc._annualized_vol(rets, "CRYPTO"), vol)
        self.assertIsNone(svc._annualized_vol([0.01], "STOCK"))

    def test_pearson_alignment(self):
        svc = _service()
        a = {"01": 0.1, "02": -0.1, "03": 0.2, "04": -0.2}
        same = {"01": 0.1, "02": -0.1, "03": 0.2, "04": -0.2}
        opp = {"01": -0.1, "02": 0.1, "03": -0.2, "04": 0.2}
        self.assertAlmostEqual(svc._pearson(a, same), 1.0, places=6)
        self.assertAlmostEqual(svc._pearson(a, opp), -1.0, places=6)
        self.assertIsNone(svc._pearson(a, {"01": 0.1}))  # <3 overlap


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.portfolio_risk'`.

- [ ] **Step 3: Create the module with helpers**

Create `backend/services/portfolio_risk.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/portfolio_risk.py backend/tests/test_portfolio_risk.py
git commit -m "feat(risk): portfolio risk service skeleton + statistics helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Per-symbol stats + correlation/covariance + portfolio volatility

**Files:**
- Modify: `backend/services/portfolio_risk.py`
- Test: `backend/tests/test_portfolio_risk.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_portfolio_risk.py` (new class):

```python
class PortfolioVolTests(unittest.TestCase):
    def _svc_with_history(self, history: dict):
        cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        return PortfolioRiskService(cfg, logging.getLogger("t"),
                                    history_provider=lambda s, l: history.get(s, []))

    def test_symbol_vols_and_fallback(self):
        # AAA has history; ZZZ has none -> conservative default + low_confidence flag
        hist = {"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3, 10.1])}
        svc = self._svc_with_history(hist)
        vols, returns_map, low_conf = svc._symbol_stats(
            [("AAA", "STOCK"), ("ZZZ", "STOCK")]
        )
        self.assertGreater(vols["AAA"], 0.0)
        self.assertEqual(vols["ZZZ"], svc.config.risk_default_stock_vol)  # fallback
        self.assertTrue(low_conf)
        self.assertIn("AAA", returns_map)

    def test_portfolio_vol_correlation_effect(self):
        # two perfectly correlated names => portfolio vol == single-name vol
        up = [10, 11, 12.1, 13.31, 14.641, 16.105, 17.716]
        hist = {"AAA": _bars(up), "BBB": _bars(up)}
        svc = self._svc_with_history(hist)
        vols, returns_map, _ = svc._symbol_stats([("AAA", "STOCK"), ("BBB", "STOCK")])
        # equal weights 0.5/0.5 vs equity, fully correlated
        sigma_p = svc._portfolio_vol(
            weights={"AAA": 0.5, "BBB": 0.5},
            vols=vols, returns_map=returns_map,
        )
        self.assertAlmostEqual(sigma_p, vols["AAA"], places=4)

    def test_portfolio_vol_diversification_reduces(self):
        up = [10, 11, 12.1, 13.31, 14.641, 16.105, 17.716]
        down = list(reversed(up))
        hist = {"AAA": _bars(up), "BBB": _bars(down)}
        svc = self._svc_with_history(hist)
        vols, returns_map, _ = svc._symbol_stats([("AAA", "STOCK"), ("BBB", "STOCK")])
        sigma_p = svc._portfolio_vol({"AAA": 0.5, "BBB": 0.5}, vols, returns_map)
        # anti-correlated holdings -> portfolio vol strictly below the single-name vol
        self.assertLess(sigma_p, vols["AAA"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk.PortfolioVolTests -v`
Expected: FAIL with `AttributeError: ... '_symbol_stats'`.

- [ ] **Step 3: Add per-symbol stats, shrunk correlation, and portfolio vol**

In `backend/services/portfolio_risk.py`, add these methods to `PortfolioRiskService` (after `_pearson`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk.PortfolioVolTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/portfolio_risk.py backend/tests/test_portfolio_risk.py
git commit -m "feat(risk): per-symbol vol, shrunk correlation, portfolio volatility

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `RiskAssessment` + `assess()` (components, score, budget)

**Files:**
- Modify: `backend/services/portfolio_risk.py`
- Test: `backend/tests/test_portfolio_risk.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_portfolio_risk.py`:

```python
class AssessTests(unittest.TestCase):
    def _svc(self, history=None, **cfg_over):
        cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                        max_open_trades_stock=3, max_open_trades_crypto=3, **cfg_over)
        history = history or {}
        return PortfolioRiskService(cfg, logging.getLogger("t"),
                                    history_provider=lambda s, l: history.get(s, []))

    def test_budget_vol_mapping(self):
        svc = self._svc(risk_tolerance=1)
        self.assertAlmostEqual(svc._budget_vol(), 0.10, places=6)
        svc = self._svc(risk_tolerance=10)
        self.assertAlmostEqual(svc._budget_vol(), 0.45, places=6)

    def test_empty_portfolio(self):
        svc = self._svc()
        a = svc.assess([], equity=10_000.0)
        self.assertEqual(a.score, 0.0)
        self.assertEqual(a.exposure, 0.0)
        self.assertFalse(a.over_alert)

    def test_single_position_concentration_max(self):
        svc = self._svc(history={"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3])})
        a = svc.assess([{"symbol": "AAA", "category": "STOCK", "value": 5_000.0}], equity=10_000.0)
        self.assertEqual(a.components["concentration"], 100.0)  # one name = max concentration
        self.assertEqual(a.components["correlation"], 0.0)       # no pairs
        self.assertAlmostEqual(a.exposure, 0.5, places=6)
        self.assertEqual(a.components["exposure"], 50.0)

    def test_correlated_vs_diversified_score(self):
        up = [10, 11, 12.1, 13.31, 14.641, 16.105, 17.716]
        down = list(reversed(up))
        corr = self._svc(history={"AAA": _bars(up), "BBB": _bars(up)})
        div = self._svc(history={"AAA": _bars(up), "BBB": _bars(down)})
        pos = [{"symbol": "AAA", "category": "STOCK", "value": 5_000.0},
               {"symbol": "BBB", "category": "STOCK", "value": 5_000.0}]
        self.assertGreater(corr.assess(pos, 10_000.0).score, div.assess(pos, 10_000.0).score)

    def test_over_thresholds_and_low_confidence(self):
        svc = self._svc(history={"AAA": _bars([10, 13, 9, 14, 8, 15, 7])},
                        risk_tolerance=1, risk_hard_threshold=10.0, risk_alert_threshold=5.0)
        a = svc.assess([{"symbol": "AAA", "category": "STOCK", "value": 9_000.0},
                        {"symbol": "ZZZ", "category": "STOCK", "value": 1_000.0}], equity=10_000.0)
        self.assertTrue(a.over_alert)
        self.assertTrue(a.over_hard)
        self.assertTrue(a.low_confidence)  # ZZZ had no history
        self.assertEqual(round(sum(a.per_position_risk_contribution.values())), 100)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk.AssessTests -v`
Expected: FAIL with `AttributeError: ... '_budget_vol'` / no `assess`.

- [ ] **Step 3: Add `RiskAssessment`, `_budget_vol`, `_normalized_weights`, `assess`**

In `backend/services/portfolio_risk.py`, add the dataclass at module level (after the `HistoryProvider = ...` line):

```python
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
```

Then add these methods to `PortfolioRiskService` (after `_portfolio_vol`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk.AssessTests -v`
Expected: PASS.

- [ ] **Step 5: Run the whole module (regression)**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/portfolio_risk.py backend/tests/test_portfolio_risk.py
git commit -m "feat(risk): RiskAssessment + composite assess() (vol/conc/corr/exposure)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Risk-based `suggest_size()` + `project()`

**Files:**
- Modify: `backend/services/portfolio_risk.py`
- Test: `backend/tests/test_portfolio_risk.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_portfolio_risk.py`:

```python
class SizingTests(unittest.TestCase):
    def _svc(self, history=None, **cfg_over):
        cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                        max_open_trades_stock=3, max_open_trades_crypto=3,
                        etoro_min_trade_amount=50.0, **cfg_over)
        history = history or {}
        return PortfolioRiskService(cfg, logging.getLogger("t"),
                                    history_provider=lambda s, l: history.get(s, []))

    def test_high_vol_gets_smaller_size(self):
        calm = _bars([10, 10.05, 9.97, 10.03, 10.0, 10.04, 10.01])
        wild = _bars([10, 12, 8, 13, 7, 14, 6])
        svc = self._svc(history={"CALM": calm, "WILD": wild})
        size_calm = svc.suggest_size({"symbol": "CALM", "category": "STOCK"}, [], 10_000.0, 10_000.0)
        size_wild = svc.suggest_size({"symbol": "WILD", "category": "STOCK"}, [], 10_000.0, 10_000.0)
        self.assertGreater(size_calm, size_wild)

    def test_size_clamps_to_max_position_pct_and_cash(self):
        calm = _bars([10, 10.01, 10.0, 10.02, 10.01, 10.0])  # very low vol -> large raw size
        svc = self._svc(history={"CALM": calm}, risk_max_position_pct=0.25)
        size = svc.suggest_size({"symbol": "CALM", "category": "STOCK"}, [], 10_000.0, 10_000.0)
        self.assertLessEqual(size, 2_500.0 + 1e-6)  # 25% of equity
        # tiny cash -> clamped to cash
        size2 = svc.suggest_size({"symbol": "CALM", "category": "STOCK"}, [], 10_000.0, 80.0)
        self.assertLessEqual(size2, 80.0 + 1e-6)

    def test_size_zero_when_cash_below_min(self):
        svc = self._svc(history={"AAA": _bars([10, 10.1, 9.9, 10.2])})
        self.assertEqual(svc.suggest_size({"symbol": "AAA", "category": "STOCK"}, [], 10_000.0, 10.0), 0.0)

    def test_project_adds_candidate(self):
        up = [10, 11, 12.1, 13.31, 14.641, 16.105, 17.716]
        svc = self._svc(history={"AAA": _bars(up), "BBB": _bars(up)})
        pos = [{"symbol": "AAA", "category": "STOCK", "value": 5_000.0}]
        before = svc.assess(pos, 10_000.0)
        after = svc.project({"symbol": "BBB", "category": "STOCK"}, 4_000.0, pos, 10_000.0)
        self.assertGreater(after.exposure, before.exposure)
        self.assertIn("BBB", after.per_position_risk_contribution)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk.SizingTests -v`
Expected: FAIL with `AttributeError: ... 'suggest_size'`.

- [ ] **Step 3: Add `suggest_size` and `project`**

In `backend/services/portfolio_risk.py`, add to `PortfolioRiskService` (after `assess`):

```python
    def _candidate_vol(self, symbol: str, category: str) -> float:
        bars = self._history(symbol, self.config.risk_lookback_days) or []
        returns = self._returns_by_ts(self._closes_by_ts(bars))
        vol = self._annualized_vol(list(returns.values()), category)
        return vol if vol and vol > 0 else self._default_vol(category)

    def _candidate_correlation(
        self, symbol: str, positions: list[dict[str, Any]], invested: float
    ) -> float:
        if not positions or invested <= 0:
            return 1.0
        bars = self._history(symbol, self.config.risk_lookback_days) or []
        cand_returns = self._returns_by_ts(self._closes_by_ts(bars))
        num = 0.0
        den = 0.0
        prior = 0.5
        lam = self.config.risk_corr_shrinkage
        for p in positions:
            sym = str(p["symbol"]).upper()
            weight = float(p["value"]) / invested
            other = self._returns_by_ts(self._closes_by_ts(self._history(sym, self.config.risk_lookback_days) or []))
            sample = self._pearson(cand_returns, other)
            rho = prior if sample is None else (lam * sample + (1.0 - lam) * prior)
            num += weight * rho
            den += weight
        return (num / den) if den > 0 else prior

    def suggest_size(
        self,
        candidate: dict[str, Any],
        positions: list[dict[str, Any]],
        equity: float,
        available_cash: float,
    ) -> float:
        if equity <= 0 or available_cash <= 0:
            return 0.0
        symbol = str(candidate["symbol"]).upper()
        category = str(candidate.get("category") or "STOCK")
        invested = sum(float(p.get("value") or 0.0) for p in positions if float(p.get("value") or 0.0) > 0)
        sigma_c = self._candidate_vol(symbol, category)
        corr_c = max(self._candidate_correlation(symbol, positions, invested), self.config.risk_sizing_corr_floor)
        target = max(self.config.max_open_trades_stock + self.config.max_open_trades_crypto, 1)
        target_risk_per_slot = self._budget_vol() / target
        denom = sigma_c * corr_c
        if denom <= 0:
            return 0.0
        value = (target_risk_per_slot / denom) * equity
        value = min(value, available_cash, self.config.risk_max_position_pct * equity)
        minimum = float(getattr(self.config, "etoro_min_trade_amount", 0.0) or 0.0)
        if value < minimum:
            return minimum if available_cash >= minimum else 0.0
        return round(value, 2)

    def project(
        self,
        candidate: dict[str, Any],
        value: float,
        positions: list[dict[str, Any]],
        equity: float,
    ) -> RiskAssessment:
        combined = list(positions) + [{
            "symbol": str(candidate["symbol"]).upper(),
            "category": str(candidate.get("category") or "STOCK"),
            "value": float(value),
        }]
        return self.assess(combined, equity)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_portfolio_risk.SizingTests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/portfolio_risk.py backend/tests/test_portfolio_risk.py
git commit -m "feat(risk): risk-based suggest_size() + project()

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Wire risk-based sizing + entry gate into TradeManager

**Files:**
- Modify: `backend/services/trade_manager.py`
- Test: `backend/tests/test_trade_manager_risk.py` (new)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_trade_manager_risk.py`:

```python
import logging
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig, PROVIDER_ETORO


def _bars(closes):
    return [{"timestamp": f"{i:04d}", "close": c} for i, c in enumerate(closes)]


def _manager(history=None, open_trades=None, equity=10_000.0, cash=10_000.0):
    from services.trade_manager import TradeManager
    cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                    max_open_trades_stock=3, max_open_trades_crypto=3, etoro_min_trade_amount=50.0)
    broker = Mock()
    broker.get_account_equity.return_value = equity
    broker.get_available_cash.return_value = cash
    data_manager = Mock()
    history = history or {}
    data_manager.get_symbol_history.side_effect = lambda s, l=None: history.get(str(s).upper(), [])
    gpt = Mock()
    tm = TradeManager(cfg, logging.getLogger("t"), {PROVIDER_ETORO: broker}, data_manager, gpt)
    tm.get_open_or_pending_trades = Mock(return_value=open_trades or [])
    return tm, broker


class RiskAllocationTests(unittest.TestCase):
    def test_risk_based_allocation_returns_positive(self):
        tm, _ = _manager(history={"CALM": _bars([10, 10.05, 9.97, 10.03, 10.0, 10.04, 10.01])})
        alloc = tm._risk_based_allocation("STOCK", "CALM", provider=PROVIDER_ETORO)
        self.assertGreater(alloc, 0.0)

    def test_falls_back_to_equal_slot_without_equity(self):
        tm, broker = _manager(equity=0.0)
        # equal-slot fallback: cash / slots = 10000 / 6
        alloc = tm._risk_based_allocation("STOCK", "AAA", provider=PROVIDER_ETORO)
        self.assertAlmostEqual(alloc, round(10_000.0 / 6, 2), places=2)

    def test_entry_gate_skips_when_over_hard_threshold(self):
        # force any addition over the hard threshold -> allocation 0 (skip)
        tm, _ = _manager(history={"WILD": _bars([10, 13, 8, 14, 7, 15, 6])})
        tm.config.risk_hard_threshold = 1.0  # everything is "over hard"
        alloc = tm._risk_based_allocation("STOCK", "WILD", provider=PROVIDER_ETORO)
        self.assertEqual(alloc, 0.0)
```

Note: if `TradeManager.__init__` positional order differs, adapt the constructor call — it is `(config, logger, broker_clients, data_manager, gpt_client)`.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_risk -v`
Expected: FAIL with `AttributeError: 'TradeManager' object has no attribute '_risk_based_allocation'`.

- [ ] **Step 3: Instantiate the service and add helpers**

In `backend/services/trade_manager.py`, add the import near the other service import (`from services.data_manager import DataManager`):

```python
from services.portfolio_risk import PortfolioRiskService
```

In `TradeManager.__init__`, after `self.data_manager = data_manager` (locate the existing assignment of `data_manager`), add:

```python
        history_provider = (
            self.data_manager.get_symbol_history
            if self.data_manager is not None
            else (lambda symbol, limit=None: [])
        )
        self.risk = PortfolioRiskService(config, self.logger, history_provider)
```

Add these methods to `TradeManager` (place them next to `compute_allocated_capital`, around line 254):

```python
    def _open_position_values(self, provider: str) -> list[dict[str, Any]]:
        """Current OPEN positions for *provider* as {symbol, category, value(USD)}."""
        positions: list[dict[str, Any]] = []
        for trade in self.get_open_or_pending_trades():
            if self._trade_provider(trade) != provider:
                continue
            if str(trade.get("status") or "").upper() != "OPEN":
                continue
            quantity = self._as_float(trade.get("quantity")) or 0.0
            current_price = self._as_float(trade.get("current_price")) or 0.0
            value = quantity * current_price
            if value <= 0:
                value = self._as_float(trade.get("allocated_capital")) or 0.0
            if value <= 0:
                continue
            positions.append({
                "symbol": str(trade.get("symbol")).upper(),
                "category": str(trade.get("category") or "STOCK"),
                "value": value,
            })
        return positions

    def _risk_based_allocation(self, category: str, symbol: str, provider: str = PROVIDER_ETORO) -> float:
        """Risk-based size for a new position, with an over-budget entry gate.

        Falls back to equal-slot allocation when equity/risk data is unavailable.
        Returns 0.0 to signal "skip" when the trade cannot fit under the hard
        risk threshold even at the minimum trade amount.
        """
        broker = self.broker(provider)
        if broker is None:
            return 0.0
        try:
            equity = float(broker.get_account_equity())
        except Exception:
            equity = 0.0
        if equity <= 0:
            return self.compute_allocated_capital(provider=provider)
        cash = float(broker.get_available_cash())
        positions = self._open_position_values(provider)
        candidate = {"symbol": str(symbol).upper(), "category": category}
        size = self.risk.suggest_size(candidate, positions, equity, cash)
        if size <= 0:
            return 0.0
        minimum = float(getattr(self.config, "etoro_min_trade_amount", 0.0) or 0.0) or 1.0
        projection = self.risk.project(candidate, size, positions, equity)
        tries = 0
        while projection.over_hard and size > minimum and tries < 8:
            size = round(max(minimum, size * 0.5), 2)
            projection = self.risk.project(candidate, size, positions, equity)
            tries += 1
        if projection.over_hard:
            self.logger.info(
                "Risk gate: skipping %s/%s — projected portfolio risk %.1f over hard threshold %.1f",
                provider, symbol, projection.score, self.config.risk_hard_threshold,
            )
            return 0.0
        return size
```

- [ ] **Step 4: Use it in the entry path**

In `backend/services/trade_manager.py`, in `_open_trade_from_signal`, replace the line:

```python
        allocated_capital = self.compute_allocated_capital(provider=provider)
```

with:

```python
        allocated_capital = self._risk_based_allocation(category, symbol, provider=provider)
```

(The existing `if allocated_capital <= 0: ... return False` immediately below now also handles the risk-gate skip.)

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_risk -v`
Expected: PASS.

- [ ] **Step 6: Run the existing trade-manager suite (regression)**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_etoro -v`
Expected: PASS. If a pre-existing test calls `_open_trade_from_signal`/`maybe_open_trade` with a Mock broker lacking `get_account_equity`, the new `_risk_based_allocation` calls it; a bare `Mock()` returns a truthy Mock, so `float(...)` raises → caught → equity=0 → equal-slot fallback (the old behavior those tests expect). Confirm green; if a test asserted exact allocation and now differs, set `broker.get_account_equity.side_effect = Exception("no equity")` in that test's setup to force the documented fallback, and report which test you adjusted.

- [ ] **Step 7: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_risk.py
git commit -m "feat(risk): risk-based sizing + over-budget entry gate in TradeManager

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Pass portfolio-risk context to GPT

**Files:**
- Modify: `backend/clients/gpt_client.py`
- Modify: `backend/services/trade_manager.py`
- Test: `backend/tests/test_trade_manager_risk.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_trade_manager_risk.py`:

```python
class RiskContextTests(unittest.TestCase):
    def test_build_risk_context_shape(self):
        tm, _ = _manager(history={"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3])},
                         open_trades=[{"symbol": "AAA", "category": "STOCK", "status": "OPEN",
                                       "quantity": 10, "current_price": 100.0,
                                       "allocated_capital": 1000.0, "provider": "etoro"}])
        ctx = tm._risk_context(provider=PROVIDER_ETORO)
        self.assertIn("score", ctx)
        self.assertIn("budget_vol", ctx)
        self.assertIn("avg_correlation", ctx)
        self.assertIn("remaining_budget", ctx)

    def test_risk_context_none_without_equity(self):
        tm, _ = _manager(equity=0.0)
        self.assertIsNone(tm._risk_context(provider=PROVIDER_ETORO))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_risk.RiskContextTests -v`
Expected: FAIL with `AttributeError: ... '_risk_context'`.

- [ ] **Step 3: Add `_risk_context` to TradeManager**

In `backend/services/trade_manager.py`, add (next to `_risk_based_allocation`):

```python
    def _risk_context(self, provider: str = PROVIDER_ETORO) -> dict[str, Any] | None:
        """Compact portfolio-risk block for GPT prompts, or None if unavailable."""
        broker = self.broker(provider)
        if broker is None:
            return None
        try:
            equity = float(broker.get_account_equity())
        except Exception:
            return None
        if equity <= 0:
            return None
        assessment = self.risk.assess(self._open_position_values(provider), equity)
        return {
            "score": assessment.score,
            "portfolio_vol": assessment.portfolio_vol,
            "budget_vol": assessment.budget_vol,
            "avg_correlation": assessment.avg_correlation,
            "n_eff": assessment.n_eff,
            "exposure": assessment.exposure,
            "remaining_budget": round(max(0.0, self.config.risk_hard_threshold - assessment.score), 2),
            "alert_threshold": self.config.risk_alert_threshold,
        }
```

- [ ] **Step 4: Accept the context in gpt_client**

In `backend/clients/gpt_client.py`, change `request_new_signal` to accept and inject the block. Replace its signature + body:

```python
    def request_new_signal(
        self,
        symbol: str,
        category: str,
        candles: list[dict[str, Any]],
        existing_trades: list[dict[str, Any]],
        provider: str = "etoro",
        portfolio_risk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.build_symbol_payload(symbol, category, candles, existing_trades, provider=provider)
        if portfolio_risk is not None:
            payload.setdefault("constraints", {})["portfolio_risk"] = portfolio_risk
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_NEW_SIGNAL, provider)
        default = INSTRUCTIONS_NEW_SIGNAL
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            NEW_SIGNAL_SCHEMA,
        )
```

And change `request_batch_trade_signals` to accept `portfolio_risk` and add it to the constraints dict. Add the parameter to the signature (after `provider: str = "etoro",`):

```python
        portfolio_risk: dict[str, Any] | None = None,
```

and inside the `"constraints": { ... }` literal, add as the last key:

```python
                "portfolio_risk": portfolio_risk,
```

- [ ] **Step 5: Add a prompt sentence (both instruction constants)**

In `backend/clients/gpt_client.py`, find the `INSTRUCTIONS_NEW_SIGNAL` text containing `"Honor constraints.risk_tolerance on a 1-10 scale where 10 is the highest risk appetite: low values should favor resilient, liquid, lower-volatility setups with tighter downside control; high values may accept more volatility and more aggressive upside theses. "` and append, in the same string, immediately after it:

```python
    "When constraints.portfolio_risk is present, treat it as the live portfolio state: prefer setups that are not highly correlated with existing holdings (avg_correlation) and avoid pushing the portfolio over its risk budget (score vs alert_threshold, remaining_budget); when remaining_budget is low, favor SKIP or defensive, uncorrelated names. "
```

Then find the `INSTRUCTIONS_BATCH_SIGNALS` text containing `"Honor constraints.risk_tolerance on a 1-10 scale where 10 means maximum tolerated risk. "` and append, in the same string, immediately after it, the identical sentence:

```python
    "When constraints.portfolio_risk is present, treat it as the live portfolio state: prefer setups that are not highly correlated with existing holdings (avg_correlation) and avoid pushing the portfolio over its risk budget (score vs alert_threshold, remaining_budget); when remaining_budget is low, favor SKIP or defensive, uncorrelated names. "
```

- [ ] **Step 6: Pass the context at the call sites**

In `backend/services/trade_manager.py`, at the `request_new_signal` call (around line 534), add the kwarg:

```python
        signal = self.gpt_client.request_new_signal(
            symbol, category, candles, [], provider=provider,
            portfolio_risk=self._risk_context(provider=provider),
        )
```

At the `request_batch_trade_signals` call (around line 983), add `portfolio_risk=self._risk_context(provider=provider)` to the existing keyword arguments (keep all current arguments unchanged).

- [ ] **Step 7: Run tests**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_risk tests.test_etoro_client -v`
Expected: PASS (new context tests + existing gpt/client tests unaffected by the optional param).

- [ ] **Step 8: Commit**

```bash
git add backend/clients/gpt_client.py backend/services/trade_manager.py backend/tests/test_trade_manager_risk.py
git commit -m "feat(risk): pass portfolio-risk context into GPT entry prompts

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `/api/risk` endpoint

**Files:**
- Modify: `backend/services/trade_manager.py` (snapshot helper)
- Modify: `backend/api/api_server.py`
- Test: `backend/tests/test_trade_manager_risk.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_trade_manager_risk.py`:

```python
class RiskSnapshotTests(unittest.TestCase):
    def test_snapshot_dict_shape(self):
        tm, _ = _manager(history={"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3])},
                         open_trades=[{"symbol": "AAA", "category": "STOCK", "status": "OPEN",
                                       "quantity": 10, "current_price": 100.0,
                                       "allocated_capital": 1000.0, "provider": "etoro"}])
        snap = tm.portfolio_risk_snapshot(provider=PROVIDER_ETORO)
        self.assertIn("score", snap)
        self.assertIn("components", snap)
        self.assertIn("per_position_risk_contribution", snap)
        self.assertIn("equity", snap)

    def test_snapshot_low_confidence_without_equity(self):
        tm, _ = _manager(equity=0.0)
        snap = tm.portfolio_risk_snapshot(provider=PROVIDER_ETORO)
        self.assertTrue(snap["low_confidence"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_risk.RiskSnapshotTests -v`
Expected: FAIL with `AttributeError: ... 'portfolio_risk_snapshot'`.

- [ ] **Step 3: Add the snapshot method**

In `backend/services/trade_manager.py`, add (next to `_risk_context`):

```python
    def portfolio_risk_snapshot(self, provider: str = PROVIDER_ETORO) -> dict[str, Any]:
        """Full risk assessment for the dashboard API (always returns a dict)."""
        broker = self.broker(provider)
        equity = 0.0
        if broker is not None:
            try:
                equity = float(broker.get_account_equity())
            except Exception:
                equity = 0.0
        positions = self._open_position_values(provider) if broker is not None else []
        assessment = self.risk.assess(positions, equity)
        snapshot = assessment.to_dict()
        snapshot["equity"] = round(equity, 2)
        snapshot["positions"] = len(positions)
        return snapshot
```

- [ ] **Step 4: Add the endpoint**

In `backend/api/api_server.py`, add a new route next to `get_allocation` (the `@app.get("/api/allocation")` block, around line 682):

```python
    @app.get("/api/risk")
    def get_risk(_user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        return scheduler.trade_manager.portfolio_risk_snapshot()
```

- [ ] **Step 5: Run tests**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_risk -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/trade_manager.py backend/api/api_server.py backend/tests/test_trade_manager_risk.py
git commit -m "feat(risk): portfolio_risk_snapshot() + GET /api/risk

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Document env vars + full verification

**Files:**
- Modify: `backend/.env.example`

- [ ] **Step 1: Document the new env vars**

Append to `backend/.env.example`, just after the `UNIVERSE_CRYPTO_SHORTLIST=150` line:

```bash
# --- Portfolio risk score --------------------------------------------------
# Composite 0-100 risk score = weighted(volatility, concentration, correlation,
# exposure). Weights are normalized to sum 1. Budget = annualized vol target
# mapped from RISK_TOLERANCE between min and max below.
RISK_WEIGHT_VOL=0.30
RISK_WEIGHT_CONCENTRATION=0.30
RISK_WEIGHT_CORRELATION=0.25
RISK_WEIGHT_EXPOSURE=0.15
RISK_BUDGET_VOL_MIN=0.10
RISK_BUDGET_VOL_MAX=0.45
RISK_LOOKBACK_DAYS=120
RISK_CORR_SHRINKAGE=0.6
# Score >= alert -> dashboard alert; >= hard -> new entries are shrunk/skipped.
RISK_ALERT_THRESHOLD=70
RISK_HARD_THRESHOLD=85
# Risk-based sizing: min correlation assumed to a held book (anti-oversizing),
# and the max share of equity a single new position may take.
RISK_SIZING_CORR_FLOOR=0.30
RISK_MAX_POSITION_PCT=0.25
# Conservative annualized vol assumed when a symbol has no price history.
RISK_DEFAULT_STOCK_VOL=0.30
RISK_DEFAULT_CRYPTO_VOL=0.60
```

- [ ] **Step 2: Commit**

```bash
git add backend/.env.example
git commit -m "docs(env): document portfolio-risk env vars

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 3: Full suite**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest discover -s tests`
Expected: PASS (no regressions; ignore intentional "no gpt" tracebacks).

- [ ] **Step 4: Smoke-check imports**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -c "import services.portfolio_risk, services.trade_manager, api.api_server, core.utils; print('import ok')"`
Expected: prints `import ok`.

---

## Self-Review Notes (author)

- **Spec coverage:** Task 1 → config; Tasks 2-4 → composite score (vol/conc/corr/exposure + budget + contributions + flags); Task 5 → risk-based sizing + projection; Task 6 → sizing + entry gate (with equal-slot fallback); Task 7 → GPT context; Task 8 → API for monitoring/alert; Task 9 → env docs + verification. All four consumer uses (monitor, constraint, sizing, GPT) covered.
- **Weights:** concentration (0.30) + correlation (0.25) deliberately dominate, per the decision.
- **Type/name consistency:** `RiskAssessment` fields produced in Task 4 are consumed unchanged in Tasks 5-8; method names stable (`assess`, `suggest_size`, `project`, `_open_position_values`, `_risk_based_allocation`, `_risk_context`, `portfolio_risk_snapshot`). Position dict shape `{symbol, category, value}` consistent across service and TradeManager.
- **Fallbacks:** no broker/equity → equal-slot sizing + None GPT context + low_confidence snapshot; missing history → conservative default vol; never blocks trading on missing data except the explicit over-hard gate.
- **Known assumption:** trade dicts expose `quantity`/`current_price`/`allocated_capital`/`status`; `_open_position_values` falls back to `allocated_capital` if quantity×price is unavailable. If the field names differ at implementation time, adjust `_open_position_values` and report it.
- **Line numbers** are from the `dev-2.0` snapshot and may drift; locate by symbol if they don't match.
