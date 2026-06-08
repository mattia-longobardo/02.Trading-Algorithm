# Liquidity Gate Before ChatGPT Order Generation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skip the ChatGPT order-generation call for an asset class (STOCK or CRYPTO) when there is not enough cash to open even the smallest trade, mirroring the existing "slots exhausted" gate.

**Architecture:** Add one `TradeManager` helper, `_has_liquidity_for_new_trade(provider)`, that returns `False` when `available_cash < etoro_min_trade_amount`. Call it as a pre-LLM gate in both order-generation entry points (`_evaluate_provider_category` batch path and `maybe_open_trade` single-symbol path), right after the existing slot gate. The helper is permissive on errors and when no minimum is configured.

**Tech Stack:** Python 3, `unittest` + `unittest.mock`, pytest runner inside the `trading-backend` Docker image.

**Spec:** `docs/superpowers/specs/2026-06-09-liquidity-gate-gpt-design.md`

---

## Environment notes (read before running tests)

- There is **no local pytest** in this repo. Backend tests run in an ephemeral container against the worktree's `backend/` dir. The canonical command (used verbatim in every "run tests" step below) is:

  ```bash
  docker run --rm \
    -v "/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt/backend:/app" \
    -w /app trading-backend \
    sh -c "python -m pip install -q pytest 2>/dev/null; python -m pytest tests/test_trade_manager_liquidity_gate.py -q"
  ```

  (Replace the `-v` host path if the worktree path differs. `docker compose run` does NOT work here.)

- All work happens on branch `worktree-liquidity-gate-gpt` in the worktree at
  `/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt`.

## File Structure

- **Create:** `backend/tests/test_trade_manager_liquidity_gate.py` — all new tests (helper unit tests + both gate behaviours). Self-contained `_manager()` fixture in the style of `tests/test_trade_manager_risk.py`.
- **Modify:** `backend/services/trade_manager.py`
  - New method `_has_liquidity_for_new_trade` next to `_available_trade_slots` (~line 603).
  - Gate insertion in `_evaluate_provider_category` after the slot gate (~line 1247).
  - Gate insertion in `maybe_open_trade` after the slot gate (~line 721).

---

## Task 1: Liquidity helper `_has_liquidity_for_new_trade`

**Files:**
- Create: `backend/tests/test_trade_manager_liquidity_gate.py`
- Modify: `backend/services/trade_manager.py` (add method near `_available_trade_slots`, ~line 603)

- [ ] **Step 1: Write the failing tests (create the test file)**

Create `backend/tests/test_trade_manager_liquidity_gate.py` with this content:

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


def _manager(cash=10_000.0, min_trade=50.0):
    """TradeManager with a mocked broker + gpt client, no DB/network."""
    from services.trade_manager import TradeManager
    cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                    max_open_trades_stock=3, max_open_trades_crypto=3,
                    etoro_min_trade_amount=min_trade)
    broker = Mock()
    broker.get_available_cash.return_value = cash
    broker.get_account_equity.return_value = 10_000.0
    data_manager = Mock()
    gpt = Mock()
    tm = TradeManager(cfg, logging.getLogger("t"), {PROVIDER_ETORO: broker}, data_manager, gpt)
    tm.get_open_or_pending_trades = Mock(return_value=[])
    return tm, broker, gpt


class LiquidityHelperTests(unittest.TestCase):
    def test_true_when_cash_at_or_above_minimum(self):
        tm, _, _ = _manager(cash=50.0, min_trade=50.0)
        self.assertTrue(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))

    def test_false_when_cash_below_minimum(self):
        tm, _, _ = _manager(cash=49.99, min_trade=50.0)
        self.assertFalse(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))

    def test_permissive_when_cash_lookup_raises(self):
        tm, broker, _ = _manager(min_trade=50.0)
        broker.get_available_cash.side_effect = Exception("api down")
        self.assertTrue(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))

    def test_true_when_no_minimum_configured(self):
        tm, broker, _ = _manager(cash=0.0, min_trade=0.0)
        self.assertTrue(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))

    def test_false_when_no_broker(self):
        tm, _, _ = _manager()
        tm.broker = Mock(return_value=None)
        self.assertFalse(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
docker run --rm -v "/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt/backend:/app" -w /app trading-backend sh -c "python -m pip install -q pytest 2>/dev/null; python -m pytest tests/test_trade_manager_liquidity_gate.py -q"
```
Expected: FAIL — `AttributeError: ... object has no attribute '_has_liquidity_for_new_trade'` on the 4 tests that reach the call (the no-broker test may also fail for the same reason).

- [ ] **Step 3: Implement the helper**

In `backend/services/trade_manager.py`, locate `_available_trade_slots` (the method starting around line 603):

```python
    def _available_trade_slots(self, category: str, provider: str = PROVIDER_ETORO) -> int:
        if category == "STOCK":
            max_trades = int(self.config.max_open_trades_stock)
        else:
            max_trades = int(self.config.max_open_trades_crypto)
        return max(max_trades - self.count_active_trades(category, provider=provider), 0)
```

Immediately **after** that method, add:

```python
    def _has_liquidity_for_new_trade(self, provider: str = PROVIDER_ETORO) -> bool:
        """True when *provider* has enough cash to open at least the smallest trade.

        Pre-LLM gate so we never ask GPT for orders we could not fund. Permissive
        by design: returns True when no minimum is configured or when the cash
        lookup fails, so a transient broker blip never silently halts trading
        (downstream sizing still guards against over-allocation).
        """
        broker = self.broker(provider)
        if broker is None:
            return False
        minimum = float(getattr(self.config, "etoro_min_trade_amount", 0.0) or 0.0)
        if minimum <= 0:
            return True
        try:
            cash = float(broker.get_available_cash())
        except Exception:
            self.logger.warning(
                "Cash lookup failed for %s; allowing GPT cycle", provider, exc_info=True
            )
            return True
        return cash >= minimum
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
docker run --rm -v "/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt/backend:/app" -w /app trading-backend sh -c "python -m pip install -q pytest 2>/dev/null; python -m pytest tests/test_trade_manager_liquidity_gate.py -q"
```
Expected: PASS — 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt
git add backend/services/trade_manager.py backend/tests/test_trade_manager_liquidity_gate.py
git commit -m "feat(orders): add liquidity helper for pre-GPT gate

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Gate the batch path `_evaluate_provider_category`

**Files:**
- Modify: `backend/tests/test_trade_manager_liquidity_gate.py` (add a test class)
- Modify: `backend/services/trade_manager.py` (gate after slot gate, ~line 1247)

- [ ] **Step 1: Write the failing tests**

Append this class to `backend/tests/test_trade_manager_liquidity_gate.py` (before the `if __name__` block):

```python
class BatchGateTests(unittest.TestCase):
    def _ready_manager(self, cash):
        """Manager wired so only the liquidity gate can stop the GPT call:
        slots always free, payloads always non-empty, GPT returns no signals."""
        tm, broker, gpt = _manager(cash=cash, min_trade=50.0)
        tm._available_trade_slots = Mock(return_value=3)
        tm._build_batch_payloads = Mock(return_value=[{"symbol": "AAA"}])
        gpt.request_batch_trade_signals.return_value = {"signals": []}
        return tm, broker, gpt

    def test_skips_gpt_for_stock_when_cash_below_min(self):
        tm, _, gpt = self._ready_manager(cash=10.0)
        tm._evaluate_provider_category(PROVIDER_ETORO, "STOCK", ["AAA"])
        gpt.request_batch_trade_signals.assert_not_called()

    def test_skips_gpt_for_crypto_when_cash_below_min(self):
        tm, _, gpt = self._ready_manager(cash=10.0)
        tm._evaluate_provider_category(PROVIDER_ETORO, "CRYPTO", ["BTC"])
        gpt.request_batch_trade_signals.assert_not_called()

    def test_calls_gpt_when_cash_sufficient(self):
        tm, _, gpt = self._ready_manager(cash=10_000.0)
        tm._evaluate_provider_category(PROVIDER_ETORO, "STOCK", ["AAA"])
        gpt.request_batch_trade_signals.assert_called_once()

    def test_categories_evaluated_independently(self):
        # STOCK slots exhausted, CRYPTO funded with free slots: STOCK must skip,
        # CRYPTO must call GPT — verified through the per-category loop.
        tm, _, gpt = self._ready_manager(cash=10_000.0)
        tm._available_trade_slots = Mock(
            side_effect=lambda category, provider=PROVIDER_ETORO: 0 if category == "STOCK" else 3
        )
        tm.evaluate_cycle({PROVIDER_ETORO: {"STOCK": ["AAA"], "CRYPTO": ["BTC"]}})
        self.assertEqual(gpt.request_batch_trade_signals.call_count, 1)
        called_category = gpt.request_batch_trade_signals.call_args.kwargs["category"]
        self.assertEqual(called_category, "CRYPTO")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
docker run --rm -v "/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt/backend:/app" -w /app trading-backend sh -c "python -m pip install -q pytest 2>/dev/null; python -m pytest tests/test_trade_manager_liquidity_gate.py::BatchGateTests -q"
```
Expected: FAIL — `test_skips_gpt_for_stock_when_cash_below_min` and `test_skips_gpt_for_crypto_when_cash_below_min` fail because GPT is still called (gate not yet present). The other two should already pass.

- [ ] **Step 3: Implement the gate**

In `backend/services/trade_manager.py`, find the slot gate at the start of `_evaluate_provider_category` (~lines 1240-1247):

```python
            available_slots = self._available_trade_slots(category, provider=provider)
            if available_slots <= 0:
                self.logger.debug(
                    "Skipping %s/%s batch evaluation because no slots are available",
                    provider,
                    category,
                )
                return
```

Immediately **after** that `return` (and before `symbol_payloads = self._build_batch_payloads(...)`), add:

```python
            if not self._has_liquidity_for_new_trade(provider):
                self.logger.info(
                    "Skipping %s/%s batch evaluation because available cash is below "
                    "the minimum trade amount",
                    provider,
                    category,
                )
                return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
docker run --rm -v "/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt/backend:/app" -w /app trading-backend sh -c "python -m pip install -q pytest 2>/dev/null; python -m pytest tests/test_trade_manager_liquidity_gate.py -q"
```
Expected: PASS — 9 passed (5 from Task 1 + 4 here).

- [ ] **Step 5: Commit**

```bash
cd /home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt
git add backend/services/trade_manager.py backend/tests/test_trade_manager_liquidity_gate.py
git commit -m "feat(orders): gate batch GPT cycle on available liquidity per category

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Gate the single-symbol path `maybe_open_trade`

**Files:**
- Modify: `backend/tests/test_trade_manager_liquidity_gate.py` (add a test class)
- Modify: `backend/services/trade_manager.py` (gate after slot gate, ~line 721)

- [ ] **Step 1: Write the failing test**

Append this class to `backend/tests/test_trade_manager_liquidity_gate.py` (before the `if __name__` block):

```python
class SingleSymbolGateTests(unittest.TestCase):
    def _ready_manager(self, cash):
        tm, broker, gpt = _manager(cash=cash, min_trade=50.0)
        # Clear the earlier guards so only the liquidity gate can block GPT.
        tm.get_symbol_trades = Mock(return_value=[])
        broker.get_open_position.return_value = None
        tm._available_trade_slots = Mock(return_value=3)
        return tm, broker, gpt

    def test_skips_gpt_when_cash_below_min(self):
        tm, _, gpt = self._ready_manager(cash=10.0)
        tm.maybe_open_trade("STOCK", "AAA", provider=PROVIDER_ETORO)
        gpt.request_new_signal.assert_not_called()

    def test_calls_gpt_when_cash_sufficient(self):
        tm, _, gpt = self._ready_manager(cash=10_000.0)
        tm.data_manager.get_symbol_history.return_value = [{"timestamp": "0001", "close": 10.0}]
        gpt.request_new_signal.return_value = {"action": "HOLD"}
        tm.maybe_open_trade("STOCK", "AAA", provider=PROVIDER_ETORO)
        gpt.request_new_signal.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify the first fails**

Run:
```bash
docker run --rm -v "/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt/backend:/app" -w /app trading-backend sh -c "python -m pip install -q pytest 2>/dev/null; python -m pytest tests/test_trade_manager_liquidity_gate.py::SingleSymbolGateTests -q"
```
Expected: FAIL — `test_skips_gpt_when_cash_below_min` fails because `request_new_signal` is still called. `test_calls_gpt_when_cash_sufficient` should already pass.

- [ ] **Step 3: Implement the gate**

In `backend/services/trade_manager.py`, find the slot gate inside `maybe_open_trade` (~lines 714-721):

```python
        if self._available_trade_slots(category, provider=provider) <= 0:
            self.logger.debug(
                "Skipping %s because the max number of active %s/%s trades has been reached",
                symbol,
                provider,
                category,
            )
            return
```

Immediately **after** that `return` (and before `candles = self.data_manager.get_symbol_history(symbol)`), add:

```python
        if not self._has_liquidity_for_new_trade(provider):
            self.logger.info(
                "Skipping %s because available cash is below the minimum trade amount",
                symbol,
            )
            return
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
docker run --rm -v "/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt/backend:/app" -w /app trading-backend sh -c "python -m pip install -q pytest 2>/dev/null; python -m pytest tests/test_trade_manager_liquidity_gate.py -q"
```
Expected: PASS — 11 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt
git add backend/services/trade_manager.py backend/tests/test_trade_manager_liquidity_gate.py
git commit -m "feat(orders): gate single-symbol GPT call on available liquidity

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Full regression run

**Files:** none (verification only)

- [ ] **Step 1: Run the full backend test suite**

Run:
```bash
docker run --rm -v "/home/mattia/docker/projects/trading/.claude/worktrees/liquidity-gate-gpt/backend:/app" -w /app trading-backend sh -c "python -m pip install -q pytest 2>/dev/null; python -m pytest tests/ -q"
```
Expected: PASS — all existing tests plus the 11 new ones green (no regressions). Note the total count.

- [ ] **Step 2: Report**

State the final passed count and confirm no failures. The feature is complete; the branch is ready for review/merge via the `superpowers:finishing-a-development-branch` skill.

---

## Self-Review (done while writing this plan)

- **Spec coverage:** slot gate (already present — noted, not re-implemented); liquidity gate via `available_cash < etoro_min_trade_amount` (Task 1 helper); both entry points gated (Task 2 batch, Task 3 single-symbol); per-category independence (Task 2 `test_categories_evaluated_independently`); permissive-on-error and unconfigured-minimum (Task 1 tests 3 & 4). All spec test cases mapped.
- **Placeholder scan:** none — every code/test/command step is concrete.
- **Type/name consistency:** helper name `_has_liquidity_for_new_trade(provider)` identical across Tasks 1-3; GPT method names match the codebase (`request_batch_trade_signals`, `request_new_signal`); insertion points cross-checked against `trade_manager.py` line numbers.
