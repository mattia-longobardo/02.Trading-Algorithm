# Robustness Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the LONG-only `entry > stop` invariant at the entry gate, stop ranking trades by the uncalibrated `confidence`, and tighten one weak test.

**Architecture:** Three small, independent edits to `services/trade_manager.py` and `tests/test_exit_levels.py`, each with its own test. No schema, no broker, no config.

**Tech Stack:** Python 3.14, stdlib `unittest`. Full suite runs in the `trading-backend` docker container (`docker cp` the worktree `backend/` to `/tmp/wt` then `python -m pytest`); pure-module tests run locally via `python3 -m unittest`.

## Global Constraints

- The bot is LONG-only; all maths assume `entry_price > stop_loss`.
- `confidence` stays persisted to the DB and shown in the UI — this plan only stops it from influencing which trades open.
- Tests are stdlib `unittest`; stub `dotenv` before importing app modules (copy from `tests/test_portfolio_risk.py:7-9`).

---

### Task 1: Enforce `entry > stop` at the entry gate

**Files:**
- Modify: `backend/services/trade_manager.py` — `_signal_has_required_levels` (starts line 611); insert the check after the per-field positivity loop (after line 621).
- Test: `backend/tests/test_trade_manager_risk.py` (add a focused test) — or `test_trade_manager_orders.py`; pick the file that already constructs a `TradeManager` with a signal helper.

**Interfaces:**
- Consumes: nothing.
- Produces: `_signal_has_required_levels(signal)` now returns False when `entry_price <= stop_loss`.

- [ ] **Step 1: Write the failing test**

Locate how an existing `TradeManager` test builds a manager + a signal (search `_signal_has_required_levels` or a `_signal(` helper in `tests/test_trade_manager_etoro.py`). Add a test in the most fitting existing test class:

```python
def test_signal_rejected_when_entry_not_above_stop(self):
    sig = self._signal(entry_price=100.0, stop_loss=100.0, take_profit=130.0)
    self.assertFalse(self.manager._signal_has_required_levels(sig))
    sig2 = self._signal(entry_price=90.0, stop_loss=100.0, take_profit=130.0)
    self.assertFalse(self.manager._signal_has_required_levels(sig2))
    ok = self._signal(entry_price=100.0, stop_loss=90.0, take_profit=130.0)
    self.assertTrue(self.manager._signal_has_required_levels(ok))
```

If no `_signal(...)` helper exists in the chosen file, build the signal dict inline with the same keys the file's other tests use.

- [ ] **Step 2: Run test to verify it fails**

Run (in container): `python -m pytest tests/test_trade_manager_etoro.py -k entry_not_above_stop -v`
Expected: FAIL — the equal/below-stop signals currently pass the gate.

- [ ] **Step 3: Add the invariant check**

In `backend/services/trade_manager.py`, immediately after the per-field loop closes (after line 621, before the `trailing_take_profit_distance = signal.get(...)` line), add:

```python
        entry_price = float(signal["entry_price"])
        stop_loss = float(signal["stop_loss"])
        if entry_price <= stop_loss:
            self.logger.warning(
                "GPT returned OPEN for %s with entry_price=%s <= stop_loss=%s (not a valid long); skipping trade",
                signal.get("symbol"),
                entry_price,
                stop_loss,
            )
            return False
```

- [ ] **Step 4: Run test to verify it passes**

Run (in container): `python -m pytest tests/test_trade_manager_etoro.py -k entry_not_above_stop -v`
Expected: PASS

- [ ] **Step 5: Run the trade-manager suites for regressions**

Run (in container): `python -m pytest tests/test_trade_manager_etoro.py tests/test_trade_manager_orders.py tests/test_trade_manager_risk.py -v`
Expected: PASS (no regressions)

- [ ] **Step 6: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_etoro.py
git commit -m "feat(trading): reject entry signals where entry_price <= stop_loss"
```

---

### Task 2: Drop `confidence` from signal ranking

**Files:**
- Modify: `backend/services/trade_manager.py` — `_rank_signals` (lines 741-747).
- Test: `backend/tests/test_trade_manager_risk.py` (or wherever `_rank_signals` is reachable; it's a method on `TradeManager`).

**Interfaces:**
- Consumes: nothing.
- Produces: `_rank_signals(signals)` orders by `trade_score` desc with a stable `symbol` tie-break; `confidence` no longer affects order.

- [ ] **Step 1: Write the failing test**

```python
def test_rank_ignores_confidence_and_ties_break_on_symbol(self):
    signals = [
        {"symbol": "BBB", "trade_score": 80, "confidence": 0.99},
        {"symbol": "AAA", "trade_score": 80, "confidence": 0.10},
        {"symbol": "CCC", "trade_score": 90, "confidence": 0.10},
    ]
    ranked = self.manager._rank_signals(signals)
    # highest score first; equal scores tie-break by symbol ascending, NOT by confidence
    self.assertEqual([s["symbol"] for s in ranked], ["CCC", "AAA", "BBB"])
```

- [ ] **Step 2: Run test to verify it fails**

Run (in container): `python -m pytest tests/test_trade_manager_risk.py -k rank_ignores_confidence -v`
Expected: FAIL — current code puts BBB before AAA (confidence 0.99 > 0.10).

- [ ] **Step 3: Change the sort key**

Replace `_rank_signals` (lines 741-747) with:

```python
    def _rank_signals(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # Rank purely by GPT trade_score; confidence is intentionally excluded
        # (historically uncorrelated-to-inverted with outcome). Tie-break on
        # symbol so the ordering is deterministic and confidence-independent.
        def sort_key(signal: dict[str, Any]) -> tuple[float, str]:
            score = self._as_float(signal.get("trade_score")) or 0.0
            symbol = str(signal.get("symbol") or "")
            return (-score, symbol)
        return sorted(signals, key=sort_key)
```

(Note the key flips to ascending with `-score` so the secondary `symbol` sorts ascending while score sorts descending.)

- [ ] **Step 4: Run test to verify it passes**

Run (in container): `python -m pytest tests/test_trade_manager_risk.py -k rank_ignores_confidence -v`
Expected: PASS

- [ ] **Step 5: Run the trade-manager suites**

Run (in container): `python -m pytest tests/test_trade_manager_risk.py tests/test_trade_manager_orders.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_risk.py
git commit -m "feat(trading): rank signals by trade_score only, drop uncalibrated confidence"
```

---

### Task 3: Tighten `test_trailing_invariant_holds`

**Files:**
- Modify: `backend/tests/test_exit_levels.py` — the `test_trailing_invariant_holds` method.

**Interfaces:**
- Consumes: `services.exit_levels.normalize_exit_levels` (unchanged).
- Produces: nothing.

- [ ] **Step 1: Replace the weak assertion**

In `backend/tests/test_exit_levels.py`, find `test_trailing_invariant_holds`. Its body currently computes `distance_pct = out["trailing_take_profit_distance"] / 100.0 * 100.0` (a no-op). Replace the method body with a version that divides by the actual entry price and asserts the real percent relationship:

```python
    def test_trailing_invariant_holds(self):
        entry = 100.0
        out = normalize_exit_levels(
            entry_price=entry, stop_loss=80.0, take_profit=200.0,
            trailing_take_profit_distance=5.0, trailing_take_profit_activation_pct=1.0,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        distance_pct = out["trailing_take_profit_distance"] / entry * 100.0
        # activation must clear distance% so the trigger sits above entry at arming
        self.assertGreater(out["trailing_take_profit_activation_pct"], distance_pct)
```

- [ ] **Step 2: Run the test**

Run (locally): `cd backend && python3 -m unittest tests.test_exit_levels -v`
Expected: PASS (6 tests, including the tightened one)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_exit_levels.py
git commit -m "test(trading): tighten trailing-TP invariant assertion to use entry price"
```

---

## Self-Review

- **Spec coverage:** Sub-feature 1's three items → Task 1 (entry>stop), Task 2 (drop confidence from ranking), Task 3 (tighten test). ✓
- **Placeholder scan:** all steps contain runnable code or exact commands; wiring uses verified line numbers + content anchors. ✓
- **Type consistency:** `_signal_has_required_levels(signal)->bool` and `_rank_signals(signals)->list` signatures unchanged; only internals edited. ✓
</content>
