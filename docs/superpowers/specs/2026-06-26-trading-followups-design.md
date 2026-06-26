# Trading Bot Follow-ups — Design Spec

**Date:** 2026-06-26
**Status:** Approved (design), pending implementation plans
**Builds on:** the merged performance branch (exit-level R-clamp, dollar-risk sizing cap, regime gate, R logging — commits `c6bbc0a..5dd22b3`, merged at `cf0d456`).

## Context

The performance analysis (`docs/analysis/2026-06-25-trade-performance.md`) left four follow-ups out of the first plan's scope. This spec designs all four as **independent sub-features**, each becoming its own implementation plan (spec → plan → subagent execution), implemented in the order below. All changes are config-driven and reversible where they affect runtime behaviour; the bot is LONG-only; tests are stdlib `unittest` run with `python -m pytest` (full suite) or `python3 -m unittest` (pure modules, locally).

Cross-feature constraints (apply to every sub-feature):
- New tunables go in three places in `core/utils.py`: the `AppConfig` field, the `load_config()` env parse, and (if operator-tunable) `SETTINGS_OVERRIDABLE_KEYS`.
- DB schema changes use the idempotent migration pattern `_ensure_optional_trade_columns()` in `core/db.py:210-220` (PRAGMA-checked `ALTER TABLE ... ADD COLUMN`). No destructive migrations.
- Pure logic (no DB/broker/IO) lives in its own small module so it is unit-testable in isolation, mirroring `services/exit_levels.py`, `services/regime.py`, `services/trade_analytics.py`.

---

## Sub-feature 1 — Robustness quick wins

**Goal:** Close the three review follow-ups; remove the uncalibrated `confidence` from trade selection.

**Design:**

1. **`entry > stop` invariant at the gate.** `_signal_has_required_levels(signal)` (`services/trade_manager.py`, ~line 611) currently validates each of `entry_price`/`stop_loss`/`take_profit` is a positive number, but not that `entry_price > stop_loss`. Add that check; reject (return False) a signal that violates it, with a log line. This makes the LONG-only assumption explicit at the entry gate instead of relying on every downstream R-formula to no-op.

2. **Drop `confidence` from ranking.** `_rank_signals` (`services/trade_manager.py:741-747`) sorts by `(trade_score, confidence)` desc. The analysis showed confidence is uncorrelated-to-inverted with outcome. Change the sort key to `trade_score` only (with a stable tie-break, e.g. symbol, so ordering is deterministic). `confidence` is still stored to the DB (`_save_new_trade`) and shown in the UI as a record — it just no longer influences which trades open. This is the ONLY decision site that uses confidence (per exploration), so the change is contained.

3. **Tighten `test_trailing_invariant_holds`.** In `tests/test_exit_levels.py`, the assertion computes `distance_pct = out["trailing_take_profit_distance"] / 100.0 * 100.0` (a no-op that only works because entry=100). Change it to divide by the actual `entry_price` so it asserts the real percentage relationship.

**Files:** `services/trade_manager.py`, `tests/test_trade_manager_*` (for the gate + ranking), `tests/test_exit_levels.py`.
**Risk:** Low. No schema, no broker, no config.
**Testing:** Unit tests: a signal with `entry <= stop` is rejected; ranking orders by trade_score and ignores confidence; the tightened exit test still passes.

---

## Sub-feature 2 — Order execution (reduce CANCELLED rate)

**Goal:** Cut the ~35% order-cancellation rate (historically 22 STOCK + 15 CRYPTO) by filling marketable entries instead of waiting for an exact limit touch.

**Background (from exploration):** Crypto entries are emulated-limit: a PENDING trade waits until `ask ≤ _entry_fill_ceiling(target)` (chase up to `crypto_entry_max_chase_bps`=40), else cancels at `crypto_pending_cancel_minutes`=12 (`ENTRY_TIMEOUT`). `crypto_entry_limit_collar_bps` and `crypto_pending_reprice_minutes` are **defined but unused**. Stocks submit a broker market order; if its status can't be resolved within `order_await_timeout_minutes`=360, it is abandoned (`ORDER_AWAIT_TIMEOUT`); stock entries are skipped entirely when the market is closed.

**CORRECTION (verified against code `trade_manager.py:863-909`):** crypto entries are ALREADY marketable up to `crypto_entry_max_chase_bps` (the fill condition is `ask ≤ target × (1 + max_chase/10_000)`, i.e. fill at market within +0.40% of target). The unused `crypto_entry_limit_collar_bps` (15 bps) is a *tighter* band than the chase (40 bps), so activating it would reduce fills, not increase them. Therefore "marketable-limit with collar" and "widen chase/timeout" collapse to the same lever. The real fix is to **widen the existing fill band and timeout**, plus make stock order resolution less trigger-happy. (User confirmed this corrected direction.)

**Design:**

1. **Crypto — widen the fill band + timeout (config defaults).** Raise `crypto_entry_max_chase_bps` (40 → 80) so entries fill at market within a larger slippage tolerance, and `crypto_pending_cancel_minutes` (12 → 20) so a pending has longer to fill before `ENTRY_TIMEOUT`. Config-only, reversible.
2. **Stock — safer order resolution + longer await.** In `_resolve_submitted_order`, do NOT abandon on a single transient `None` status read; only abandon a `None`-status order when it is past the timeout (current behaviour) AND we have not just transiently failed to read it — i.e. keep the existing timeout gate but document that `None` means "not found", and raise `order_await_timeout_minutes` (360 → 720) so a slow fill near the close is not abandoned prematurely.
3. **Remove the two dead knobs.** Delete `crypto_entry_limit_collar_bps` and `crypto_pending_reprice_minutes` from `AppConfig`, `load_config`, and `SETTINGS_OVERRIDABLE_KEYS` (they are defined-but-unused, and keeping a collar knob that contradicts the chase semantics is a maintenance trap).
4. **Marketable decision made testable.** Extract the fill condition into a pure helper `is_marketable(ask, target, max_chase_bps) -> bool` so the band logic is unit-tested in isolation; `sync_pending_trade` calls it instead of the inline `ask > self._entry_fill_ceiling(target)` comparison.

**Decision applied:** widen band+timeout (crypto) + robust stock resolution + remove dead knobs (user-confirmed).
**Files:** `services/trade_manager.py` (pending sync + order resolution), `core/utils.py` (config), tests.
**Risk:** Medium — touches live order code. Mitigations: behaviour changes are config-default value changes + one extracted pure helper (`is_marketable`); no change to how orders are actually placed (still `open_market_position`); the helper preserves the exact current inequality.

---

## Sub-feature 3 — Persist R metrics + dashboard

**Goal:** Make exit-capture quality visible without ad-hoc SQL: persist per-trade R metrics and MAE/MFE, surface aggregate "captured R" and per-trade columns in the UI.

**Design:**

1. **Schema (idempotent ADD COLUMN via `_ensure_optional_trade_columns`):**
   - `planned_risk_per_unit REAL` — `entry − stop` at open.
   - `planned_reward_risk REAL` — `(tp − entry)/risk` at open.
   - `realized_r REAL` — `(close − entry)/risk` at close.
   - `low_water_mark REAL` — running min price seen while open (mirror of existing `high_water_mark`).
   - `mae REAL`, `mfe REAL` — max adverse / favorable excursion, stored as **R-multiples** (`(low_water − entry)/risk` and `(high_water − entry)/risk`) for interpretability.
2. **Population:**
   - At open (`_save_new_trade`): set `planned_risk_per_unit`, `planned_reward_risk` from `trade_analytics.planned_metrics`.
   - During monitoring (the open-trade sync that already updates `high_water_mark`): also update `low_water_mark` from current price.
   - At close (`_mark_trade_closed`): set `realized_r` from `trade_analytics.realized_r`; compute final `mae`/`mfe` from low/high water marks vs entry/risk.
3. **Pure helpers:** extend `services/trade_analytics.py` with `excursion_r(entry, stop, water_mark) -> float | None` so MAE/MFE math is unit-tested in isolation.
4. **Metrics API (`metrics_service.compute_metrics`):** add `avg_captured_r` (mean `realized_r` over closed trades in window) and `avg_planned_rr` (mean `planned_reward_risk`). `list_trades` already `SELECT *`, so the new columns reach the frontend automatically.
5. **Frontend:**
   - `components/dashboard/kpi-strip.tsx`: add a "Captured R" KPI card (avg realized R, with avg planned RR as subtext).
   - `components/trades/trades-table.tsx`: add columns for planned RR, realized R, MAE (R), MFE (R).
   - `lib/types.ts`: extend the `Trade` type with the new optional numeric fields.

**Decision applied:** essential R + MAE/MFE (chosen).
**Files:** `core/db.py`, `services/trade_manager.py`, `services/trade_analytics.py`, `services/metrics_service.py`, frontend `kpi-strip.tsx` / `trades-table.tsx` / `lib/types.ts`, tests.
**Risk:** Medium. Schema migration is idempotent and additive; existing rows get NULLs (handled as "n/a" in UI and skipped in averages).
**Testing:** unit tests for `excursion_r`; metrics test that `avg_captured_r` averages only non-null realized_r; a migration test that the columns exist after `initialize_databases`. Frontend: render with and without the new fields (null-safe).

---

## Sub-feature 4 — Backtest harness (deterministic exit/sizing replay)

**Goal:** Provide an A/B harness that replays historical trades through OLD vs NEW exit/sizing/regime logic over historical daily prices, so deterministic strategy changes have a measurable baseline before going live.

**Scope decision:** deterministic **exit/sizing replay**, NOT a full GPT-strategy backtest. Entries are taken as given from a historical trades dataset (default: the backup `db_backup_2026-06-26/trades.sqlite`, 108 real trades, which carry entry/stop/tp/trailing params, symbol, category, open timestamp). GPT is not re-invoked.

**Design:**

1. **New package `backend/backtest/`:**
   - `prices.py` — a price provider over `market_data.sqlite`: `daily_bars(symbol, from_ts, to_ts) -> list[bar]` (ascending). Pure read-only.
   - `simulator.py` — the core engine. For one historical trade:
     - Choose exit levels: **OLD** = the recorded raw levels; **NEW** = `exit_levels.normalize_exit_levels(...)` applied to the recorded entry/stop/tp/trailing.
     - Optionally apply the **regime gate** (NEW) at entry: if `passes_regime_gate` is False on the entry date, the trade is "not taken" (excluded from NEW results) — quantifies the gate's filtering.
     - Size with `portfolio_risk.suggest_size(...)` (NEW, with the dollar-risk cap) vs the recorded `allocated_capital` (OLD) to get position size and dollar PnL.
     - Walk daily bars from the entry date forward; each day, update high/low water marks and evaluate the existing pure exit functions (`_compute_trailing_*`, `_downside_close_reason`, `_trailing_take_profit_close_reason`) to find the first triggered exit. Close at that level; compute realized R and PnL.
   - `run.py` — CLI `python -m backtest.run --trades <db> --mode old|new|ab` that aggregates results and prints an A/B report: realized-R distribution, win rate, avg win/avg loss, % winners reaching planned TP, total/أverage PnL, and (for `ab`) the delta and the count of trades the regime gate would have skipped.
2. **Intraday ambiguity rule (documented):** with daily bars, if both the stop and a profit target fall within a single day's [low, high], assume the **adverse** level triggers first (conservative). State this in `run.py` output and in the module docstring.
3. **Purity:** the simulator imports only the existing pure functions + the price provider; no broker, no GPT, no live DB writes. Fully deterministic.
4. **Reuse, don't duplicate:** the simulator must call the SAME pure exit/level/sizing functions the live bot uses (`exit_levels`, `regime`, `portfolio_risk`, and the static `_compute_*`/`_*_close_reason` helpers). If a needed helper is currently a private staticmethod on `TradeManager`, extract it to a pure module (e.g. `services/exit_eval.py`) and have `TradeManager` import it — so live and backtest share one implementation. (This extraction is part of this sub-feature's plan.)

**Files:** new `backend/backtest/{__init__,prices,simulator,run}.py`, possibly new `services/exit_eval.py` (extraction), tests `backend/tests/test_backtest_simulator.py`.
**Risk:** Medium-high (new subsystem) but isolated — it does not touch the live trading path except the optional helper extraction (which is behaviour-preserving and covered by existing trade_manager tests).
**Testing:** unit tests with synthetic daily price series proving: a trade that gaps below stop closes at stop with realized_r ≈ −1; a trade that runs to TP closes at TP; the intraday-ambiguity rule picks the adverse exit; the regime gate excludes a below-SMA entry. An end-to-end smoke test running the harness over a tiny fixture trades DB.

---

## Implementation order & decomposition

Four independent plans, implemented in this order (smallest/safest first, backtest last so it can exercise the others):

1. `2026-06-26-robustness-quick-wins` (Sub-feature 1)
2. `2026-06-26-order-execution-marketable` (Sub-feature 2)
3. `2026-06-26-r-metrics-and-dashboard` (Sub-feature 3)
4. `2026-06-26-backtest-harness` (Sub-feature 4)

Each plan produces working, tested software on its own. Sub-feature 4 depends on 1–3 only loosely (it reuses the pure exit/sizing functions that already exist on `cf0d456`); it can validate the others once built.
</content>
