# Trade Performance Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the trading bot's realized expectancy by deterministically capturing the GPT's planned reward/risk on exits and bounding the dollar loss per trade, then gating entries by market regime.

**Architecture:** Four independent, config-driven changes to the Python backend. Each introduces a *pure* function (trivially unit-testable, no DB/broker) plus a thin wiring step into `services/trade_manager.py`. New behaviour is controlled by `AppConfig` fields with safe defaults and is overridable at runtime from the Settings UI, so every change is reversible without a code edit. No schema migrations.

**Tech Stack:** Python 3.14, `unittest` (stdlib), SQLite, FastAPI/APScheduler (untouched here). Tests live in `backend/tests/` and run with `python -m pytest` from `backend/`.

## Global Constraints

- Tests use **stdlib `unittest`** classes; run them with `python -m pytest <path> -v` from the `backend/` directory (the existing suite mixes both — pytest discovers `unittest.TestCase`).
- Every test file stubs `dotenv` before importing app modules (copy the 3-line stub from `tests/test_portfolio_risk.py:7-9`).
- Construct config in tests with `AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")` and set new fields explicitly per test.
- New tunables MUST be added in three places: the `AppConfig` dataclass field (`core/utils.py`), the `load_config()` env parse (`core/utils.py`), and — if operator-tunable — `SETTINGS_OVERRIDABLE_KEYS` (`core/utils.py:28`).
- The bot is LONG-only; all maths assume `entry > stop_loss` (a long). Reject/skip rather than crash when that invariant is violated.
- Do not change the GPT JSON schema or prompt caching prefix in this plan. We *post-process* GPT output deterministically instead of trusting it.
- This is a live (demo by default) trading bot: no change ships to a `real` account until Task 5 (backtest + demo validation) passes.

---

### Task 1: Deterministic R-based exit-level normalization

**Why:** Winners capture only 15–22% of their planned take-profit move; realized R ≈ +0.06 vs planned R/R ≈ 2.5. The trailing-take-profit arms too early and trails too tight. We stop trusting GPT's raw exit levels and clamp them to multiples of the initial risk `R = entry − stop`.

**Files:**
- Create: `backend/services/exit_levels.py`
- Create: `backend/tests/test_exit_levels.py`
- Modify: `backend/core/utils.py` (add config fields + env parse + overridable keys)
- Modify: `backend/services/trade_manager.py` — the `_save_new_trade(self, category, symbol, signal, instrument_id, allocated_capital, provider=...)` method (currently starts at line 533), which reads the exit fields off `signal` (lines 542–543, 566, 569) and writes the `INSERT INTO trades (...) VALUES (..., 'LONG', 'PENDING', ...)` (line 557)

**Interfaces:**
- Produces: `services/exit_levels.normalize_exit_levels(entry_price: float, stop_loss: float, take_profit: float | None, trailing_take_profit_distance: float | None, trailing_take_profit_activation_pct: float | None, *, min_reward_risk: float, arm_r: float, trail_r: float) -> dict` returning keys `take_profit`, `trailing_take_profit_distance`, `trailing_take_profit_activation_pct` (all floats; activation is a percent of entry).
- Consumes (Task 2 does not depend on this): nothing.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_exit_levels.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.exit_levels import normalize_exit_levels


class NormalizeExitLevelsTests(unittest.TestCase):
    def test_take_profit_raised_to_min_reward_risk(self):
        # entry 100, stop 90 -> R = 10. GPT proposed TP only 105 (0.5R).
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=90.0, take_profit=105.0,
            trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        # TP must be at least entry + 1.5R = 100 + 15 = 115
        self.assertAlmostEqual(out["take_profit"], 115.0, places=6)

    def test_take_profit_kept_when_already_generous(self):
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=90.0, take_profit=130.0,
            trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        self.assertAlmostEqual(out["take_profit"], 130.0, places=6)

    def test_trailing_arms_at_arm_r_and_trails_at_trail_r(self):
        # R = 10. arm at +1.5R = +15% -> activation_pct 15. trail distance = 1.0R = 10.
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=90.0, take_profit=130.0,
            trailing_take_profit_distance=2.0, trailing_take_profit_activation_pct=3.0,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        self.assertAlmostEqual(out["trailing_take_profit_activation_pct"], 15.0, places=6)
        self.assertAlmostEqual(out["trailing_take_profit_distance"], 10.0, places=6)

    def test_trailing_invariant_holds(self):
        # activation_pct must exceed distance/entry*100 (so trigger > entry at arming)
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=80.0, take_profit=200.0,
            trailing_take_profit_distance=5.0, trailing_take_profit_activation_pct=1.0,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        distance_pct = out["trailing_take_profit_distance"] / 100.0 * 100.0
        self.assertGreater(out["trailing_take_profit_activation_pct"], distance_pct)

    def test_no_trailing_when_input_none(self):
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=90.0, take_profit=130.0,
            trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        self.assertIsNone(out["trailing_take_profit_distance"])
        self.assertIsNone(out["trailing_take_profit_activation_pct"])

    def test_invalid_long_returns_inputs_unchanged(self):
        # entry <= stop is not a valid long; do not fabricate levels.
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=100.0, take_profit=130.0,
            trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        self.assertEqual(out["take_profit"], 130.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_exit_levels.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.exit_levels'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/exit_levels.py
"""Deterministic, R-multiple-based normalization of exit levels.

R = entry_price - stop_loss is the per-trade risk unit (a long). GPT proposes
take_profit and trailing-take-profit parameters but historically clipped winners
to ~0.4R; this module clamps those levels to risk multiples so winners are
allowed to run to a configured reward/risk. Pure: no DB, no broker, no I/O.
"""

from __future__ import annotations


def normalize_exit_levels(
    entry_price: float,
    stop_loss: float,
    take_profit: float | None,
    trailing_take_profit_distance: float | None,
    trailing_take_profit_activation_pct: float | None,
    *,
    min_reward_risk: float,
    arm_r: float,
    trail_r: float,
) -> dict:
    """Clamp exit levels to multiples of the initial risk R = entry - stop.

    - take_profit is raised (never lowered) to at least entry + min_reward_risk * R.
    - When a trailing take profit is requested (both inputs set), its activation is
      set to arm_r * R (as a percent of entry) and its distance to trail_r * R, then
      the activation is nudged up so it always exceeds distance/entry*100 (the
      bot's arming invariant: trigger sits above entry the moment it arms).
    - When entry <= stop (not a valid long) inputs are returned unchanged.
    """

    out = {
        "take_profit": take_profit,
        "trailing_take_profit_distance": trailing_take_profit_distance,
        "trailing_take_profit_activation_pct": trailing_take_profit_activation_pct,
    }
    risk = entry_price - stop_loss
    if entry_price <= 0 or risk <= 0:
        return out

    floor_tp = entry_price + min_reward_risk * risk
    if take_profit is None or take_profit < floor_tp:
        out["take_profit"] = round(floor_tp, 8)

    if trailing_take_profit_distance is not None and trailing_take_profit_activation_pct is not None:
        distance = round(trail_r * risk, 8)
        distance_pct = distance / entry_price * 100.0
        activation_pct = arm_r * risk / entry_price * 100.0
        # keep the bot's invariant: activation must clear distance_pct with margin
        activation_pct = max(activation_pct, distance_pct + 0.5)
        out["trailing_take_profit_distance"] = distance
        out["trailing_take_profit_activation_pct"] = round(activation_pct, 8)

    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_exit_levels.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Add config fields**

In `backend/core/utils.py`, inside the `AppConfig` dataclass (after `trailing_tp_min_profit_buffer_pct`, ~line 126), add:

```python
    # Deterministic R-multiple exit shaping (R = entry - stop). See
    # services/exit_levels.normalize_exit_levels.
    exit_min_reward_risk: float = 1.5
    exit_trailing_arm_r: float = 1.5
    exit_trailing_trail_r: float = 1.0
```

In `load_config()` (after the `trailing_tp_min_profit_buffer_pct=...` line, ~line 255), add:

```python
        exit_min_reward_risk=max(0.0, float(os.getenv("EXIT_MIN_REWARD_RISK", "1.5"))),
        exit_trailing_arm_r=max(0.0, float(os.getenv("EXIT_TRAILING_ARM_R", "1.5"))),
        exit_trailing_trail_r=max(0.01, float(os.getenv("EXIT_TRAILING_TRAIL_R", "1.0"))),
```

In `SETTINGS_OVERRIDABLE_KEYS` (the frozenset at ~line 28), add the three keys:

```python
        "exit_min_reward_risk",
        "exit_trailing_arm_r",
        "exit_trailing_trail_r",
```

- [ ] **Step 6: Wire the normalizer into `_save_new_trade`**

In `backend/services/trade_manager.py`, add the import near the other `from services.` imports at the top:

```python
from services.exit_levels import normalize_exit_levels
```

In `_save_new_trade` (line 533), replace the two raw reads at lines 542–543 with a normalized block computed from `signal`:

```python
        _levels = normalize_exit_levels(
            entry_price=float(signal["entry_price"]),
            stop_loss=float(signal["stop_loss"]),
            take_profit=self._as_float(signal.get("take_profit")),
            trailing_take_profit_distance=self._as_float(signal.get("trailing_take_profit_distance")),
            trailing_take_profit_activation_pct=self._as_float(signal.get("trailing_take_profit_activation_pct")),
            min_reward_risk=self.config.exit_min_reward_risk,
            arm_r=self.config.exit_trailing_arm_r,
            trail_r=self.config.exit_trailing_trail_r,
        )
        trailing_take_profit_distance = _levels["trailing_take_profit_distance"]
        trailing_take_profit_activation_pct = _levels["trailing_take_profit_activation_pct"]
        take_profit = _levels["take_profit"]
```

Then change the INSERT values tuple so `take_profit` comes from the normalized local instead of the raw signal: replace `float(signal["take_profit"])` at line 566 with `float(take_profit)`. The `trailing_take_profit_distance` / `trailing_take_profit_activation_pct` locals at lines 567–568 already feed the tuple, so they now carry the normalized values automatically.

- [ ] **Step 7: Run the full trade-manager test suite to verify no regression**

Run: `cd backend && python -m pytest tests/test_trade_manager_orders.py tests/test_trade_manager_risk.py tests/test_trade_manager_etoro.py -v`
Expected: PASS (no regressions; pre-existing trailing-validation tests still green)

- [ ] **Step 8: Commit**

```bash
git add backend/services/exit_levels.py backend/tests/test_exit_levels.py backend/core/utils.py backend/services/trade_manager.py
git commit -m "feat(trading): clamp exit levels to R-multiples to capture planned edge"
```

---

### Task 2: Risk-based dollar sizing cap

**Why:** Sizing is portfolio-vol-parity, so the dollar loss on a −1R stop ranged from −16 to −2,867 USD. We cap each position so the loss to its stop never exceeds a fixed fraction of equity, making every −1R a constant, small bite and removing the sizing variance that turned a breakeven-R book into −3,253 USD.

**Files:**
- Modify: `backend/services/portfolio_risk.py` (extend `suggest_size`, ~line 309)
- Modify: `backend/tests/test_portfolio_risk.py` (add cases)
- Modify: `backend/core/utils.py` (config field + env parse + overridable key)
- Modify: `backend/services/trade_manager.py` — thread `entry_price`/`stop_loss` through `_risk_based_allocation` (line 339) into its `self.risk.suggest_size(...)` call (line 364), and pass them from the open path (line 751). The *what-if projection* site at line 457 is intentionally left unchanged (it has no live signal/stop).

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `PortfolioRiskService.suggest_size(candidate, positions, equity, available_cash, stop_loss: float | None = None)` — new optional last parameter; when set and a valid long, the returned value is additionally capped so `(entry−stop)/entry × value ≤ risk_per_trade_pct × equity`. `candidate` must carry `entry_price` when `stop_loss` is passed.
  - `TradeManager._risk_based_allocation(category, symbol, provider=..., entry_price: float | None = None, stop_loss: float | None = None)` — new optional kwargs forwarded to `suggest_size`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_portfolio_risk.py`:

```python
class RiskBasedSizingCapTests(unittest.TestCase):
    def _svc(self, risk_pct):
        cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        cfg.risk_per_trade_pct = risk_pct
        cfg.risk_max_position_pct = 1.0  # isolate the new cap
        return PortfolioRiskService(cfg, logging.getLogger("t"),
                                    history_provider=lambda s, l: [])

    def test_stop_cap_limits_dollar_risk(self):
        svc = self._svc(0.01)  # risk 1% of equity per trade
        # entry 100, stop 90 -> 10% stop. equity 100000 -> max risk $1000.
        # max value = 1000 / 0.10 = 10000.
        cand = {"symbol": "AAA", "category": "STOCK", "entry_price": 100.0}
        value = svc.suggest_size(cand, [], equity=100000.0,
                                 available_cash=100000.0, stop_loss=90.0)
        self.assertLessEqual(value, 10000.0 + 1e-6)

    def test_no_stop_means_no_extra_cap(self):
        svc = self._svc(0.01)
        cand = {"symbol": "AAA", "category": "STOCK", "entry_price": 100.0}
        with_cap = svc.suggest_size(cand, [], 100000.0, 100000.0, stop_loss=90.0)
        without = svc.suggest_size(cand, [], 100000.0, 100000.0, stop_loss=None)
        self.assertLessEqual(with_cap, without + 1e-6)

    def test_invalid_long_ignores_cap(self):
        svc = self._svc(0.01)
        cand = {"symbol": "AAA", "category": "STOCK", "entry_price": 100.0}
        # stop above entry -> not a valid long, cap is skipped (no div-by-zero/negative)
        value = svc.suggest_size(cand, [], 100000.0, 100000.0, stop_loss=110.0)
        self.assertGreaterEqual(value, 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_portfolio_risk.py::RiskBasedSizingCapTests -v`
Expected: FAIL — `AttributeError: 'AppConfig' object has no attribute 'risk_per_trade_pct'` (and `suggest_size()` rejecting the `stop_loss` kwarg)

- [ ] **Step 3: Add config field**

In `backend/core/utils.py` `AppConfig` (after `risk_max_position_pct`, ~line 111):

```python
    risk_per_trade_pct: float = 0.01
```

In `load_config()` (after the `risk_max_position_pct=...` line, ~line 246):

```python
        risk_per_trade_pct=min(0.10, max(0.001, float(os.getenv("RISK_PER_TRADE_PCT", "0.01")))),
```

In `SETTINGS_OVERRIDABLE_KEYS`, add `"risk_per_trade_pct"`.

- [ ] **Step 4: Implement the cap in `suggest_size`**

In `backend/services/portfolio_risk.py`, change the signature (line 309) and add the cap just before the `minimum` check (line 331):

```python
    def suggest_size(
        self,
        candidate: dict[str, Any],
        positions: list[dict[str, Any]],
        equity: float,
        available_cash: float,
        stop_loss: float | None = None,
    ) -> float:
        if equity <= 0 or available_cash <= 0:
            return 0.0
        symbol = str(candidate["symbol"]).upper()
        category = str(candidate.get("category") or "STOCK")
        invested = sum(self._coerce_value(p.get("value")) for p in positions
                       if self._coerce_value(p.get("value")) > 0)
        sigma_c = self._candidate_vol(symbol, category)
        corr_c = max(self._candidate_correlation(symbol, positions, invested), self.config.risk_sizing_corr_floor)
        target = max(self.config.max_open_trades_stock + self.config.max_open_trades_crypto, 1)
        target_risk_per_slot = self._budget_vol() / target
        denom = sigma_c * corr_c
        if denom <= 0:
            return 0.0
        value = (target_risk_per_slot / denom) * equity
        value = min(value, available_cash, self.config.risk_max_position_pct * equity)
        # Fixed-fractional dollar-risk cap: bound the loss to the stop at
        # risk_per_trade_pct of equity. entry/stop come from the candidate signal.
        entry = self._coerce_value(candidate.get("entry_price"))
        if stop_loss is not None and entry > 0 and stop_loss < entry:
            stop_fraction = (entry - stop_loss) / entry
            if stop_fraction > 0:
                max_risk_value = (self.config.risk_per_trade_pct * equity) / stop_fraction
                value = min(value, max_risk_value)
        minimum = float(getattr(self.config, "etoro_min_trade_amount", 0.0) or 0.0)
        if value < minimum:
            return minimum if available_cash >= minimum else 0.0
        return round(value, 2)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_portfolio_risk.py -v`
Expected: PASS (existing + 3 new tests)

- [ ] **Step 6: Thread `entry_price`/`stop_loss` through the live sizing path**

In `backend/services/trade_manager.py`:

(a) Change the `_risk_based_allocation` signature (line 339) to accept the new kwargs:

```python
    def _risk_based_allocation(
        self,
        category: str,
        symbol: str,
        provider: str = PROVIDER_ETORO,
        entry_price: float | None = None,
        stop_loss: float | None = None,
    ) -> float:
```

(b) Inside it, enrich the `candidate` dict (line 363) and forward `stop_loss` to `suggest_size` (line 364):

```python
        candidate = {"symbol": str(symbol).upper(), "category": category, "entry_price": entry_price}
        size = self.risk.suggest_size(candidate, positions, equity, cash, stop_loss=stop_loss)
```

(c) At the open path call site (line 751), pass the signal's levels:

```python
        allocated_capital = self._risk_based_allocation(
            category, symbol, provider=provider,
            entry_price=float(signal["entry_price"]),
            stop_loss=self._as_float(signal.get("stop_loss")),
        )
```

Leave the projection site at line 457 unchanged — it sizes a hypothetical with no stop and must keep its current behaviour.

- [ ] **Step 7: Run sizing-related trade-manager tests**

Run: `cd backend && python -m pytest tests/test_trade_manager_risk.py tests/test_trade_manager_liquidity_gate.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/services/portfolio_risk.py backend/tests/test_portfolio_risk.py backend/core/utils.py backend/services/trade_manager.py
git commit -m "feat(trading): cap position size by fixed-fractional dollar risk to stop"
```

---

### Task 3: Market-regime entry gate

**Why:** Long-only, crypto-heavy, with no hard trend filter produced "stop-out clustering" (30 broker-side stop closes, −14,655 USD) from entries fired into downtrends. Block opening a long when price is below its long-term moving average.

**Files:**
- Create: `backend/services/regime.py`
- Create: `backend/tests/test_regime.py`
- Modify: `backend/core/utils.py` (config: enable flag + SMA period + env parse + overridable keys)
- Modify: `backend/services/trade_manager.py` (skip a symbol whose history fails the gate — in the open path, right after the `_signal_has_required_levels(signal)` guard at line 748 and before the `_risk_based_allocation` call at line 751)

**Interfaces:**
- Consumes: nothing from Tasks 1–2.
- Produces: `services/regime.passes_regime_gate(bars: list[dict], sma_period: int, current_price: float | None = None) -> bool` — True when `current_price` (or the last close) is at/above the simple moving average of the last `sma_period` closes; True (fail-open) when there is insufficient history, so the gate never blocks for lack of data.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_regime.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.regime import passes_regime_gate


def _bars(closes):
    return [{"timestamp": f"{i:04d}", "close": c} for i, c in enumerate(closes)]


class RegimeGateTests(unittest.TestCase):
    def test_price_above_sma_passes(self):
        bars = _bars([10.0] * 50)
        self.assertTrue(passes_regime_gate(bars, sma_period=50, current_price=11.0))

    def test_price_below_sma_blocks(self):
        bars = _bars([10.0] * 50)
        self.assertFalse(passes_regime_gate(bars, sma_period=50, current_price=9.0))

    def test_uses_last_close_when_no_current_price(self):
        bars = _bars([10.0] * 49 + [8.0])
        # mean of 49*10 + 8 = 9.96; last close 8 < sma -> blocks
        self.assertFalse(passes_regime_gate(bars, sma_period=50))

    def test_insufficient_history_fails_open(self):
        bars = _bars([10.0] * 5)
        self.assertTrue(passes_regime_gate(bars, sma_period=200, current_price=1.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_regime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.regime'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/regime.py
"""Market-regime entry gate: only open longs in an up-regime (price >= SMA).

Pure and fail-open: when history is too short to form the SMA the gate returns
True so a thin-data symbol is never silently blocked. The caller supplies bars
(ascending or not) as {"close": ...} dicts and optionally the live price.
"""

from __future__ import annotations


def _closes(bars: list[dict]) -> list[float]:
    out: list[float] = []
    for bar in bars:
        raw = bar.get("close")
        try:
            close = float(raw)
        except (TypeError, ValueError):
            continue
        if close > 0:
            out.append(close)
    return out


def passes_regime_gate(
    bars: list[dict], sma_period: int, current_price: float | None = None
) -> bool:
    closes = _closes(bars)
    if sma_period <= 0 or len(closes) < sma_period:
        return True  # fail-open: insufficient history
    window = closes[-sma_period:]
    sma = sum(window) / len(window)
    price = current_price if (current_price is not None and current_price > 0) else closes[-1]
    return price >= sma
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_regime.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Add config fields**

In `backend/core/utils.py` `AppConfig` (near the other `risk_*` fields, ~line 113):

```python
    regime_gate_enabled: bool = True
    regime_sma_period: int = 200
```

In `load_config()`:

```python
        regime_gate_enabled=os.getenv("REGIME_GATE_ENABLED", "true").strip().lower()
        in {"1", "true", "yes", "on"},
        regime_sma_period=max(20, int(os.getenv("REGIME_SMA_PERIOD", "200"))),
```

In `SETTINGS_OVERRIDABLE_KEYS`, add `"regime_gate_enabled"` and `"regime_sma_period"`.

- [ ] **Step 6: Wire the gate into candidate evaluation**

In `backend/services/trade_manager.py`, import at top:

```python
from services.regime import passes_regime_gate
```

In the open path, insert the gate immediately after the `_signal_has_required_levels(signal)` guard (line 748–749) and before the `_risk_based_allocation` call (line 751). `symbol`, `category`, and `signal` are all in scope, and the method returns `False` to skip a symbol. Use the existing history accessor `self.data_manager.get_symbol_history(symbol, limit=...)` (same one used at lines 704/998):

```python
        if self.config.regime_gate_enabled:
            bars = self.data_manager.get_symbol_history(
                symbol, limit=self.config.regime_sma_period
            ) or []
            if not passes_regime_gate(
                bars,
                self.config.regime_sma_period,
                current_price=self._as_float(signal.get("entry_price")),
            ):
                self.logger.info(
                    "Regime gate blocked %s (price below SMA%s)",
                    symbol, self.config.regime_sma_period,
                )
                return False
```

- [ ] **Step 7: Run the trade-manager suite**

Run: `cd backend && python -m pytest tests/test_trade_manager_orders.py tests/test_trade_manager_risk.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/services/regime.py backend/tests/test_regime.py backend/core/utils.py backend/services/trade_manager.py
git commit -m "feat(trading): gate long entries by market regime (price >= SMA200)"
```

---

### Task 4: Per-trade R analytics logging

**Why:** We could not previously see that winners captured only ~20% of planned TP without ad-hoc SQL. Emit the planned risk (R) and reward/risk at open, and the realized R at close, as structured log lines so future regressions in exit capture are visible in `logs/trading_bot.log` without re-deriving it.

**Files:**
- Create: `backend/services/trade_analytics.py`
- Create: `backend/tests/test_trade_analytics.py`
- Modify: `backend/services/trade_manager.py` (log at open and at close — search anchors: the post-`INSERT INTO trades` success path, and the close path where `close_reason`/`pnl` are finalized)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `services/trade_analytics.planned_metrics(entry_price: float, stop_loss: float, take_profit: float | None) -> dict` → `{"risk_per_unit": float, "reward_risk": float | None}`
  - `services/trade_analytics.realized_r(entry_price: float, stop_loss: float, close_price: float) -> float | None` → `(close − entry) / (entry − stop)`, or `None` when not a valid long.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_trade_analytics.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.trade_analytics import planned_metrics, realized_r


class TradeAnalyticsTests(unittest.TestCase):
    def test_planned_metrics(self):
        m = planned_metrics(entry_price=100.0, stop_loss=90.0, take_profit=130.0)
        self.assertAlmostEqual(m["risk_per_unit"], 10.0, places=6)
        self.assertAlmostEqual(m["reward_risk"], 3.0, places=6)

    def test_planned_metrics_no_tp(self):
        m = planned_metrics(entry_price=100.0, stop_loss=90.0, take_profit=None)
        self.assertIsNone(m["reward_risk"])

    def test_planned_metrics_invalid_long(self):
        m = planned_metrics(entry_price=100.0, stop_loss=100.0, take_profit=130.0)
        self.assertIsNone(m["reward_risk"])
        self.assertEqual(m["risk_per_unit"], 0.0)

    def test_realized_r(self):
        self.assertAlmostEqual(realized_r(100.0, 90.0, 115.0), 1.5, places=6)
        self.assertAlmostEqual(realized_r(100.0, 90.0, 90.0), -1.0, places=6)
        self.assertIsNone(realized_r(100.0, 100.0, 120.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_trade_analytics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.trade_analytics'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/trade_analytics.py
"""Pure R-multiple analytics for trade open/close logging. No DB, no I/O."""

from __future__ import annotations


def planned_metrics(entry_price: float, stop_loss: float, take_profit: float | None) -> dict:
    risk = entry_price - stop_loss
    if entry_price <= 0 or risk <= 0:
        return {"risk_per_unit": 0.0, "reward_risk": None}
    reward_risk = None
    if take_profit is not None and take_profit > entry_price:
        reward_risk = (take_profit - entry_price) / risk
    return {"risk_per_unit": round(risk, 8), "reward_risk": reward_risk}


def realized_r(entry_price: float, stop_loss: float, close_price: float) -> float | None:
    risk = entry_price - stop_loss
    if entry_price <= 0 or risk <= 0:
        return None
    return (close_price - entry_price) / risk
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_trade_analytics.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Log planned metrics at open**

In `backend/services/trade_manager.py`, add the import:

```python
from services.trade_analytics import planned_metrics, realized_r
```

On the successful-open path (after the position is confirmed / the trade row is inserted), add:

```python
        _pm = planned_metrics(
            float(trade["entry_price"]), float(trade["stop_loss"]),
            self._as_float(trade.get("take_profit")),
        )
        self.logger.info(
            "OPEN %s qty=%s alloc=%.2f R=%.4f planned_RR=%s",
            trade["symbol"], trade["quantity"], float(trade["allocated_capital"]),
            _pm["risk_per_unit"], _pm["reward_risk"],
        )
```

- [ ] **Step 6: Log realized R at close**

On the close path (where `close_reason` and `pnl` are finalized), add:

```python
        _r = realized_r(
            float(trade["entry_price"]), float(trade["stop_loss"]),
            float(close_price),
        )
        self.logger.info(
            "CLOSE %s reason=%s pnl=%.2f realized_R=%s",
            trade["symbol"], reason, float(pnl) if pnl is not None else 0.0, _r,
        )
```

(Match the local variable names at each site — `trade`, `reason`, `close_price`, `pnl`. Guard with the same null-safety helpers already used nearby.)

- [ ] **Step 7: Run the trade-manager suite**

Run: `cd backend && python -m pytest tests/test_trade_manager_orders.py tests/test_close_resolution.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/services/trade_analytics.py backend/tests/test_trade_analytics.py backend/services/trade_manager.py
git commit -m "feat(trading): log planned and realized R per trade"
```

---

### Task 5: Backtest + demo validation gate

**Why:** Sizing and exit changes are high-impact on a money-handling bot. Before any rollout to a `real` account, validate the new behaviour end-to-end and confirm no test regressed.

**Files:**
- Modify: none (validation only). Uses `backend/backtest/` and the demo eToro account.

**Interfaces:**
- Consumes: Tasks 1–4 merged.

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS (all existing tests + the new `test_exit_levels.py`, `test_regime.py`, `test_trade_analytics.py`, and the added `test_portfolio_risk.py` cases). Record the pass count.

- [ ] **Step 2: Backtest old vs new exit/sizing**

Inspect `backend/backtest/` for the entrypoint (search for `if __name__` / a `run`/`main`). Run it once with the new config defaults and once with the change neutralized (`EXIT_MIN_REWARD_RISK=0 EXIT_TRAILING_TRAIL_R=999 RISK_PER_TRADE_PCT=0.10 REGIME_GATE_ENABLED=false`) to A/B realized expectancy. Record both equity curves / net PnL in the PR description. If the backtest harness lacks the hooks, note that explicitly as a gap rather than skipping silently.

- [ ] **Step 3: Dry-run on the demo account**

Confirm `ETORO_ACCOUNT_TYPE=demo`, start the stack (`docker compose up -d --build` from the repo root), and let one scheduler cycle run. In `logs/trading_bot.log` confirm: `OPEN ... planned_RR=` lines show RR ≥ `exit_min_reward_risk`, at least one `Regime gate blocked` line appears in a downtrend, and sized positions respect the dollar-risk cap (allocated × stop% ≤ ~1% equity).

- [ ] **Step 4: Verify the tracking anomaly from the analysis**

Before trusting live PnL, reconcile the §1 anomaly (equity +9% vs ledger −4.9k). Query `account_equity_snapshots` deltas vs summed trade `pnl` for the same window; if they still diverge, file a separate bug — do not gate this plan on it, but record the finding.

- [ ] **Step 5: Commit the validation notes**

```bash
git add docs/analysis/2026-06-25-trade-performance.md
git commit -m "docs(trading): record backtest + demo validation results"
```

---

## Out of scope (follow-ups, separate plans)

- **De-weight / recalibrate `confidence`** in `_rank_signals` (§2.3 of the analysis): confidence is uncorrelated-to-inverted with outcome. Either drop it from the sort key or calibrate it (Brier score on history) before reusing. Small, but needs a calibration dataset.
- **Reduce CANCELLED rate** (§2.5): tune `crypto_pending_cancel_minutes` / use marketable-limit entries.
- **Persist R metrics** to the `trades` table + surface "captured R" on the dashboard (schema migration; the logging in Task 4 is the cheap first step).
- **Shorting / hedging or cash-raise** in a down-regime (currently long-only).

## Self-Review

- **Spec coverage:** Analysis leverage 1 (capture edge) → Task 1; leverage 2 (dollar-risk) → Task 2; leverage 3 (regime) → Task 3; leverage 5 (observability) → Task 4; leverages 4 (confidence) and 6 (execution) → explicitly deferred in Out of scope; validation → Task 5. ✓
- **Placeholder scan:** every code step contains runnable code; wiring steps that touch unverified line numbers use search anchors and name the exact symbol to find, not "add error handling". ✓
- **Type consistency:** `normalize_exit_levels` returns the three exit keys used verbatim in Task 1 Step 6; `suggest_size` gains `stop_loss=` used verbatim in Task 2 Step 6; `passes_regime_gate(bars, sma_period, current_price=)` matches Task 3 Step 6; `planned_metrics`/`realized_r` signatures match Task 4 Steps 5–6. ✓
</content>
