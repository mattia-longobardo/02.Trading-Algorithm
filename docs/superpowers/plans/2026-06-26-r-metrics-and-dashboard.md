# R Metrics Persistence + Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist per-trade R metrics (planned risk, planned reward/risk, realized R, MAE, MFE) and surface aggregate "captured R" plus per-trade R columns in the dashboard.

**Architecture:** Idempotent additive DB columns; population at open / during monitoring / at close using pure helpers in `services/trade_analytics.py`; two new aggregate metrics in `metrics_service`; one KPI card and four trades-table columns in the Next.js frontend.

**Tech Stack:** Python 3.14 + stdlib `unittest` (backend), Next.js 15 + TypeScript + TanStack Query (frontend). Backend full suite in the `trading-backend` container; pure modules locally via `python3 -m unittest`. Frontend: `cd frontend && npm run build` / `npm run lint`.

## Global Constraints

- DB changes use the idempotent pattern: add entries to `TRADE_OPTIONAL_COLUMNS` in `core/db.py:77` (PRAGMA-checked `ALTER TABLE ADD COLUMN` at line 210-220, run by `initialize_databases`). Never a destructive migration. Existing rows get NULL for new columns.
- New per-trade columns: `planned_risk_per_unit REAL`, `planned_reward_risk REAL`, `realized_r REAL`, `low_water_mark REAL`, `mae REAL`, `mfe REAL`. MAE/MFE are stored as **R-multiples**.
- `metrics_service.list_trades` does `SELECT * FROM trades` (line 176), so new columns reach the API automatically; the frontend `Trade` type must be extended to read them.
- The bot is LONG-only; `risk = entry − stop > 0` is now enforced at the entry gate (robustness plan). R helpers still return `None`/`0.0` defensively when `risk <= 0`.
- Existing pure helpers live in `services/trade_analytics.py` (`planned_metrics`, `realized_r`).

---

### Task 1: Add the six R columns (idempotent migration)

**Files:**
- Modify: `backend/core/db.py` — `TRADE_OPTIONAL_COLUMNS` (line 77).
- Test: `backend/tests/test_data_manager.py` or a new `backend/tests/test_db_migration.py`.

**Interfaces:**
- Produces: after `initialize_databases`, the `trades` table has columns `planned_risk_per_unit, planned_reward_risk, realized_r, low_water_mark, mae, mfe` (all REAL, nullable).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_db_migration.py
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases


class RColumnsMigrationTests(unittest.TestCase):
    def test_r_columns_exist_after_init(self):
        with tempfile.TemporaryDirectory() as d:
            market = str(Path(d) / "m.sqlite")
            trades = str(Path(d) / "t.sqlite")
            initialize_databases(market, trades)
            cols = {r[1] for r in sqlite3.connect(trades).execute("PRAGMA table_info(trades)")}
            for c in ("planned_risk_per_unit", "planned_reward_risk", "realized_r",
                      "low_water_mark", "mae", "mfe"):
                self.assertIn(c, cols)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify it fails**

Run (container): `python -m pytest tests/test_db_migration.py -v`
Expected: FAIL — the six columns are missing.

- [ ] **Step 3: Add the columns**

In `backend/core/db.py`, add to `TRADE_OPTIONAL_COLUMNS` (before the closing brace at line 96):

```python
    "planned_risk_per_unit": "REAL",
    "planned_reward_risk": "REAL",
    "realized_r": "REAL",
    "low_water_mark": "REAL",
    "mae": "REAL",
    "mfe": "REAL",
```

- [ ] **Step 4: Run to verify it passes**

Run (container): `python -m pytest tests/test_db_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/core/db.py backend/tests/test_db_migration.py
git commit -m "feat(trading): add R-metric columns to trades table (idempotent migration)"
```

---

### Task 2: Pure `excursion_r` helper

**Files:**
- Modify: `backend/services/trade_analytics.py`
- Test: `backend/tests/test_trade_analytics.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `trade_analytics.excursion_r(entry_price: float, stop_loss: float, water_mark: float) -> float | None` → `(water_mark − entry)/(entry − stop)`, `None` when `entry <= stop` or `entry <= 0`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_trade_analytics.py`:

```python
class ExcursionRTests(unittest.TestCase):
    def test_favorable_excursion_positive_r(self):
        from services.trade_analytics import excursion_r
        # entry 100, stop 90 -> R=10. high water 115 -> +1.5R
        self.assertAlmostEqual(excursion_r(100.0, 90.0, 115.0), 1.5, places=6)

    def test_adverse_excursion_negative_r(self):
        from services.trade_analytics import excursion_r
        # low water 95 -> -0.5R
        self.assertAlmostEqual(excursion_r(100.0, 90.0, 95.0), -0.5, places=6)

    def test_invalid_long_none(self):
        from services.trade_analytics import excursion_r
        self.assertIsNone(excursion_r(100.0, 100.0, 110.0))
```

- [ ] **Step 2: Run to verify it fails**

Run (locally): `cd backend && python3 -m unittest tests.test_trade_analytics -k Excursion -v`
Expected: FAIL — `excursion_r` not defined.

- [ ] **Step 3: Implement**

Append to `backend/services/trade_analytics.py`:

```python
def excursion_r(entry_price: float, stop_loss: float, water_mark: float) -> float | None:
    """Excursion from entry to a high/low water mark, in R-multiples.

    Positive for a favorable mark (MFE), negative for an adverse one (MAE).
    None when not a valid long (entry <= stop or entry <= 0).
    """
    risk = entry_price - stop_loss
    if entry_price <= 0 or risk <= 0:
        return None
    return (water_mark - entry_price) / risk
```

- [ ] **Step 4: Run to verify it passes**

Run (locally): `cd backend && python3 -m unittest tests.test_trade_analytics -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/trade_analytics.py backend/tests/test_trade_analytics.py
git commit -m "feat(trading): add excursion_r helper for MAE/MFE in R-multiples"
```

---

### Task 3: Populate R metrics at open, during monitoring, and at close

**Files:**
- Modify: `backend/services/trade_manager.py` — `_save_new_trade` (line 543; add planned_* to the INSERT), the two open-trade monitor update sites that write `high_water_mark` (lines ~1002 and ~1374; also track `low_water_mark`), and `_mark_trade_closed` (line 1123; write realized_r/mae/mfe).
- Test: `backend/tests/test_trade_manager_orders.py` (or a focused new test) + the existing close tests.

**Interfaces:**
- Consumes: `trade_analytics.planned_metrics`, `trade_analytics.realized_r`, `trade_analytics.excursion_r` (Task 2).
- Produces: persisted `planned_risk_per_unit`, `planned_reward_risk` at open; `low_water_mark` maintained while open; `realized_r`, `mae`, `mfe` at close.

- [ ] **Step 1: Write the failing test**

Add a test that opens a trade and asserts planned_* are persisted, and (simulating a close) asserts realized_r is persisted. Model it on the existing `_save_new_trade` / close tests in `test_trade_manager_orders.py` (read that file first for the manager fixture). Example shape:

```python
def test_open_persists_planned_r(self):
    # build a signal entry=100, stop=90, tp=130 and open it
    self.manager._save_new_trade("CRYPTO", "AAA", self._signal(entry_price=100.0, stop_loss=90.0, take_profit=130.0), instrument_id=1, allocated_capital=1000.0)
    row = fetch_one(self.manager.config.db_trades, "SELECT planned_risk_per_unit, planned_reward_risk FROM trades WHERE symbol='AAA'", ())
    self.assertAlmostEqual(row["planned_risk_per_unit"], 10.0, places=6)
    self.assertAlmostEqual(row["planned_reward_risk"], 3.0, places=6)
```

(Use the file's existing import of `fetch_one`/db helpers and its `_signal` helper; adapt names to the file.)

- [ ] **Step 2: Run to verify it fails**

Run (container): `python -m pytest tests/test_trade_manager_orders.py -k persists_planned_r -v`
Expected: FAIL — columns are NULL (not populated).

- [ ] **Step 3a: Populate planned_* at open**

In `_save_new_trade` (line 543), after the existing exit-level normalization block and before the INSERT, compute planned metrics and include them in the INSERT column list + values tuple:

```python
        from services.trade_analytics import planned_metrics
        _pm = planned_metrics(target_entry_price, float(signal["stop_loss"]), take_profit)
```

Add `planned_risk_per_unit, planned_reward_risk` to the INSERT column list and `_pm["risk_per_unit"], _pm["reward_risk"]` to the VALUES tuple (extend the `?` placeholders to match). Keep the column/placeholder counts consistent.

- [ ] **Step 3b: Track low_water_mark during monitoring**

At each site that updates `high_water_mark` for an OPEN trade (lines ~1002 and ~1374), add a parallel `low_water_mark`:

```python
        low_water_mark = min(self._as_float(trade.get("low_water_mark")) or entry_price, entry_price, current_price)
```

and add `low_water_mark = ?` to that site's `UPDATE ... SET ...` SQL and its parameter tuple (mirroring how `high_water_mark` is written there).

- [ ] **Step 3c: Persist realized_r / mae / mfe at close**

In `_mark_trade_closed` (line 1123), after `actual` resolution and before the UPDATE, compute:

```python
        from services.trade_analytics import realized_r, excursion_r
        _entry = float(trade["entry_price"])
        _stop = self._as_float(trade.get("stop_loss"))
        _rr = realized_r(_entry, _stop, float(close_price)) if _stop is not None else None
        _hwm = self._as_float(trade.get("high_water_mark"))
        _lwm = self._as_float(trade.get("low_water_mark"))
        _mfe = excursion_r(_entry, _stop, _hwm) if (_stop is not None and _hwm is not None) else None
        _mae = excursion_r(_entry, _stop, _lwm) if (_stop is not None and _lwm is not None) else None
```

Add `realized_r = ?, mae = ?, mfe = ?` to the close UPDATE `SET` clause and `_rr, _mae, _mfe` to its parameter tuple.

- [ ] **Step 4: Run to verify it passes + close tests**

Run (container): `python -m pytest tests/test_trade_manager_orders.py tests/test_close_resolution.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_orders.py
git commit -m "feat(trading): persist planned R at open, low-water-mark while open, realized R/MAE/MFE at close"
```

---

### Task 4: Aggregate metrics `avg_captured_r` and `avg_planned_rr`

**Files:**
- Modify: `backend/services/metrics_service.py` — `compute_metrics` (line 353; add to the return dict at line 435-459).
- Test: `backend/tests/test_metrics_account_return.py` or a focused metrics test (read an existing metrics test for the fixture).

**Interfaces:**
- Consumes: `realized_r`, `planned_reward_risk` columns on closed trades.
- Produces: `compute_metrics(...)` return dict gains `avg_captured_r` (mean realized_r over closed-in-period, non-null) and `avg_planned_rr` (mean planned_reward_risk, non-null); both `0.0` when no data.

- [ ] **Step 1: Write the failing test**

Add a metrics test that seeds two closed trades with `realized_r` 1.0 and 2.0 and asserts `avg_captured_r == 1.5` (model the fixture on an existing metrics test that inserts rows into a temp trades DB).

```python
    def test_avg_captured_r(self):
        # after seeding two closed trades with realized_r 1.0 and 2.0 in [window]
        m = self.service.compute_metrics(None, None)
        self.assertAlmostEqual(m["avg_captured_r"], 1.5, places=6)
```

- [ ] **Step 2: Run to verify it fails**

Run (container): `python -m pytest tests/test_metrics_account_return.py -k avg_captured_r -v`
Expected: FAIL — key absent.

- [ ] **Step 3: Compute the aggregates**

In `compute_metrics`, after `closed_in_period` is built (line 360), add:

```python
        _rs = [_safe_float(r.get("realized_r")) for r in closed_in_period]
        _rs = [v for v in _rs if v is not None]
        avg_captured_r = round(sum(_rs) / len(_rs), 4) if _rs else 0.0
        _rrs = [_safe_float(r.get("planned_reward_risk")) for r in closed_in_period]
        _rrs = [v for v in _rrs if v is not None]
        avg_planned_rr = round(sum(_rrs) / len(_rrs), 4) if _rrs else 0.0
```

Add to the return dict (near line 446):

```python
            "avg_captured_r": avg_captured_r,
            "avg_planned_rr": avg_planned_rr,
```

(Use the module's existing `_safe_float`; confirm its name by reading the file's imports/helpers.)

- [ ] **Step 4: Run to verify it passes**

Run (container): `python -m pytest tests/test_metrics_account_return.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/services/metrics_service.py backend/tests/test_metrics_account_return.py
git commit -m "feat(trading): expose avg_captured_r and avg_planned_rr in metrics"
```

---

### Task 5: Frontend — Trade type + "Captured R" KPI card

**Files:**
- Modify: `frontend/src/lib/types.ts` — extend the `Trade` type and the metrics type.
- Modify: `frontend/src/components/dashboard/kpi-strip.tsx` — add a KPI card.

**Interfaces:**
- Consumes: API `metrics` payload now has `avg_captured_r`, `avg_planned_rr`; `Trade` rows now carry `realized_r`, `planned_reward_risk`, `mae`, `mfe`.
- Produces: a "Captured R" KPI; type fields for the table task to consume.

- [ ] **Step 1: Extend the types**

In `frontend/src/lib/types.ts`, add to the `Trade` type (the optional numeric fields, matching the existing optional-field style):

```typescript
  realized_r?: number | null;
  planned_reward_risk?: number | null;
  mae?: number | null;
  mfe?: number | null;
```

And to the metrics/KPI type (find the type backing the `/api/metrics` response), add:

```typescript
  avg_captured_r?: number | null;
  avg_planned_rr?: number | null;
```

- [ ] **Step 2: Add the KPI card**

In `frontend/src/components/dashboard/kpi-strip.tsx`, add one `<Kpi>` card alongside the existing ones (match the existing card props/format; the component is defined at the top of the file). Example:

```tsx
      <Kpi
        label="Captured R"
        value={metrics?.avg_captured_r != null ? metrics.avg_captured_r.toFixed(2) + "R" : "—"}
        sub={metrics?.avg_planned_rr != null ? `planned ${metrics.avg_planned_rr.toFixed(2)}R` : undefined}
      />
```

(Match the actual `<Kpi>` prop names in this file — read the component definition first; if it uses `hint`/`caption` instead of `sub`, use that.)

- [ ] **Step 3: Verify the build**

Run: `cd frontend && npm run build`
Expected: build succeeds with no type errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/components/dashboard/kpi-strip.tsx
git commit -m "feat(frontend): add Captured R KPI and R fields on Trade type"
```

---

### Task 6: Frontend — R columns in the trades table

**Files:**
- Modify: `frontend/src/components/trades/trades-table.tsx` — add columns for planned RR, realized R, MAE (R), MFE (R).

**Interfaces:**
- Consumes: `Trade.realized_r`, `Trade.planned_reward_risk`, `Trade.mae`, `Trade.mfe` (Task 5).
- Produces: nothing.

- [ ] **Step 1: Add the column defs + cells**

In `frontend/src/components/trades/trades-table.tsx`, the `COLUMNS` array (around line 36) and the row renderer (`TradeRow`, around line 179) define the table. Add four columns following the existing pattern (header label + a cell that formats the numeric or renders "—" when null):

```tsx
  { key: "planned_reward_risk", label: "Plan RR" },
  { key: "realized_r", label: "Real R" },
  { key: "mfe", label: "MFE (R)" },
  { key: "mae", label: "MAE (R)" },
```

and in the row renderer add matching cells, e.g.:

```tsx
        <td className="num">{t.planned_reward_risk != null ? t.planned_reward_risk.toFixed(2) : "—"}</td>
        <td className="num">{t.realized_r != null ? t.realized_r.toFixed(2) : "—"}</td>
        <td className="num">{t.mfe != null ? t.mfe.toFixed(2) : "—"}</td>
        <td className="num">{t.mae != null ? t.mae.toFixed(2) : "—"}</td>
```

(Match the file's actual `COLUMNS` shape and cell/className conventions — read it first; the keys must align header order with cell order.)

- [ ] **Step 2: Verify the build + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: build + lint succeed.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/trades/trades-table.tsx
git commit -m "feat(frontend): show planned RR, realized R, MAE/MFE columns in trades table"
```

---

## Self-Review

- **Spec coverage:** six columns → Task 1; excursion helper → Task 2; populate open/monitor/close → Task 3; aggregate metrics → Task 4; KPI + types → Task 5; table columns → Task 6. ✓
- **Placeholder scan:** all code steps carry real code; frontend steps say "read first / match conventions" with concrete snippets, not vague directives. ✓
- **Type consistency:** column names (`planned_risk_per_unit, planned_reward_risk, realized_r, low_water_mark, mae, mfe`) identical across Tasks 1, 3, 4; `excursion_r(entry, stop, water_mark)` defined in Task 2 and used in Task 3; metrics keys `avg_captured_r`/`avg_planned_rr` defined in Task 4 and consumed in Task 5. ✓
</content>
