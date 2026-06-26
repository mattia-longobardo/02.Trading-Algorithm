# Order Execution — Reduce CANCELLED Rate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the ~35% order-cancellation rate by widening the crypto fill band + timeout, making stock order resolution less trigger-happy, and removing two dead config knobs — all behind config defaults.

**Architecture:** A pure helper `is_marketable()` replaces the inline crypto fill-condition; config defaults for chase/timeout are widened; two unused knobs are deleted. No change to how orders are placed.

**Tech Stack:** Python 3.14, stdlib `unittest`. Full suite in the `trading-backend` container; pure-module tests locally via `python3 -m unittest`.

## Global Constraints

- Verified code facts (base `cf0d456`): the crypto fill condition is `ask > self._entry_fill_ceiling(target)` → wait, where `_entry_fill_ceiling(target) = target * (1 + crypto_entry_max_chase_bps/10_000)` (`trade_manager.py:863-864, 908-909`). `crypto_pending_cancel_minutes` gates `ENTRY_TIMEOUT` at line 893. `order_await_timeout_minutes` gates `ORDER_AWAIT_TIMEOUT` in `_resolve_submitted_order` (lines 944-978).
- `crypto_entry_limit_collar_bps` and `crypto_pending_reprice_minutes` are defined-but-unused (grep confirms no use outside `core/utils.py`). They are removed in this plan.
- New/changed tunables touch all three places in `core/utils.py`: `AppConfig` field, `load_config()` parse, `SETTINGS_OVERRIDABLE_KEYS`.
- The bot is LONG-only; no change to `open_market_position`.

---

### Task 1: Extract a pure `is_marketable` helper and use it in the crypto fill path

**Files:**
- Create: `backend/services/order_exec.py`
- Create: `backend/tests/test_order_exec.py`
- Modify: `backend/services/trade_manager.py` — `sync_pending_trade` line 908 (replace the inline ceiling comparison), and add an import.

**Interfaces:**
- Produces: `services/order_exec.is_marketable(ask: float, target: float, max_chase_bps: float) -> bool` — True when `ask <= target * (1 + max_chase_bps/10_000)` (i.e. close enough to fill at market). False on non-positive target/ask.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_order_exec.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.order_exec import is_marketable


class IsMarketableTests(unittest.TestCase):
    def test_fills_within_band(self):
        # target 100, 40 bps band -> ceiling 100.40; ask 100.3 fills
        self.assertTrue(is_marketable(100.3, 100.0, 40))

    def test_at_target_fills(self):
        self.assertTrue(is_marketable(100.0, 100.0, 40))

    def test_above_band_waits(self):
        # ask 100.5 > ceiling 100.40 -> not marketable
        self.assertFalse(is_marketable(100.5, 100.0, 40))

    def test_wider_band_fills_more(self):
        self.assertFalse(is_marketable(100.5, 100.0, 40))
        self.assertTrue(is_marketable(100.5, 100.0, 80))  # ceiling 100.80

    def test_invalid_inputs_not_marketable(self):
        self.assertFalse(is_marketable(0.0, 100.0, 40))
        self.assertFalse(is_marketable(100.0, 0.0, 40))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run (locally): `cd backend && python3 -m unittest tests.test_order_exec -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'services.order_exec'`

- [ ] **Step 3: Implement the helper**

```python
# backend/services/order_exec.py
"""Pure order-execution helpers (no broker, no DB)."""

from __future__ import annotations


def is_marketable(ask: float, target: float, max_chase_bps: float) -> bool:
    """True when the current ask is close enough to the target to fill at market.

    Mirrors the live fill rule: fill when ``ask <= target * (1 + max_chase_bps/10_000)``.
    A wider ``max_chase_bps`` accepts more slippage above target and fills more
    orders (fewer ENTRY_TIMEOUT cancellations). Non-positive ask/target never fill.
    """
    if ask <= 0 or target <= 0:
        return False
    ceiling = target * (1.0 + max_chase_bps / 10_000.0)
    return ask <= ceiling
```

- [ ] **Step 4: Run to verify it passes**

Run (locally): `cd backend && python3 -m unittest tests.test_order_exec -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Use the helper in `sync_pending_trade`**

In `backend/services/trade_manager.py`, add the import near the other `from services.` imports:

```python
from services.order_exec import is_marketable
```

Replace the inline comparison at line 908:

```python
        if ask > self._entry_fill_ceiling(target):
            return  # wait for price to come down to the limit
```

with:

```python
        if not is_marketable(ask, target, float(self.config.crypto_entry_max_chase_bps)):
            return  # ask above the fill band; wait for price to come down
```

(`_entry_fill_ceiling` may remain for any other caller; if grep shows it is now unused, leave it — removing it is out of scope.)

- [ ] **Step 6: Run the order tests in the container**

Run (container): `python -m pytest tests/test_trade_manager_orders.py tests/test_trade_manager_liquidity_gate.py -v`
Expected: PASS (behaviour identical at the default 40 bps — the helper preserves the exact inequality)

- [ ] **Step 7: Commit**

```bash
git add backend/services/order_exec.py backend/tests/test_order_exec.py backend/services/trade_manager.py
git commit -m "refactor(trading): extract pure is_marketable helper for crypto fill band"
```

---

### Task 2: Widen crypto fill band + timeout defaults; raise stock await timeout

**Files:**
- Modify: `backend/core/utils.py` — `AppConfig` defaults + `load_config()` env defaults for `crypto_entry_max_chase_bps`, `crypto_pending_cancel_minutes`, `order_await_timeout_minutes`.
- Test: `backend/tests/test_etoro_config.py` (config defaults are asserted there; confirm by reading it first).

**Interfaces:**
- Consumes: `is_marketable` (Task 1) reads `crypto_entry_max_chase_bps`.
- Produces: new default values (chase 80, cancel 20 min, await 720 min).

- [ ] **Step 1: Write/adjust the failing test**

Read `backend/tests/test_etoro_config.py` to see how defaults are asserted. Add (or adjust) assertions:

```python
    def test_widened_execution_defaults(self):
        cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        self.assertEqual(cfg.crypto_entry_max_chase_bps, 80)
        self.assertEqual(cfg.crypto_pending_cancel_minutes, 20)
        self.assertEqual(cfg.order_await_timeout_minutes, 720)
```

- [ ] **Step 2: Run to verify it fails**

Run (locally): `cd backend && python3 -m unittest tests.test_etoro_config -v`
Expected: FAIL — current defaults are 40 / 12 / 360.

- [ ] **Step 3: Update the defaults**

In `backend/core/utils.py`, change the `AppConfig` dataclass defaults:
- `crypto_entry_max_chase_bps: int = 40` → `= 80`
- `crypto_pending_cancel_minutes: int = 12` → `= 20`
- `order_await_timeout_minutes: int = 360` → `= 720`

And in `load_config()` change the matching `os.getenv(..., "<default>")` fallbacks to `"80"`, `"20"`, `"720"` respectively (keep the same `max(...)`/`int(...)` wrappers).

- [ ] **Step 4: Run to verify it passes**

Run (locally): `cd backend && python3 -m unittest tests.test_etoro_config -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/utils.py backend/tests/test_etoro_config.py
git commit -m "feat(trading): widen crypto fill band/timeout and stock await defaults to cut cancellations"
```

---

### Task 3: Remove the two dead config knobs

**Files:**
- Modify: `backend/core/utils.py` — remove `crypto_entry_limit_collar_bps` and `crypto_pending_reprice_minutes` from `AppConfig`, `load_config()`, and `SETTINGS_OVERRIDABLE_KEYS`.
- Test: `backend/tests/test_etoro_config.py`.

**Interfaces:**
- Consumes: nothing.
- Produces: the two attributes no longer exist on `AppConfig`.

- [ ] **Step 1: Confirm they are unused**

Run (locally): `cd backend && grep -rn "crypto_entry_limit_collar_bps\|crypto_pending_reprice_minutes" --include=*.py . | grep -v core/utils.py`
Expected: NO output (only `core/utils.py` references them). If anything else references them, STOP and report — removal is unsafe.

- [ ] **Step 2: Write the failing test**

```python
    def test_dead_knobs_removed(self):
        cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        self.assertFalse(hasattr(cfg, "crypto_entry_limit_collar_bps"))
        self.assertFalse(hasattr(cfg, "crypto_pending_reprice_minutes"))
```

- [ ] **Step 3: Run to verify it fails**

Run (locally): `cd backend && python3 -m unittest tests.test_etoro_config -k dead_knobs -v`
Expected: FAIL — attributes still exist.

- [ ] **Step 4: Remove the knobs**

In `backend/core/utils.py`:
- Delete the `crypto_entry_limit_collar_bps: int = 15` and `crypto_pending_reprice_minutes: int = 2` lines from `AppConfig`.
- Delete their `os.getenv(...)` lines from `load_config()`.
- Delete `"crypto_entry_limit_collar_bps"` and `"crypto_pending_reprice_minutes"` from `SETTINGS_OVERRIDABLE_KEYS`.

- [ ] **Step 5: Run to verify it passes + full config test**

Run (locally): `cd backend && python3 -m unittest tests.test_etoro_config -v`
Expected: PASS

- [ ] **Step 6: Run the full suite (container) to catch any frontend/settings coupling**

Run (container): `python -m pytest -q`
Expected: PASS. If a settings/API test references the removed keys, update it to drop them (they were never used for behaviour).

- [ ] **Step 7: Commit**

```bash
git add backend/core/utils.py backend/tests/test_etoro_config.py
git commit -m "chore(trading): remove unused crypto_entry_limit_collar_bps and crypto_pending_reprice_minutes"
```

---

## Self-Review

- **Spec coverage:** widen crypto band+timeout → Task 2; stock await → Task 2; remove dead knobs → Task 3; testable marketable helper → Task 1. Stock "safer resolution" is realized via the longer await default (Task 2); no logic change to `_resolve_submitted_order` is made because the existing timeout gate already requires the age threshold before abandoning — documented here so the reviewer does not expect a code change there. ✓
- **Placeholder scan:** all steps carry runnable code/commands; the one grep-gated removal (Task 3 Step 1) has an explicit STOP condition. ✓
- **Type consistency:** `is_marketable(ask, target, max_chase_bps)->bool` used identically in Task 1 Step 5. Config field names match `core/utils.py`. ✓
</content>
