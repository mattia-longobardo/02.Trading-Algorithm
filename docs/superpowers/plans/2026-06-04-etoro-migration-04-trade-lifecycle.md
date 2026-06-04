# eToro Migration — Plan 4: Trade Lifecycle Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `TradeManager`'s broker interaction to eToro's model: client-side emulated limit entry (store PENDING with a target, poll the rate each monitor tick, fire a market open by USD amount when price touches, with eToro-native fixed SL/TP as a backstop), activation from the eToro position, runtime-managed exit via `close_position_market(positionId)` confirmed by the position disappearing.

**Architecture:** The trade-lifecycle *decision* logic (HWM, trailing TP with activation% + min-profit floor, trailing stop, static TP/SL, GPT batch/ranking) is pure and stays unchanged. Only the **broker-interaction** seams change. eToro maps onto what was Alpaca's "crypto + script-protection" path, generalized to every trade. Key differences from the Alpaca code being replaced: no broker order rests at signal time (the limit is emulated in `sync_pending_trade`); positions are plain dicts (`position["units"]`, `position["open_rate"]`) not objects; exit confirmation is "position gone" not an order-status poll. This is a **full replacement** of the Alpaca order semantics — the Alpaca client loses these call sites and the Alpaca-coupled `test_trade_manager_orders.py` is replaced by eToro tests. Alpaca code/deps are deleted in Plan 5.

**Tech Stack:** Python 3.11+, `unittest` in Docker (`docker run --rm -v <worktree>/backend:/app -w /app trading-backend:test python -m unittest …`).

**Depends on:** Plans 1–3 (EToroClient: `open_market_position`, `close_position_market`, `get_open_position`→dict, `get_latest_price`/`get_latest_quote`, `instrument_id_for_symbol`).

**EToroClient methods this plan calls (all built in Plans 1–2):**
- `instrument_id_for_symbol(symbol) -> int | None`
- `get_open_position(symbol) -> Position dict | None` (`{position_id, instrument_id, units, open_rate, amount, is_buy, …}`)
- `get_latest_price(symbol, category) -> float`; `get_latest_quote(symbol, category) -> {bid_price, ask_price, …}`
- `open_market_position(instrument_id, symbol, amount_usd, stop_loss_rate, take_profit_rate, leverage) -> {order_id, reference_id, request_id, position_id, raw}`
- `close_position_market(position_id, units=None) -> {order_id, raw}`

**Trade DB columns added (this plan, additive via `TRADE_OPTIONAL_COLUMNS`):** `instrument_id INTEGER`, `position_id TEXT`, `order_reference_id TEXT`. The legacy `alpaca_order_id`/`client_order_id` columns stay (unused by eToro) until the Plan 5 fresh schema.

**Emulated-limit fill rule:** for a long entry, fill when `ask_price > 0 and ask_price <= target * (1 + ENTRY_MAX_CHASE_BPS/10_000)`. If unfilled and `age >= ENTRY_PENDING_CANCEL_MINUTES`, cancel the PENDING record (`ENTRY_TIMEOUT`) — a pure DB state change (no resting broker order to cancel).

---

## File Structure

| File | Responsibility |
|---|---|
| `core/db.py` (modify) | Add `instrument_id`/`position_id`/`order_reference_id` to schema + `TRADE_OPTIONAL_COLUMNS`. |
| `services/trade_manager.py` (modify) | Rewrite entry (`_save_new_trade`, `_open_trade_from_signal`), pending fill (`sync_pending_trade`, `_activate_trade_from_entry_fill`), open sync (`sync_open_trade`), exit (`_request_market_close`, `_sync_exit_order`); generalize `compute_allocated_capital`; drop the Alpaca-order-object helpers no longer used. |
| `tests/test_trade_manager_orders.py` (replace) | Replace Alpaca-coupled tests with the eToro lifecycle fake. |

---

## Task 1: Trade DB columns for eToro

**Files:**
- Modify: `core/db.py`
- Test: `tests/test_etoro_trade_schema.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_etoro_trade_schema.py`:

```python
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db import initialize_databases


class TradeSchemaTests(unittest.TestCase):
    def test_etoro_columns_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = str(Path(tmp) / "m.sqlite")
            trades = str(Path(tmp) / "t.sqlite")
            initialize_databases(market, trades)
            conn = sqlite3.connect(trades)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
            conn.close()
            self.assertIn("instrument_id", cols)
            self.assertIn("position_id", cols)
            self.assertIn("order_reference_id", cols)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_trade_schema -v`
Expected: FAIL — `instrument_id` not in columns.

- [ ] **Step 3: Add the columns**

In `core/db.py`, in the `TRADES_SCHEMA` `CREATE TABLE`, add three columns after the `exit_requested_at TEXT,` line:

```sql
    instrument_id INTEGER,
    position_id TEXT,
    order_reference_id TEXT,
```

Then add the same three to `TRADE_OPTIONAL_COLUMNS` (so existing DBs get them via `ALTER`):

```python
    "instrument_id": "INTEGER",
    "position_id": "TEXT",
    "order_reference_id": "TEXT",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_trade_schema -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/core/db.py backend/tests/test_etoro_trade_schema.py
git commit -m "feat(etoro): add instrument_id/position_id/order_reference_id trade columns"
```

---

## Task 2: Generalize allocation + eToro minimum

**Files:**
- Modify: `services/trade_manager.py`
- Test: covered by Task 6's suite (the method is exercised through `_open_trade_from_signal`); no standalone test.

`compute_allocated_capital` hardcodes `== PROVIDER_ALPACA` in its active-trade count and ignores the eToro minimum. Generalize it.

- [ ] **Step 1: Replace `compute_allocated_capital`**

In `services/trade_manager.py`, replace the method body:

```python
    def compute_allocated_capital(self, provider: str = PROVIDER_ALPACA) -> float:
        broker = self.broker(provider)
        if broker is None:
            return 0.0
        cash = broker.get_available_cash()
        slots = self.config.max_open_trades_stock + self.config.max_open_trades_crypto
        active = sum(
            1
            for t in self.get_open_or_pending_trades()
            if self._trade_provider(t) == provider
        )
        available_slots = max(slots - active, 1)
        allocated = round(cash / available_slots, 2)
        minimum = float(getattr(self.config, "etoro_min_trade_amount", 0.0) or 0.0)
        if minimum > 0 and 0 < allocated < minimum:
            if cash >= minimum:
                return minimum
        return allocated
```

- [ ] **Step 2: Commit**

```bash
git add backend/services/trade_manager.py
git commit -m "feat(etoro): generalize compute_allocated_capital per provider + min amount"
```

---

## Task 3: Emulated-limit entry (store PENDING, no broker order)

**Files:**
- Modify: `services/trade_manager.py`
- Test: `tests/test_trade_manager_etoro.py` (create — full lifecycle fake; grows across Tasks 3–5)

- [ ] **Step 1: Write the failing test**

Create `tests/test_trade_manager_etoro.py`:

```python
import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

for name, attr in (("clients.alpaca_client", "AlpacaClient"), ("clients.gpt_client", "GPTClient")):
    stub = ModuleType(name)
    setattr(stub, attr, object)
    sys.modules.setdefault(name, stub)
dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases
from core.utils import AppConfig, PROVIDER_ETORO
from services.trade_manager import TradeManager


def make_config(trades_db, market_db):
    return AppConfig(
        openai_api_key="k", alpaca_api_key="", alpaca_secret_key="", alpaca_base_url="x",
        etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo",
        db_trades=trades_db, db_market_data=market_db,
        crypto_entry_max_chase_bps=40, crypto_pending_cancel_minutes=12,
    )


class EtoroLifecycleBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        initialize_databases(self.market_db, self.trades_db)
        self.config = make_config(self.trades_db, self.market_db)
        self.broker = Mock()
        self.broker.instrument_id_for_symbol.return_value = 101
        self.broker.get_open_position.return_value = None
        self.broker.get_available_cash.return_value = 1000.0
        self.data_manager = Mock()
        self.gpt = Mock()
        self.manager = TradeManager(
            self.config, logging.getLogger("t"), {PROVIDER_ETORO: self.broker}, self.data_manager, self.gpt
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _rows(self, status=None):
        conn = sqlite3.connect(self.trades_db)
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM trades"
        if status:
            q += f" WHERE status = '{status}'"
        rows = [dict(r) for r in conn.execute(q)]
        conn.close()
        return rows

    def _signal(self, **over):
        s = {"action": "OPEN", "symbol": "AAPL", "entry_price": 100.0, "take_profit": 120.0,
             "stop_loss": 90.0, "trailing_take_profit_distance": None,
             "trailing_take_profit_activation_pct": None, "trailing_stop_distance": None,
             "trade_score": 80.0, "confidence": 0.9, "reasoning": "x"}
        s.update(over)
        return s


class EtoroEntryTests(EtoroLifecycleBase):
    def test_open_stores_pending_without_broker_order(self):
        ok = self.manager._open_trade_from_signal("STOCK", "AAPL", self._signal(), provider=PROVIDER_ETORO)
        self.assertTrue(ok)
        self.broker.open_market_position.assert_not_called()  # emulated — no order yet
        rows = self._rows("PENDING")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["instrument_id"], 101)
        self.assertEqual(rows[0]["target_entry_price"], 100.0)
        self.assertEqual(rows[0]["provider"], "etoro")

    def test_open_skips_when_instrument_unknown(self):
        self.broker.instrument_id_for_symbol.return_value = None
        ok = self.manager._open_trade_from_signal("STOCK", "NOPE", self._signal(symbol="NOPE"), provider=PROVIDER_ETORO)
        self.assertFalse(ok)
        self.assertEqual(self._rows(), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_trade_manager_etoro.EtoroEntryTests -v`
Expected: FAIL (current `_open_trade_from_signal` calls `place_limit_entry_order`, which the Mock auto-creates, and `_save_new_trade` expects an `order_payload` with `"order"`/`"client_order_id"` → KeyError / wrong state).

- [ ] **Step 3: Rewrite `_save_new_trade`**

In `services/trade_manager.py`, replace `_save_new_trade` with a version that stores a PENDING trade with the instrument id and a provisional entry/quantity — no broker order:

```python
    def _save_new_trade(
        self,
        category: str,
        symbol: str,
        signal: dict[str, Any],
        instrument_id: int,
        allocated_capital: float,
        provider: str = PROVIDER_ALPACA,
    ) -> None:
        trailing_take_profit_distance = self._as_float(signal.get("trailing_take_profit_distance"))
        trailing_take_profit_activation_pct = self._as_float(signal.get("trailing_take_profit_activation_pct"))
        trailing_stop_distance = self._as_float(signal.get("trailing_stop_distance"))
        target_entry_price = float(signal["entry_price"])
        provisional_quantity = (allocated_capital / target_entry_price) if target_entry_price > 0 else 0.0
        account_currency = self.config.provider_account_currency(provider)
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                INSERT INTO trades (
                    symbol, category, direction, status, entry_price, target_entry_price, quantity, allocated_capital,
                    take_profit, trailing_take_profit_distance, trailing_take_profit_activation_pct,
                    stop_loss, trailing_stop_distance,
                    instrument_id, reasoning, confidence, trade_score,
                    provider, account_currency
                ) VALUES (?, ?, 'LONG', 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    category,
                    target_entry_price,
                    target_entry_price,
                    provisional_quantity,
                    allocated_capital,
                    float(signal["take_profit"]),
                    trailing_take_profit_distance,
                    trailing_take_profit_activation_pct,
                    float(signal["stop_loss"]),
                    trailing_stop_distance,
                    int(instrument_id),
                    signal.get("reasoning"),
                    signal.get("confidence"),
                    self._as_float(signal.get("trade_score")),
                    provider,
                    account_currency,
                ),
            )
        self.logger.info("Stored new pending (emulated-limit) trade for %s on %s", symbol, provider)
```

- [ ] **Step 4: Rewrite `_open_trade_from_signal`**

Replace the order-placement portion (from `allocated_capital = …` to `return True`) so it resolves the instrument and stores PENDING without placing an order:

```python
        allocated_capital = self.compute_allocated_capital(provider=provider)
        if allocated_capital <= 0:
            self.logger.warning("Skipping %s because allocated capital is zero", symbol)
            return False
        instrument_id = broker.instrument_id_for_symbol(symbol)
        if instrument_id is None:
            self.logger.warning("Skipping %s because it is not a tradable %s instrument", symbol, provider)
            return False
        self._save_new_trade(category, symbol, signal, instrument_id, allocated_capital, provider=provider)
        return True
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_trade_manager_etoro.EtoroEntryTests -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_etoro.py
git commit -m "feat(etoro): emulated-limit entry stores PENDING without a broker order"
```

---

## Task 4: Pending fill — poll rate, market open, activate

**Files:**
- Modify: `services/trade_manager.py`
- Test: `tests/test_trade_manager_etoro.py` (append `EtoroPendingTests`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_manager_etoro.py`:

```python
class EtoroPendingTests(EtoroLifecycleBase):
    def _pending(self, target=100.0):
        self.manager._save_new_trade("STOCK", "AAPL", self._signal(entry_price=target), 101, 200.0, provider=PROVIDER_ETORO)
        return self._rows("PENDING")[0]

    def test_fill_when_price_touches_target(self):
        trade = self._pending(target=100.0)
        self.broker.get_latest_quote.return_value = {"ask_price": 100.0, "bid_price": 99.9}
        self.broker.open_market_position.return_value = {
            "order_id": "o1", "reference_id": "r1", "request_id": "req1", "position_id": "p1", "raw": {}}
        self.broker.get_open_position.return_value = {
            "position_id": "p1", "instrument_id": 101, "units": 2.0, "open_rate": 100.0,
            "amount": 200.0, "is_buy": True}
        self.broker.get_latest_price.return_value = 101.0
        self.manager.sync_pending_trade(trade)
        self.broker.open_market_position.assert_called_once()
        kwargs = self.broker.open_market_position.call_args.kwargs
        self.assertEqual(kwargs["amount_usd"], 200.0)
        self.assertEqual(kwargs["stop_loss_rate"], 90.0)
        self.assertEqual(kwargs["take_profit_rate"], 120.0)
        self.assertEqual(kwargs["leverage"], 1)
        row = self._rows("OPEN")[0]
        self.assertEqual(row["position_id"], "p1")
        self.assertEqual(row["quantity"], 2.0)
        self.assertEqual(row["entry_price"], 100.0)

    def test_no_fill_when_price_above_chase(self):
        trade = self._pending(target=100.0)
        self.broker.get_latest_quote.return_value = {"ask_price": 105.0, "bid_price": 104.9}  # > 0.4% chase
        self.manager.sync_pending_trade(trade)
        self.broker.open_market_position.assert_not_called()
        self.assertEqual(len(self._rows("PENDING")), 1)

    def test_timeout_cancels_pending(self):
        trade = self._pending(target=100.0)
        # backdate created_at beyond the cancel window
        conn = sqlite3.connect(self.trades_db)
        conn.execute("UPDATE trades SET created_at = datetime('now','-1 day') WHERE id = ?", (trade["id"],))
        conn.commit(); conn.close()
        trade = self._rows("PENDING")[0]
        self.broker.get_latest_quote.return_value = {"ask_price": 105.0, "bid_price": 104.9}
        self.manager.sync_pending_trade(trade)
        self.broker.open_market_position.assert_not_called()
        self.assertEqual(self._rows("CANCELLED")[0]["close_reason"], "ENTRY_TIMEOUT")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_trade_manager_etoro.EtoroPendingTests -v`
Expected: FAIL (current `sync_pending_trade` uses `alpaca_order_id`/`get_order`/Alpaca status flow).

- [ ] **Step 3: Add the fill helper and rewrite `sync_pending_trade`**

In `services/trade_manager.py`, replace `sync_pending_trade` and `_activate_trade_from_entry_fill` with eToro versions, and add `_pending_age_minutes`:

```python
    def _entry_fill_ceiling(self, target_entry_price: float) -> float:
        return target_entry_price * (1 + (int(self.config.crypto_entry_max_chase_bps) / 10_000.0))

    def sync_pending_trade(self, trade: dict[str, Any]) -> None:
        broker = self._trade_broker(trade)
        if broker is None:
            return

        # If a position already exists for this symbol (filled on a prior tick
        # before activation completed), activate from it.
        existing = broker.get_open_position(trade["symbol"])
        if existing is not None:
            self._activate_trade_from_position(trade, existing, None)
            return

        target = self._as_float(trade.get("target_entry_price")) or self._as_float(trade.get("entry_price"))
        if target is None or target <= 0:
            return

        age_minutes = self._minutes_since(parse_datetime(trade.get("created_at"))) or 0.0
        if age_minutes >= int(self.config.crypto_pending_cancel_minutes):
            self._cancel_pending_trade_record(trade, "ENTRY_TIMEOUT")
            self.logger.info("Cancelled pending trade %s after %s min without touching target", trade["id"], round(age_minutes, 1))
            return

        try:
            quote = broker.get_latest_quote(str(trade["symbol"]), str(trade["category"]))
        except Exception:
            self.logger.warning("Could not fetch quote for pending trade %s", trade["id"], exc_info=True)
            return
        ask = self._as_float(quote.get("ask_price")) or self._as_float(quote.get("bid_price"))
        if ask is None or ask <= 0:
            return
        if ask > self._entry_fill_ceiling(target):
            return  # wait for price to come down to the limit

        instrument_id = int(trade.get("instrument_id") or 0) or broker.instrument_id_for_symbol(trade["symbol"])
        if not instrument_id:
            self._cancel_pending_trade_record(trade, "INSTRUMENT_UNRESOLVED")
            return
        try:
            result = broker.open_market_position(
                instrument_id=int(instrument_id),
                symbol=str(trade["symbol"]),
                amount_usd=float(trade["allocated_capital"]),
                stop_loss_rate=float(trade["stop_loss"]),
                take_profit_rate=float(trade["take_profit"]),
                leverage=int(getattr(self.config, "etoro_default_leverage", 1) or 1),
            )
        except Exception:
            self.logger.exception("Market open failed for pending trade %s; cancelling", trade["id"])
            self._cancel_pending_trade_record(trade, "ENTRY_FAILED")
            return

        position = broker.get_open_position(trade["symbol"])
        self._activate_trade_from_position(trade, position, result)

    def _activate_trade_from_position(self, trade: dict[str, Any], position: Any, open_result: dict[str, Any] | None) -> None:
        target = self._as_float(trade.get("target_entry_price")) or self._as_float(trade.get("entry_price")) or 0.0
        pos = position if isinstance(position, dict) else {}
        entry_price = self._as_float(pos.get("open_rate")) or target or float(trade["entry_price"])
        quantity = self._as_float(pos.get("units")) or float(trade["quantity"])
        position_id = str(pos.get("position_id") or (open_result or {}).get("position_id") or "") or None
        reference_id = str((open_result or {}).get("reference_id") or (open_result or {}).get("request_id") or "") or None

        current_price = self._resolve_current_price(
            trade["symbol"], trade["category"], position=None, fallback=entry_price,
            provider=self._trade_provider(trade),
        )
        high_water_mark = max(self._as_float(trade.get("high_water_mark")) or entry_price, entry_price, current_price)
        trailing_stop_price = self._compute_trailing_stop_price(
            high_water_mark, self._as_float(trade.get("trailing_stop_distance")))
        trailing_take_profit_price = self._compute_trailing_take_profit_price(
            high_water_mark, entry_price,
            self._as_float(trade.get("trailing_take_profit_distance")),
            self._as_float(trade.get("trailing_take_profit_activation_pct")),
            self.config.trailing_tp_min_profit_buffer_pct,
        )
        pnl = (current_price - entry_price) * quantity
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET status = 'OPEN', open_timestamp = ?, entry_price = ?, quantity = ?, current_price = ?, pnl = ?,
                    high_water_mark = ?, trailing_take_profit_price = ?, trailing_stop_price = ?,
                    position_id = ?, order_reference_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    isoformat_utc(utc_now()), entry_price, quantity, current_price, pnl,
                    high_water_mark, trailing_take_profit_price, trailing_stop_price,
                    position_id, reference_id, trade["id"],
                ),
            )
        self.logger.info("Trade %s opened on eToro (position %s)", trade["id"], position_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_trade_manager_etoro.EtoroPendingTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_etoro.py
git commit -m "feat(etoro): fill emulated-limit entries via market open + activate from position"
```

---

## Task 5: Open sync + exit on eToro

**Files:**
- Modify: `services/trade_manager.py`
- Test: `tests/test_trade_manager_etoro.py` (append `EtoroExitTests`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trade_manager_etoro.py`:

```python
class EtoroExitTests(EtoroLifecycleBase):
    def _open_trade(self, **over):
        self.manager._save_new_trade("STOCK", "AAPL", self._signal(**over), 101, 200.0, provider=PROVIDER_ETORO)
        t = self._rows("PENDING")[0]
        pos = {"position_id": "p1", "instrument_id": 101, "units": 2.0, "open_rate": 100.0, "amount": 200.0, "is_buy": True}
        self.broker.get_latest_price.return_value = 100.0
        self.manager._activate_trade_from_position(t, pos, {"position_id": "p1", "reference_id": "r1"})
        return self._rows("OPEN")[0]

    def test_take_profit_triggers_close_by_position_id(self):
        trade = self._open_trade(take_profit=120.0)
        self.broker.get_open_position.return_value = {
            "position_id": "p1", "instrument_id": 101, "units": 2.0, "open_rate": 100.0, "amount": 200.0, "is_buy": True}
        self.broker.get_latest_price.return_value = 125.0  # above TP
        self.broker.close_position_market.return_value = {"order_id": "c1", "raw": {}}
        # after close request, position disappears
        def _after_close(*a, **k):
            self.broker.get_open_position.return_value = None
            return {"order_id": "c1", "raw": {}}
        self.broker.close_position_market.side_effect = _after_close
        self.manager.sync_open_trade(trade)
        self.broker.close_position_market.assert_called_once_with("p1")
        closed = self._rows("CLOSED")[0]
        self.assertEqual(closed["close_reason"], "TAKE_PROFIT")

    def test_position_vanished_closes_trade(self):
        trade = self._open_trade()
        self.broker.get_open_position.return_value = None
        self.manager.sync_open_trade(trade)
        self.assertEqual(len(self._rows("CLOSED")), 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_trade_manager_etoro.EtoroExitTests -v`
Expected: FAIL (current `sync_open_trade` uses `getattr(position, "qty")`; `_request_market_close` calls `close_position_market(symbol)` and `_sync_exit_order` polls `get_order`).

- [ ] **Step 3: Rewrite `sync_open_trade`, `_request_market_close`, `_sync_exit_order`**

In `services/trade_manager.py`, replace `sync_open_trade` so it reads the position dict:

```python
    def sync_open_trade(self, trade: dict[str, Any]) -> None:
        if trade.get("exit_order_id"):
            self._sync_exit_order(trade)
            return

        broker = self._trade_broker(trade)
        if broker is None:
            return
        position = broker.get_open_position(trade["symbol"])
        if position is None:
            self._close_trade_without_position(trade)
            return

        quantity = self._as_float(position.get("units")) or float(trade["quantity"])
        current_price = self._resolve_current_price(
            trade["symbol"], trade["category"], position=None,
            fallback=float(trade.get("current_price") or trade["entry_price"]),
            provider=self._trade_provider(trade),
        )
        entry_price = float(trade["entry_price"])
        stop_loss = self._as_float(trade.get("stop_loss"))
        take_profit = self._as_float(trade.get("take_profit"))
        trailing_take_profit_distance = self._as_float(trade.get("trailing_take_profit_distance"))
        trailing_take_profit_activation_pct = self._as_float(trade.get("trailing_take_profit_activation_pct"))
        high_water_mark = max(self._as_float(trade.get("high_water_mark")) or entry_price, current_price)
        trailing_take_profit_price = self._compute_trailing_take_profit_price(
            high_water_mark, entry_price, trailing_take_profit_distance,
            trailing_take_profit_activation_pct, self.config.trailing_tp_min_profit_buffer_pct,
        )
        trailing_stop_price = self._compute_trailing_stop_price(
            high_water_mark, self._as_float(trade.get("trailing_stop_distance")))
        pnl = (current_price - entry_price) * quantity

        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET quantity = ?, current_price = ?, pnl = ?, high_water_mark = ?, trailing_take_profit_price = ?,
                    trailing_stop_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (quantity, current_price, pnl, high_water_mark, trailing_take_profit_price, trailing_stop_price, trade["id"]),
            )

        close_reason = self._trailing_take_profit_close_reason(current_price, trailing_take_profit_price)
        if close_reason:
            self._request_market_close(trade, close_reason, current_price)
            return
        if take_profit is not None and trailing_take_profit_price is None and current_price >= take_profit:
            self._request_market_close(trade, "TAKE_PROFIT", current_price)
            return
        close_reason = self._downside_close_reason(current_price, stop_loss, trailing_stop_price)
        if close_reason:
            self._request_market_close(trade, close_reason, current_price)
```

Replace `_request_market_close` so it closes by position id:

```python
    def _request_market_close(self, trade: dict[str, Any], close_reason: str, trigger_price: float) -> None:
        if trade.get("exit_order_id"):
            return
        broker = self._trade_broker(trade)
        position_id = trade.get("position_id")
        if broker is None or not position_id:
            self._mark_trade_closed(trade, close_reason, trigger_price)
            return
        try:
            order = broker.close_position_market(str(position_id))
        except Exception as exc:
            message = str(exc).lower()
            if "position" in message and ("not" in message or "exist" in message):
                self._mark_trade_closed(trade, close_reason, trigger_price)
                return
            raise
        order_id = str((order or {}).get("order_id") or "") or None
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET exit_order_id = ?, exit_requested_at = ?, pending_close_reason = ?, current_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (order_id, isoformat_utc(utc_now()), close_reason, trigger_price, trade["id"]),
            )
        refreshed_trade = self.get_trade(trade["id"]) or trade
        self._sync_exit_order(refreshed_trade)
```

Replace `_sync_exit_order` so it confirms via the position disappearing:

```python
    def _sync_exit_order(self, trade: dict[str, Any]) -> None:
        if not trade.get("exit_order_id"):
            return
        broker = self._trade_broker(trade)
        if broker is None:
            return
        position = broker.get_open_position(trade["symbol"])
        if position is None:
            close_price = self._as_float(trade.get("current_price")) or float(trade["entry_price"])
            self._mark_trade_closed(
                trade, str(trade.get("pending_close_reason") or "MARKET_EXIT"), close_price)
            return
        # Position still present: the market close is in flight; retry next tick.
        self.logger.debug("Exit for trade %s still pending (position open)", trade["id"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_trade_manager_etoro.EtoroExitTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the whole eToro lifecycle suite**

Run: `cd backend && python3 -m unittest tests.test_trade_manager_etoro -v`
Expected: PASS (all classes).

- [ ] **Step 6: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_etoro.py
git commit -m "feat(etoro): runtime exit closes by positionId, confirmed by position gone"
```

---

## Task 6: Retire the Alpaca-coupled trade tests + dead helpers

**Files:**
- Delete: `tests/test_trade_manager_orders.py`
- Modify: `services/trade_manager.py` (remove now-unused Alpaca-order helpers)

The replaced lifecycle no longer uses `_update_pending_trade_submission`, `_refresh_live_crypto_pending_trade`, `_fetch_trade_order`, `_activate_trade_from_entry_fill`, `_order_status`, `_order_timestamp`, or the `FILLED_ENTRY_STATUSES`/`LIVE_PENDING_ENTRY_STATUSES`/`TERMINAL_PENDING_STATUSES` constants. Removing them keeps the module honest. `test_trade_manager_orders.py` tests the deleted Alpaca semantics and is superseded by `test_trade_manager_etoro.py`.

- [ ] **Step 1: Delete the superseded test file**

```bash
git rm backend/tests/test_trade_manager_orders.py
```

- [ ] **Step 2: Remove dead Alpaca-order helpers**

In `services/trade_manager.py`, delete these now-unused methods and constants (verify each has no remaining caller with `grep -n <name> services/trade_manager.py` first): `_update_pending_trade_submission`, `_refresh_live_crypto_pending_trade`, `_max_acceptable_crypto_entry_price`, `_max_acceptable_crypto_entry_price_for`, `_pending_reprice_minutes`, `_cancel_broker_order`, `_fetch_trade_order`, `_activate_trade_from_entry_fill`, `_order_status`, `_order_timestamp`, and the `TERMINAL_PENDING_STATUSES`/`FILLED_ENTRY_STATUSES`/`LIVE_PENDING_ENTRY_STATUSES` class attributes. Keep `_pending_cancel_minutes` (used by the emulated entry) — wait, the rewrite reads `self.config.crypto_pending_cancel_minutes` directly, so `_pending_cancel_minutes` is also unused; remove it too. Keep `review_stale_pending_trades` / `_review_single_stale_pending_trade` but change their `trade.get("alpaca_order_id")` cancel branch to a pure record cancel:

In `_review_single_stale_pending_trade`, replace the block:

```python
        order_id = trade.get("alpaca_order_id")
        if order_id:
            self._cancel_broker_order(trade, str(order_id))

        self._cancel_pending_trade_record(
```

with:

```python
        self._cancel_pending_trade_record(
```

- [ ] **Step 3: Verify no dangling references**

Run:
```bash
cd backend && grep -nE "alpaca_order_id|place_limit_entry_order|_fetch_trade_order|_activate_trade_from_entry_fill|_refresh_live_crypto_pending_trade|_cancel_broker_order|FILLED_ENTRY_STATUSES|_order_status\b" services/trade_manager.py || echo "clean"
```
Expected: `clean` (no matches).

- [ ] **Step 4: Full suite in Docker**

Run:
```bash
docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest discover -s tests 2>&1 | tail -8
```
Expected: **OK** — the 4 pre-existing failures + 1 error are gone (their file was removed and the lifecycle is now correct); all eToro suites pass.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(etoro): retire Alpaca order helpers and superseded trade tests"
```

---

## Self-Review (completed during planning)

- **Spec coverage (Plan 4 scope):** emulated-limit entry storing PENDING with no resting order (§5.3) — Task 3 ✓; poll-and-fire-market-open on touch with leverage=1 + fixed SL/TP backstop (§5.3) — Task 4 ✓; activation from the eToro position read-back (§5.3) — Task 4 ✓; runtime exit via `close_position_market(positionId)` confirmed by position-gone (§5.4) — Task 5 ✓; per-provider allocation + eToro minimum (§5.5) — Task 2 ✓; `instrument_id`/`position_id`/`order_reference_id` columns (§5.6) — Task 1 ✓; unchanged trailing TP (activation% + min-profit floor) / trailing stop / static TP-SL decision logic reused (§5.4, §6) ✓.
- **Deferred (by design):** Alpaca client/dep/env removal and the *fresh* DB schema (dropping `alpaca_*` columns) → Plan 5 cutover; demo-account integration → Plan 5.
- **Behavioural note (logged, not silent):** emulated entry fills at most once per monitor tick (≤1 min latency) and only while a quote is available — acceptable and matches the design; timeouts and failures are logged with explicit reasons (`ENTRY_TIMEOUT`/`ENTRY_FAILED`/`INSTRUMENT_UNRESOLVED`).
- **Placeholder scan:** none.
- **Type consistency:** positions are dicts everywhere now (`position.get("units"/"open_rate"/"position_id")`); `_save_new_trade(category, symbol, signal, instrument_id, allocated_capital, provider)` signature matches its single caller in `_open_trade_from_signal`; `open_market_position(instrument_id, symbol, amount_usd, stop_loss_rate, take_profit_rate, leverage)` matches the Plan 1 client signature; `close_position_market(position_id)` matches Plan 1. `_resolve_current_price` is called with `position=None` (it no longer reads `.current_price` off a dict — the fallback path supplies the price), preserving its broker-price-first behaviour.
