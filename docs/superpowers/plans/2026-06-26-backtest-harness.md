# Backtest Harness (Deterministic Exit/Sizing Replay) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replay historical trades through OLD vs NEW exit/sizing/regime logic over historical daily prices, producing an A/B report — so deterministic strategy changes have a measurable baseline.

**Architecture:** Extract the pure exit-trigger functions into `services/exit_eval.py` (shared by the live bot and the simulator), then build a `backend/backtest/` package: a price reader over `market_data.sqlite`, a pure per-trade simulator, and a CLI aggregator. No GPT, no broker, no live-DB writes. Entries are taken as given from a historical trades DB (default: the backup).

**Tech Stack:** Python 3.14, stdlib `unittest` + `sqlite3`. Pure modules tested locally via `python3 -m unittest`.

## Global Constraints

- The simulator reuses the SAME pure functions the live bot uses: `services/exit_levels.normalize_exit_levels`, `services/regime.passes_regime_gate`, `services/portfolio_risk.PortfolioRiskService.suggest_size`, and the exit-trigger functions extracted in Task 1.
- **Intraday ambiguity rule:** with daily bars, if a day's `[low, high]` straddles both a downside trigger (stop/trailing-stop) and an upside trigger (TP/trailing-TP), assume the **adverse** (downside) triggers first. State this in code docstrings and CLI output.
- **GPT is not replayed.** Entries (symbol, entry_price, stop_loss, take_profit, trailing params, open_timestamp, allocated_capital) come from the historical trades DB as-is.
- The bot is LONG-only; `risk = entry − stop > 0`.
- `market_data.sqlite` holds daily OHLCV per symbol in `ohlcv_*` tables, resolved via the `market_symbols` registry (mirror how `services/data_manager.py` resolves a symbol's table). Date range ~2024-06 to 2026-06.
- No change to the live trading path except the behaviour-preserving extraction in Task 1.

---

### Task 1: Extract pure exit-trigger functions to `services/exit_eval.py`

**Files:**
- Create: `backend/services/exit_eval.py`
- Create: `backend/tests/test_exit_eval.py`
- Modify: `backend/services/trade_manager.py` — the four staticmethods at lines 105-205 delegate to the new module.

**Interfaces:**
- Produces (in `services/exit_eval.py`):
  - `compute_trailing_stop_price(high_water_mark, trailing_stop_distance) -> float | None`
  - `compute_trailing_take_profit_price(high_water_mark, entry_price, trailing_take_profit_distance, trailing_take_profit_activation_pct, min_profit_buffer_pct=0.0) -> float | None`
  - `downside_close_reason(current_price, stop_loss, trailing_stop_price) -> str | None`
  - `trailing_take_profit_close_reason(current_price, trailing_take_profit_price) -> str | None`
  - Same logic and return values as the current `TradeManager` staticmethods.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_exit_eval.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.exit_eval import (
    compute_trailing_stop_price,
    compute_trailing_take_profit_price,
    downside_close_reason,
    trailing_take_profit_close_reason,
)


class ExitEvalTests(unittest.TestCase):
    def test_trailing_stop_price(self):
        self.assertEqual(compute_trailing_stop_price(100.0, 5.0), 95.0)
        self.assertIsNone(compute_trailing_stop_price(100.0, None))

    def test_trailing_tp_price_arms_above_activation(self):
        # entry 100, activation 5% -> arms at 105; hwm 110, distance 3 -> trigger 107
        self.assertAlmostEqual(compute_trailing_take_profit_price(110.0, 100.0, 3.0, 5.0), 107.0, places=6)
        # below activation -> None
        self.assertIsNone(compute_trailing_take_profit_price(104.0, 100.0, 3.0, 5.0))

    def test_downside_reason(self):
        self.assertEqual(downside_close_reason(89.0, 90.0, None), "STOP_LOSS")
        self.assertIsNone(downside_close_reason(95.0, 90.0, None))

    def test_trailing_tp_reason(self):
        self.assertEqual(trailing_take_profit_close_reason(106.0, 107.0), "TRAILING_TAKE_PROFIT")
        self.assertIsNone(trailing_take_profit_close_reason(108.0, 107.0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run (locally): `cd backend && python3 -m unittest tests.test_exit_eval -v`
Expected: FAIL — `services.exit_eval` missing.

- [ ] **Step 3: Create the module by moving the logic**

Create `backend/services/exit_eval.py` containing the four functions, copied verbatim from the bodies of `TradeManager._compute_trailing_stop_price` (lines 105-109), `_compute_trailing_take_profit_price` (115-144), `_downside_close_reason` (175-193), `_trailing_take_profit_close_reason` (195-202) — as module-level functions (drop `self`, keep the exact logic, rounding, and the `min_profit_buffer_pct` floor). No behaviour change.

- [ ] **Step 4: Delegate from `TradeManager`**

In `backend/services/trade_manager.py`, add the import:

```python
from services import exit_eval
```

Replace the four staticmethod bodies so each delegates (keeping the methods so existing `self._compute_*` / `self._downside_*` call sites are untouched):

```python
    @staticmethod
    def _compute_trailing_stop_price(high_water_mark, trailing_stop_distance):
        return exit_eval.compute_trailing_stop_price(high_water_mark, trailing_stop_distance)

    @staticmethod
    def _compute_trailing_take_profit_price(high_water_mark, entry_price, trailing_take_profit_distance, trailing_take_profit_activation_pct, min_profit_buffer_pct=0.0):
        return exit_eval.compute_trailing_take_profit_price(high_water_mark, entry_price, trailing_take_profit_distance, trailing_take_profit_activation_pct, min_profit_buffer_pct)

    @staticmethod
    def _downside_close_reason(current_price, stop_loss, trailing_stop_price):
        return exit_eval.downside_close_reason(current_price, stop_loss, trailing_stop_price)

    @staticmethod
    def _trailing_take_profit_close_reason(current_price, trailing_take_profit_price):
        return exit_eval.trailing_take_profit_close_reason(current_price, trailing_take_profit_price)
```

(Preserve the original type annotations on these signatures by copying them from the current code.)

- [ ] **Step 5: Run the new test + the live exit tests**

Run (locally): `cd backend && python3 -m unittest tests.test_exit_eval -v`
Expected: PASS
Run (container): `python -m pytest tests/test_trade_manager_orders.py tests/test_close_resolution.py -v`
Expected: PASS (delegation is behaviour-preserving)

- [ ] **Step 6: Commit**

```bash
git add backend/services/exit_eval.py backend/tests/test_exit_eval.py backend/services/trade_manager.py
git commit -m "refactor(trading): extract pure exit-trigger functions to services/exit_eval"
```

---

### Task 2: Price reader over `market_data.sqlite`

**Files:**
- Create: `backend/backtest/__init__.py` (empty)
- Create: `backend/backtest/prices.py`
- Create: `backend/tests/test_backtest_prices.py`

**Interfaces:**
- Produces: `backtest.prices.load_daily_bars(market_db_path: str, symbol: str) -> list[dict]` — ascending-by-timestamp bars `{"timestamp": str, "open": float, "high": float, "low": float, "close": float, "volume": float}` for the symbol; `[]` if the symbol has no table.

- [ ] **Step 1: Write the failing test (builds a tiny market DB)**

```python
# backend/tests/test_backtest_prices.py
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from backtest.prices import load_daily_bars


def _make_market_db(path, symbol, table, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_symbols (symbol TEXT, table_name TEXT, created_at TEXT)")
    conn.execute("INSERT INTO market_symbols (symbol, table_name) VALUES (?, ?)", (symbol, table))
    conn.execute(f"CREATE TABLE {table} (timestamp TEXT PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume REAL)")
    conn.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?)", rows)
    conn.commit()


class LoadDailyBarsTests(unittest.TestCase):
    def test_loads_ascending(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "m.sqlite")
            _make_market_db(p, "AAA", "ohlcv_AAA", [
                ("2026-01-02", 10, 11, 9, 10.5, 100),
                ("2026-01-01", 10, 10.5, 9.5, 10, 100),
            ])
            bars = load_daily_bars(p, "AAA")
            self.assertEqual([b["timestamp"] for b in bars], ["2026-01-01", "2026-01-02"])
            self.assertEqual(bars[1]["high"], 11.0)

    def test_unknown_symbol_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "m.sqlite")
            _make_market_db(p, "AAA", "ohlcv_AAA", [("2026-01-01", 10, 10, 10, 10, 1)])
            self.assertEqual(load_daily_bars(p, "ZZZ"), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run (locally): `cd backend && python3 -m unittest tests.test_backtest_prices -v`
Expected: FAIL — `backtest.prices` missing.

- [ ] **Step 3: Implement the reader**

Before writing, read `backend/services/data_manager.py` to confirm how a symbol maps to its `ohlcv_*` table (registry lookup vs. `SYMBOL_TABLE_PREFIX` normalization). Implement `load_daily_bars` to use the same resolution. A registry-first implementation:

```python
# backend/backtest/prices.py
"""Read daily OHLCV bars from market_data.sqlite for backtest replay. Read-only."""

from __future__ import annotations

import sqlite3


def _table_for_symbol(conn: sqlite3.Connection, symbol: str) -> str | None:
    row = conn.execute(
        "SELECT table_name FROM market_symbols WHERE symbol = ?", (symbol,)
    ).fetchone()
    return row[0] if row else None


def load_daily_bars(market_db_path: str, symbol: str) -> list[dict]:
    conn = sqlite3.connect(market_db_path)
    try:
        table = _table_for_symbol(conn, symbol)
        if not table:
            return []
        rows = conn.execute(
            f"SELECT timestamp, open, high, low, close, volume FROM {table} ORDER BY timestamp"
        ).fetchall()
    finally:
        conn.close()
    return [
        {"timestamp": r[0], "open": float(r[1]), "high": float(r[2]),
         "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}
        for r in rows
    ]
```

If `data_manager.py` shows the registry stores a different column name or the table is resolved by prefix instead, adjust `_table_for_symbol` to match — the test's `_make_market_db` mirrors the registry shape; align both to the real schema and STOP to report if they differ materially.

- [ ] **Step 4: Run to verify it passes**

Run (locally): `cd backend && python3 -m unittest tests.test_backtest_prices -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/__init__.py backend/backtest/prices.py backend/tests/test_backtest_prices.py
git commit -m "feat(backtest): read daily OHLCV bars from market_data.sqlite"
```

---

### Task 3: Per-trade simulator

**Files:**
- Create: `backend/backtest/simulator.py`
- Create: `backend/tests/test_backtest_simulator.py`

**Interfaces:**
- Consumes: `services.exit_eval.*` (Task 1), `services.exit_levels.normalize_exit_levels`, `services.regime.passes_regime_gate`.
- Produces: `backtest.simulator.simulate_trade(trade: dict, entry_bars: list[dict], forward_bars: list[dict], *, mode: str, exit_cfg: dict, regime_cfg: dict) -> dict` returning `{"taken": bool, "exit_reason": str|None, "close_price": float|None, "realized_r": float|None, "reached_tp": bool}`.
  - `trade` carries `entry_price, stop_loss, take_profit, trailing_take_profit_distance, trailing_take_profit_activation_pct, trailing_stop_distance`.
  - `mode`: `"old"` uses the trade's recorded levels as-is and skips the regime gate; `"new"` applies `normalize_exit_levels` to the levels and applies the regime gate using `entry_bars`.
  - `exit_cfg`: `{"min_reward_risk", "arm_r", "trail_r", "min_profit_buffer_pct"}`. `regime_cfg`: `{"enabled", "sma_period"}`.

- [ ] **Step 1: Write the failing tests (synthetic bars)**

```python
# backend/tests/test_backtest_simulator.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from backtest.simulator import simulate_trade

EXIT_CFG = {"min_reward_risk": 1.5, "arm_r": 1.5, "trail_r": 1.0, "min_profit_buffer_pct": 0.5}
REGIME_OFF = {"enabled": False, "sma_period": 200}


def _bar(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}


def _trade(**kw):
    base = dict(entry_price=100.0, stop_loss=90.0, take_profit=130.0,
                trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
                trailing_stop_distance=None)
    base.update(kw)
    return base


class SimulateTradeTests(unittest.TestCase):
    def test_stop_hit_realizes_minus_one_r(self):
        fwd = [_bar("d1", 100, 101, 88, 95)]  # low 88 < stop 90
        out = simulate_trade(_trade(), [], fwd, mode="old", exit_cfg=EXIT_CFG, regime_cfg=REGIME_OFF)
        self.assertTrue(out["taken"])
        self.assertEqual(out["exit_reason"], "STOP_LOSS")
        self.assertAlmostEqual(out["close_price"], 90.0, places=6)
        self.assertAlmostEqual(out["realized_r"], -1.0, places=6)

    def test_tp_hit_realizes_positive(self):
        fwd = [_bar("d1", 100, 131, 99, 130)]  # high 131 > tp 130
        out = simulate_trade(_trade(), [], fwd, mode="old", exit_cfg=EXIT_CFG, regime_cfg=REGIME_OFF)
        self.assertEqual(out["exit_reason"], "TAKE_PROFIT")
        self.assertTrue(out["reached_tp"])
        self.assertAlmostEqual(out["realized_r"], 3.0, places=6)  # (130-100)/10

    def test_intraday_ambiguity_picks_adverse(self):
        fwd = [_bar("d1", 100, 131, 88, 100)]  # both tp(130) and stop(90) inside [88,131]
        out = simulate_trade(_trade(), [], fwd, mode="old", exit_cfg=EXIT_CFG, regime_cfg=REGIME_OFF)
        self.assertEqual(out["exit_reason"], "STOP_LOSS")  # adverse first

    def test_regime_gate_excludes_below_sma(self):
        # entry_bars: 200 closes all at 200, entry price 100 below SMA -> not taken
        entry_bars = [_bar(f"e{i}", 200, 200, 200, 200) for i in range(200)]
        fwd = [_bar("d1", 100, 101, 99, 100)]
        out = simulate_trade(_trade(), entry_bars, fwd, mode="new",
                             exit_cfg=EXIT_CFG, regime_cfg={"enabled": True, "sma_period": 200})
        self.assertFalse(out["taken"])

    def test_open_at_end_marks_unclosed(self):
        fwd = [_bar("d1", 100, 105, 99, 104)]  # never hits stop or tp
        out = simulate_trade(_trade(), [], fwd, mode="old", exit_cfg=EXIT_CFG, regime_cfg=REGIME_OFF)
        self.assertIsNone(out["exit_reason"])  # still open at data end


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run (locally): `cd backend && python3 -m unittest tests.test_backtest_simulator -v`
Expected: FAIL — `backtest.simulator` missing.

- [ ] **Step 3: Implement the simulator**

```python
# backend/backtest/simulator.py
"""Deterministic per-trade exit replay. Pure: prices in, verdict out.

Daily granularity. Intraday-ambiguity rule: if a day's [low, high] straddles
both an adverse (stop/trailing-stop) and a favorable (TP/trailing-TP) trigger,
the adverse one is assumed to fire first (conservative). GPT entry selection is
NOT replayed — the trade's entry/levels are taken as given.
"""

from __future__ import annotations

from services import exit_eval
from services.exit_levels import normalize_exit_levels
from services.regime import passes_regime_gate


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def simulate_trade(trade, entry_bars, forward_bars, *, mode, exit_cfg, regime_cfg):
    entry = float(trade["entry_price"])
    stop = float(trade["stop_loss"])
    tp = _f(trade.get("take_profit"))
    ttp_dist = _f(trade.get("trailing_take_profit_distance"))
    ttp_act = _f(trade.get("trailing_take_profit_activation_pct"))
    ts_dist = _f(trade.get("trailing_stop_distance"))
    risk = entry - stop
    result = {"taken": True, "exit_reason": None, "close_price": None,
              "realized_r": None, "reached_tp": False}
    if risk <= 0:
        result["taken"] = False
        return result

    if mode == "new":
        if regime_cfg.get("enabled"):
            if not passes_regime_gate(entry_bars, int(regime_cfg["sma_period"]), current_price=entry):
                result["taken"] = False
                return result
        lv = normalize_exit_levels(
            entry, stop, tp, ttp_dist, ttp_act,
            min_reward_risk=exit_cfg["min_reward_risk"],
            arm_r=exit_cfg["arm_r"], trail_r=exit_cfg["trail_r"],
        )
        tp = lv["take_profit"]
        ttp_dist = lv["trailing_take_profit_distance"]
        ttp_act = lv["trailing_take_profit_activation_pct"]

    min_buf = exit_cfg.get("min_profit_buffer_pct", 0.0)
    hwm = entry
    for bar in forward_bars:
        hi = float(bar["high"]); lo = float(bar["low"])
        hwm = max(hwm, hi)
        ts_price = exit_eval.compute_trailing_stop_price(hwm, ts_dist)
        ttp_price = exit_eval.compute_trailing_take_profit_price(hwm, entry, ttp_dist, ttp_act, min_buf)
        # adverse first (conservative): test the day's low against downside triggers
        down = exit_eval.downside_close_reason(lo, stop, ts_price)
        if down == "STOP_LOSS":
            return _close(result, stop, entry, risk, "STOP_LOSS")
        if down == "TRAILING_STOP" and ts_price is not None:
            return _close(result, ts_price, entry, risk, "TRAILING_STOP")
        # favorable: test the day's high
        if tp is not None and hi >= tp:
            result["reached_tp"] = True
            return _close(result, tp, entry, risk, "TAKE_PROFIT")
        ttp_reason = exit_eval.trailing_take_profit_close_reason(lo, ttp_price)
        if ttp_reason == "TRAILING_TAKE_PROFIT" and ttp_price is not None:
            return _close(result, ttp_price, entry, risk, "TRAILING_TAKE_PROFIT")
    return result  # never triggered → still open at data end


def _close(result, price, entry, risk, reason):
    result["exit_reason"] = reason
    result["close_price"] = round(price, 8)
    result["realized_r"] = (price - entry) / risk
    return result
```

- [ ] **Step 4: Run to verify it passes**

Run (locally): `cd backend && python3 -m unittest tests.test_backtest_simulator -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/backtest/simulator.py backend/tests/test_backtest_simulator.py
git commit -m "feat(backtest): deterministic per-trade exit/regime replay simulator"
```

---

### Task 4: CLI aggregator `backtest.run`

**Files:**
- Create: `backend/backtest/run.py`
- Create: `backend/tests/test_backtest_run.py`

**Interfaces:**
- Consumes: `backtest.prices.load_daily_bars`, `backtest.simulator.simulate_trade`, `core.utils.load_config` (for exit/regime defaults).
- Produces:
  - `backtest.run.aggregate(results: list[dict]) -> dict` → `{"n_taken", "n_closed", "win_rate", "avg_realized_r", "pct_reached_tp", "total_r"}`.
  - `backtest.run.run_replay(trades_db_path, market_db_path, mode, exit_cfg, regime_cfg) -> dict` → aggregate over all trades in the DB.
  - `main()` CLI: `python -m backtest.run --trades <db> --market <db> --mode old|new|ab` printing the report (and for `ab`, both columns + deltas + regime-skipped count).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_backtest_run.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from backtest.run import aggregate


class AggregateTests(unittest.TestCase):
    def test_aggregate_basic(self):
        results = [
            {"taken": True, "exit_reason": "STOP_LOSS", "realized_r": -1.0, "reached_tp": False},
            {"taken": True, "exit_reason": "TAKE_PROFIT", "realized_r": 3.0, "reached_tp": True},
            {"taken": False, "exit_reason": None, "realized_r": None, "reached_tp": False},
        ]
        agg = aggregate(results)
        self.assertEqual(agg["n_taken"], 2)
        self.assertEqual(agg["n_closed"], 2)
        self.assertAlmostEqual(agg["avg_realized_r"], 1.0, places=6)
        self.assertAlmostEqual(agg["win_rate"], 0.5, places=6)
        self.assertAlmostEqual(agg["pct_reached_tp"], 0.5, places=6)
        self.assertAlmostEqual(agg["total_r"], 2.0, places=6)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run (locally): `cd backend && python3 -m unittest tests.test_backtest_run -v`
Expected: FAIL — `backtest.run` missing.

- [ ] **Step 3: Implement aggregate + run_replay + CLI**

```python
# backend/backtest/run.py
"""CLI: A/B replay of historical trades through OLD vs NEW exit/sizing/regime.

GPT entries are NOT replayed; daily granularity; intraday ambiguity resolves to
the adverse exit. Default trades DB is the backup snapshot.
"""

from __future__ import annotations

import argparse
import sqlite3

from backtest.prices import load_daily_bars
from backtest.simulator import simulate_trade


def aggregate(results: list[dict]) -> dict:
    taken = [r for r in results if r.get("taken")]
    closed = [r for r in taken if r.get("realized_r") is not None]
    rs = [float(r["realized_r"]) for r in closed]
    wins = [v for v in rs if v > 0]
    reached = [r for r in closed if r.get("reached_tp")]
    n_closed = len(closed)
    return {
        "n_taken": len(taken),
        "n_closed": n_closed,
        "win_rate": round(len(wins) / n_closed, 4) if n_closed else 0.0,
        "avg_realized_r": round(sum(rs) / n_closed, 4) if n_closed else 0.0,
        "pct_reached_tp": round(len(reached) / n_closed, 4) if n_closed else 0.0,
        "total_r": round(sum(rs), 4),
    }


def _load_trades(trades_db_path: str) -> list[dict]:
    conn = sqlite3.connect(trades_db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'CLOSED' AND open_timestamp IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def run_replay(trades_db_path, market_db_path, mode, exit_cfg, regime_cfg) -> dict:
    results = []
    for t in _load_trades(trades_db_path):
        bars = load_daily_bars(market_db_path, str(t["symbol"]))
        open_ts = str(t.get("open_timestamp") or "")[:10]
        entry_bars = [b for b in bars if b["timestamp"][:10] < open_ts]
        forward_bars = [b for b in bars if b["timestamp"][:10] >= open_ts]
        if not forward_bars:
            continue  # no price data to replay this symbol/date
        results.append(simulate_trade(t, entry_bars, forward_bars, mode=mode, exit_cfg=exit_cfg, regime_cfg=regime_cfg))
    return aggregate(results)


def _cfg_from_config():
    from core.utils import load_config
    c = load_config()
    exit_cfg = {
        "min_reward_risk": c.exit_min_reward_risk, "arm_r": c.exit_trailing_arm_r,
        "trail_r": c.exit_trailing_trail_r, "min_profit_buffer_pct": c.trailing_tp_min_profit_buffer_pct,
    }
    regime_cfg = {"enabled": c.regime_gate_enabled, "sma_period": c.regime_sma_period}
    return exit_cfg, regime_cfg


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest exit/sizing replay (GPT entries not replayed).")
    p.add_argument("--trades", required=True)
    p.add_argument("--market", default="data/market_data.sqlite")
    p.add_argument("--mode", choices=["old", "new", "ab"], default="ab")
    args = p.parse_args()
    exit_cfg, regime_cfg = _cfg_from_config()
    print("NOTE: daily bars; intraday ambiguity -> adverse exit assumed; GPT entries taken as-is.")
    modes = ["old", "new"] if args.mode == "ab" else [args.mode]
    reports = {m: run_replay(args.trades, args.market, m, exit_cfg, regime_cfg) for m in modes}
    for m, rep in reports.items():
        print(f"\n[{m.upper()}] {rep}")
    if args.mode == "ab":
        d_r = reports["new"]["avg_realized_r"] - reports["old"]["avg_realized_r"]
        print(f"\nDelta avg_realized_r (new-old): {round(d_r, 4)}")
        print(f"Trades regime gate skipped (taken old - taken new): {reports['old']['n_taken'] - reports['new']['n_taken']}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify aggregate passes**

Run (locally): `cd backend && python3 -m unittest tests.test_backtest_run -v`
Expected: PASS

- [ ] **Step 5: Smoke-run the CLI against the backup**

Run (container, where deps + data are available):
```
docker cp backend/. trading-backend:/tmp/wt && \
docker cp /home/mattia/docker/projects/02.Trading/db_backup_2026-06-26/trades.sqlite trading-backend:/tmp/bt_trades.sqlite && \
docker exec trading-backend sh -c 'cd /tmp/wt && python -m backtest.run --trades /tmp/bt_trades.sqlite --market /app/data/market_data.sqlite --mode ab'
```
Expected: prints OLD and NEW aggregate rows + deltas without error. (If many trades are skipped for missing price data, the NOTE explains it — record the taken/closed counts.)

- [ ] **Step 6: Commit**

```bash
git add backend/backtest/run.py backend/tests/test_backtest_run.py
git commit -m "feat(backtest): CLI A/B aggregator for exit/sizing replay"
```

---

## Self-Review

- **Spec coverage:** extract shared exit functions → Task 1; price reader → Task 2; simulator (old/new, regime, intraday rule) → Task 3; CLI A/B aggregator → Task 4. Sizing-A/B note: `suggest_size` is available for a dollar-PnL extension; this plan reports R-multiples (size-independent) which is the primary comparison — dollar PnL via `suggest_size` is a follow-up, called out here so the reviewer does not expect it. ✓
- **Placeholder scan:** all steps carry runnable code + commands; the one storage-schema dependency (Task 2 Step 3) names the file to read and a STOP condition. ✓
- **Type consistency:** `simulate_trade(trade, entry_bars, forward_bars, *, mode, exit_cfg, regime_cfg)` defined in Task 3 and called identically in Task 4; `aggregate(results)` keys match the test; `load_daily_bars(market_db_path, symbol)` consistent across Tasks 2 and 4; `exit_eval.*` names consistent between Task 1 and Task 3. ✓
</content>
