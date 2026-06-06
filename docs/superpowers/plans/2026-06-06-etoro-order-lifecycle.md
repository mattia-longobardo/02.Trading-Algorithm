# eToro Order Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the eToro trade lifecycle from the real asynchronous order status (not the 2xx submit), fix the broken position-close path, and stop the bot from marking never-confirmed trades EXTERNAL_CLOSE.

**Architecture:** `EToroClient` gains a correct order-status reader (`get_order_status`, mapped by status *name*), a fixed `close_position_market` (the dedicated market-close endpoint), and `cancel_order`. A submitted market order keeps its trade `PENDING` with a stored `order_id` until the status resolves: Filled→OPEN, WaitingForMarket→hold, Rejected/Canceled→CANCELLED. `position_confirmed` (set only when a live position is actually observed) gates EXTERNAL_CLOSE.

**Tech Stack:** Python 3.14, stdlib `unittest` + `unittest.mock`, eToro REST API, SQLite. Tests run in Docker.

---

## Conventions

**Working directory:** worktree root `/home/mattia/docker/projects/trading/.claude/worktrees/order-lifecycle` (branch `worktree-order-lifecycle`, based on `dev-2.0`).

**Test command (source-mounted; service `backend`; run from worktree root):**
```bash
docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.<module> -v
```
If a docker dir-permission error appears on data/logs/run, run once: `docker run --rm -v "$PWD/backend:/w" alpine sh -c 'mkdir -p /w/data/reports /w/logs /w/run && chmod -R 777 /w/data /w/logs /w/run'`. Intentional `Exception("no gpt")` tracebacks in some tests are expected — check the final `OK`.

**Full suite:** `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest discover -s tests -v`

**Commit cadence:** one commit per task. End every commit message with:
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

---

## File Structure

- **Modify** `backend/clients/etoro_client.py` — `open_market_position` body (`settlementType`); replace `get_order_info` with `get_order_status` (correct `status`/`positionExecutions` parsing, name-based); fix `close_position_market` (dedicated endpoint + `instrument_id`); add `cancel_order`.
- **Modify** `backend/core/db.py` — add `order_id`, `order_submitted_at`, `position_confirmed` to `TRADE_OPTIONAL_COLUMNS`.
- **Modify** `backend/core/utils.py` — add `order_await_timeout_minutes` config.
- **Modify** `backend/services/trade_manager.py` — submit-then-resolve lifecycle (`_mark_order_submitted`, `_resolve_submitted_order`, `sync_pending_trade` branch), `position_confirmed` in `_activate_trade_from_position`, `sync_open_trade` grace, and pass `instrument_id` to the close call.
- **Test** `backend/tests/test_etoro_client.py` — order status / close / cancel / open body.
- **Test** `backend/tests/test_trade_manager_orders.py` (new) — lifecycle state machine.

---

## Task 1: `open_market_position` sends `settlementType="real"`

**Files:** Modify `backend/clients/etoro_client.py`; Test `backend/tests/test_etoro_client.py`.

- [ ] **Step 1: Update the existing body test**

In `backend/tests/test_etoro_client.py`, in `test_open_market_position_builds_correct_body` (the `EToroOrderTests` class), add after the `self.assertNotIn("symbol", body)` line:
```python
        self.assertEqual(body["settlementType"], "real")
```

- [ ] **Step 2: Run, expect FAIL**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroOrderTests.test_open_market_position_builds_correct_body -v`
Expected: FAIL with `KeyError: 'settlementType'`.

- [ ] **Step 3: Add the field**

In `backend/clients/etoro_client.py`, in `open_market_position`'s `body` dict, add `"settlementType": "real",` immediately after the `"instrumentId": int(instrument_id),` line.

- [ ] **Step 4: Run, expect PASS**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroOrderTests.test_open_market_position_builds_correct_body -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "fix(etoro): send settlementType=real on open orders

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `get_order_status` (correct async status reader)

**Files:** Modify `backend/clients/etoro_client.py`; Test `backend/tests/test_etoro_client.py`.

The existing `get_order_info` parses the wrong fields (top-level `positionId`/`openRate`) and is unused. Replace it with `get_order_status` that reads `status` + `positionExecutions`, mapping by status *name*.

- [ ] **Step 1: Write the failing test**

Add to `class EToroOrderTests` in `backend/tests/test_etoro_client.py`:
```python
    def test_get_order_status_filled(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {
            "orderId": 555, "status": {"id": 3, "name": "Filled", "errorCode": 0, "errorMessage": None},
            "positionExecutions": [{"positionId": 9001, "state": "open"}],
        })
        st = client.get_order_status("555")
        self.assertTrue(st["executed"])
        self.assertFalse(st["rejected"])
        self.assertEqual(st["position_id"], "9001")
        params = session.request.call_args.kwargs["params"]
        self.assertEqual(params["orderId"], "555")
        self.assertTrue(session.request.call_args.args[1].endswith("/api/v2/trading/info/demo/orders:lookup"))

    def test_get_order_status_rejected(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {
            "orderId": 7, "status": {"id": 4, "name": "Rejected", "errorCode": 759,
                                     "errorMessage": "manual Trading is disallowed for this instrument type(10:CRYPTO)"},
            "positionExecutions": [],
        })
        st = client.get_order_status("7")
        self.assertTrue(st["rejected"])
        self.assertFalse(st["executed"])
        self.assertEqual(st["error_code"], 759)
        self.assertIn("disallowed", st["error_message"])
        self.assertIsNone(st["position_id"])

    def test_get_order_status_waiting(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {
            "orderId": 8, "status": {"id": 11, "name": "WaitingForMarket", "errorCode": 0, "errorMessage": None},
            "positionExecutions": [],
        })
        st = client.get_order_status("8")
        self.assertTrue(st["waiting"])
        self.assertFalse(st["executed"])
        self.assertFalse(st["rejected"])

    def test_get_order_status_not_found(self):
        client, session = make_client("demo")
        session.request.side_effect = EToroAPIError(404, "no operation")
        self.assertIsNone(client.get_order_status("404ref"))
```

- [ ] **Step 2: Run, expect FAIL**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroOrderTests -v`
Expected: FAIL with `AttributeError: 'EToroClient' object has no attribute 'get_order_status'`.

- [ ] **Step 3: Replace `get_order_info` with `get_order_status`**

In `backend/clients/etoro_client.py`, replace the entire `get_order_info` method with:
```python
    @staticmethod
    def _classify_order_status(name: str, status_id: int | None) -> tuple[bool, bool, bool, bool]:
        """Return (executed, waiting, rejected, canceled) from the status name.

        eToro status ids are inconsistent across asset types, so classify by the
        human-readable name and fall back to ids only when the name is unknown.
        """
        text = name.lower()
        if "fill" in text or "execut" in text:
            return True, False, False, False
        if "reject" in text:
            return False, False, True, False
        if "cancel" in text:
            return False, False, False, True
        if "wait" in text or "pending" in text:
            return False, True, False, False
        mapping = {1: (True, False, False, False), 2: (False, False, False, True),
                   3: (False, False, True, False), 4: (False, False, True, False),
                   7: (False, False, False, True), 11: (False, True, False, False)}
        return mapping.get(int(status_id) if status_id is not None else -1, (False, True, False, False))

    def get_order_status(self, order_id: str) -> dict[str, Any] | None:
        """Resolve an order's async outcome via the orders:lookup endpoint.

        Returns ``None`` when the order is not (yet) found (HTTP 404).
        """
        path = f"/api/v2/trading/info/{self._mode_segment()}orders:lookup"
        try:
            payload = self._request("GET", path, params={"orderId": str(order_id)})
        except EToroAPIError as exc:
            if exc.status_code == 404:
                return None
            raise
        status = payload.get("status") or {}
        name = str(status.get("name") or "")
        status_id = status.get("id")
        executed, waiting, rejected, canceled = self._classify_order_status(name, status_id)
        position_id = None
        for execution in payload.get("positionExecutions") or []:
            if str(execution.get("state") or "").lower() == "open" and execution.get("positionId") is not None:
                position_id = str(execution["positionId"])
                break
        return {
            "order_id": str(order_id),
            "status_name": name,
            "status_id": status_id,
            "executed": executed,
            "waiting": waiting,
            "rejected": rejected,
            "canceled": canceled,
            "error_code": status.get("errorCode"),
            "error_message": status.get("errorMessage"),
            "position_id": position_id,
        }
```

- [ ] **Step 4: Run, expect PASS**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroOrderTests -v`
Expected: PASS. (Confirm `EToroAPIError` is imported in the test file — it already is, used by other tests.)

- [ ] **Step 5: Commit**
```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): get_order_status reads async order outcome (by status name)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Fix `close_position_market` + add `cancel_order`

**Files:** Modify `backend/clients/etoro_client.py`; Test `backend/tests/test_etoro_client.py`.

- [ ] **Step 1: Write the failing test**

Replace the existing `test_close_position_market_builds_body` in `backend/tests/test_etoro_client.py` with:
```python
    def test_close_position_market_uses_market_close_endpoint(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {"orderForClose": {"orderID": 42}})
        result = client.close_position_market("p1", instrument_id=100000)
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/api/v1/trading/execution/demo/market-close-orders/positions/p1"))
        body = kwargs["json"]
        self.assertEqual(body["InstrumentID"], 100000)
        self.assertNotIn("UnitsToDeduct", body)  # full close omits it
        self.assertEqual(result["raw"]["orderForClose"]["orderID"], 42)

    def test_close_position_market_partial_sends_units(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {"orderForClose": {"orderID": 43}})
        client.close_position_market("p2", instrument_id=100000, units=0.5)
        body = session.request.call_args.kwargs["json"]
        self.assertEqual(body["UnitsToDeduct"], 0.5)

    def test_cancel_order_deletes(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {"token": "t1"})
        client.cancel_order("999")
        args, _ = session.request.call_args
        self.assertEqual(args[0], "DELETE")
        self.assertTrue(args[1].endswith("/api/v2/trading/execution/demo/orders/999"))
```

- [ ] **Step 2: Run, expect FAIL**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroOrderTests -v`
Expected: FAIL (close hits the old endpoint / `cancel_order` missing).

- [ ] **Step 3: Replace `close_position_market` and add `cancel_order`**

In `backend/clients/etoro_client.py`, replace the entire `close_position_market` method with:
```python
    def close_position_market(self, position_id: str, instrument_id: int, units: float | None = None) -> dict[str, Any]:
        """Close (or partially close) a position via the dedicated market-close endpoint.

        eToro's v2 orders endpoint does not accept ``action=close``; the correct
        path is the v1 market-close-orders endpoint, which needs the instrument id
        and (optionally) the units to deduct for a partial close.
        """
        path = f"/api/v1/trading/execution/{self._mode_segment()}market-close-orders/positions/{position_id}"
        body: dict[str, Any] = {"InstrumentID": int(instrument_id)}
        if units is not None:
            body["UnitsToDeduct"] = float(units)
        payload = self._request_with_id("POST", path, str(uuid4()), json_body=body)
        order = payload.get("orderForClose") or {}
        return {
            "order_id": str(order.get("orderID")) if order.get("orderID") is not None else None,
            "raw": payload,
        }

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an order before it executes (idempotent if already closed)."""
        path = f"/api/v2/trading/execution/{self._mode_segment()}orders/{order_id}"
        return self._request_with_id("DELETE", path, str(uuid4()))
```

- [ ] **Step 4: Run, expect PASS**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client -v`
Expected: PASS (whole client module).

- [ ] **Step 5: Commit**
```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "fix(etoro): close_position_market uses market-close endpoint; add cancel_order

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: DB columns + await-timeout config

**Files:** Modify `backend/core/db.py`, `backend/core/utils.py`; Test `backend/tests/test_etoro_config.py`.

- [ ] **Step 1: Write the failing config test**

Add to `class EtoroConfigTests` in `backend/tests/test_etoro_config.py`:
```python
    def test_order_await_timeout_default_and_env(self):
        self.assertEqual(AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b").order_await_timeout_minutes, 360)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "o", "ORDER_AWAIT_TIMEOUT_MINUTES": "30"}, clear=True):
            self.assertEqual(load_config().order_await_timeout_minutes, 30)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_config -v`
Expected: FAIL with `AttributeError: ... 'order_await_timeout_minutes'`.

- [ ] **Step 3: Add the config field + env**

In `backend/core/utils.py`, add a dataclass field to `AppConfig` immediately after the `crypto_pending_cancel_minutes: int = 12` line:
```python
    order_await_timeout_minutes: int = 360
```
And in `load_config`, immediately after the `crypto_pending_cancel_minutes=...` line:
```python
        order_await_timeout_minutes=max(1, int(os.getenv("ORDER_AWAIT_TIMEOUT_MINUTES", "360"))),
```

- [ ] **Step 4: Add the DB columns**

In `backend/core/db.py`, add three entries to the `TRADE_OPTIONAL_COLUMNS` dict (after the `"exit_requested_at": "TEXT",` entry):
```python
    "order_id": "TEXT",
    "order_submitted_at": "TEXT",
    "position_confirmed": "INTEGER NOT NULL DEFAULT 0",
```

- [ ] **Step 5: Run config test + a DB-migration smoke check**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_config tests.test_etoro_instruments_db -v`
Expected: PASS. Then verify migration adds the columns:
Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -c "import tempfile,os; from core.db import initialize_databases; d=tempfile.mkdtemp(); m=os.path.join(d,'m.sqlite'); t=os.path.join(d,'t.sqlite'); initialize_databases(m,t); import sqlite3; c=sqlite3.connect(t); cols={r[1] for r in c.execute('PRAGMA table_info(trades)')}; assert {'order_id','order_submitted_at','position_confirmed'} <= cols, cols; print('cols ok')"`
Expected: prints `cols ok`.

- [ ] **Step 6: Commit**
```bash
git add backend/core/db.py backend/core/utils.py backend/tests/test_etoro_config.py
git commit -m "feat(orders): add order_id/order_submitted_at/position_confirmed columns + await timeout

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Submit-then-resolve lifecycle in TradeManager

**Files:** Modify `backend/services/trade_manager.py`; Test `backend/tests/test_trade_manager_orders.py` (new).

Context: `sync_pending_trade` currently fires `open_market_position` then immediately calls `_activate_trade_from_position`. New flow: when fired, store `order_id`/`order_submitted_at` and stay PENDING; on subsequent ticks resolve the status. Helper `_minutes_since(parse_datetime(...))` and `_cancel_pending_trade_record(trade, reason)` already exist.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_trade_manager_orders.py`:
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


def _tm(broker):
    from services.trade_manager import TradeManager
    cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                    etoro_account_type="demo", order_await_timeout_minutes=360)
    return TradeManager(cfg, logging.getLogger("t"), {PROVIDER_ETORO: broker}, Mock(), Mock())


class ResolveSubmittedOrderTests(unittest.TestCase):
    def _trade(self, **over):
        t = {"id": 1, "symbol": "AAPL", "category": "STOCK", "status": "PENDING",
             "provider": "etoro", "order_id": "555", "order_submitted_at": "2999-01-01T00:00:00+00:00",
             "instrument_id": 9422, "entry_price": 100.0, "target_entry_price": 100.0,
             "quantity": 1.0, "allocated_capital": 100.0, "position_confirmed": 0}
        t.update(over)
        return t

    def test_executed_activates_open(self):
        broker = Mock()
        broker.get_order_status.return_value = {"executed": True, "rejected": False, "waiting": False,
                                                "canceled": False, "position_id": "9001", "error_message": None}
        broker.get_open_position.return_value = {"position_id": "9001", "units": 2.0, "open_rate": 101.0}
        tm = _tm(broker)
        captured = {}
        tm._activate_trade_from_position = lambda trade, pos, res: captured.update(pos=pos, res=res)
        tm._resolve_submitted_order(self._trade())
        self.assertIsNotNone(captured["pos"])

    def test_rejected_cancels_with_reason(self):
        broker = Mock()
        broker.get_order_status.return_value = {"executed": False, "rejected": True, "waiting": False,
                                                "canceled": False, "position_id": None,
                                                "error_message": "manual Trading is disallowed"}
        tm = _tm(broker)
        seen = {}
        tm._cancel_pending_trade_record = lambda trade, reason: seen.update(reason=reason)
        tm._resolve_submitted_order(self._trade())
        self.assertEqual(seen["reason"], "ENTRY_REJECTED")

    def test_waiting_keeps_pending(self):
        broker = Mock()
        broker.get_order_status.return_value = {"executed": False, "rejected": False, "waiting": True,
                                                "canceled": False, "position_id": None, "error_message": None}
        tm = _tm(broker)
        tm._cancel_pending_trade_record = Mock()
        tm._activate_trade_from_position = Mock()
        tm._resolve_submitted_order(self._trade())  # future submitted_at -> within timeout
        tm._cancel_pending_trade_record.assert_not_called()
        tm._activate_trade_from_position.assert_not_called()

    def test_waiting_past_timeout_cancels_order(self):
        broker = Mock()
        broker.get_order_status.return_value = {"executed": False, "rejected": False, "waiting": True,
                                                "canceled": False, "position_id": None, "error_message": None}
        tm = _tm(broker)
        seen = {}
        tm._cancel_pending_trade_record = lambda trade, reason: seen.update(reason=reason)
        tm._resolve_submitted_order(self._trade(order_submitted_at="2000-01-01T00:00:00+00:00"))
        broker.cancel_order.assert_called_once_with("555")
        self.assertEqual(seen["reason"], "ORDER_AWAIT_TIMEOUT")

    def test_status_none_is_left_alone(self):
        broker = Mock()
        broker.get_order_status.return_value = None
        tm = _tm(broker)
        tm._cancel_pending_trade_record = Mock()
        tm._activate_trade_from_position = Mock()
        tm._resolve_submitted_order(self._trade())  # future submitted_at
        tm._cancel_pending_trade_record.assert_not_called()
        tm._activate_trade_from_position.assert_not_called()
```

- [ ] **Step 2: Run, expect FAIL**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_orders -v`
Expected: FAIL with `AttributeError: ... '_resolve_submitted_order'`.

- [ ] **Step 3: Add `_resolve_submitted_order` and `_mark_order_submitted`**

In `backend/services/trade_manager.py`, add these methods to `TradeManager` (place them right after `sync_pending_trade`):
```python
    def _mark_order_submitted(self, trade: dict[str, Any], open_result: dict[str, Any] | None) -> None:
        order_id = str((open_result or {}).get("order_id") or "") or None
        if not order_id:
            # No order id to track → fall back to the legacy immediate activation.
            self._activate_trade_from_position(trade, None, open_result)
            return
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                "UPDATE trades SET order_id = ?, order_submitted_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (order_id, isoformat_utc(utc_now()), trade["id"]),
            )
        self.logger.info("Trade %s order submitted (order %s); awaiting fill", trade["id"], order_id)

    def _resolve_submitted_order(self, trade: dict[str, Any]) -> None:
        broker = self._trade_broker(trade)
        if broker is None:
            return
        order_id = str(trade.get("order_id") or "")
        if not order_id:
            return
        try:
            status = broker.get_order_status(order_id)
        except Exception:
            self.logger.warning("Order status lookup failed for trade %s", trade["id"], exc_info=True)
            return
        submitted_age = self._minutes_since(parse_datetime(trade.get("order_submitted_at"))) or 0.0
        timed_out = submitted_age >= int(self.config.order_await_timeout_minutes)

        if status is None:
            if timed_out:
                self._abandon_unfilled_order(trade, order_id, "ORDER_AWAIT_TIMEOUT")
            return
        if status.get("executed"):
            position = broker.get_open_position(trade["symbol"])
            self._activate_trade_from_position(trade, position, {"position_id": status.get("position_id")})
            return
        if status.get("rejected") or status.get("canceled"):
            self.logger.warning(
                "Entry order for trade %s/%s was %s: %s",
                trade["id"], trade["symbol"],
                "rejected" if status.get("rejected") else "canceled",
                status.get("error_message"),
            )
            self._cancel_pending_trade_record(trade, "ENTRY_REJECTED")
            return
        # waiting / not yet executed
        if timed_out:
            self._abandon_unfilled_order(trade, order_id, "ORDER_AWAIT_TIMEOUT")

    def _abandon_unfilled_order(self, trade: dict[str, Any], order_id: str, reason: str) -> None:
        broker = self._trade_broker(trade)
        if broker is not None:
            try:
                broker.cancel_order(order_id)
            except Exception:
                self.logger.warning("cancel_order failed for trade %s order %s", trade["id"], order_id, exc_info=True)
        self._cancel_pending_trade_record(trade, reason)
```

- [ ] **Step 4: Wire the branch into `sync_pending_trade`**

In `backend/services/trade_manager.py`, in `sync_pending_trade`, immediately after the `broker` None-check block (after `if broker is None: return`), insert:
```python
        if trade.get("order_id"):
            self._resolve_submitted_order(trade)
            return
```
Then replace the final two lines of `sync_pending_trade`:
```python
        position = broker.get_open_position(trade["symbol"])
        self._activate_trade_from_position(trade, position, result)
```
with:
```python
        self._mark_order_submitted(trade, result)
```

- [ ] **Step 5: Run, expect PASS**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_orders -v`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_orders.py
git commit -m "feat(orders): submit-then-resolve lifecycle (await fill, handle reject/timeout)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: `position_confirmed` gate + close-call instrument_id

**Files:** Modify `backend/services/trade_manager.py`; Test `backend/tests/test_trade_manager_orders.py`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_trade_manager_orders.py`:
```python
class PositionConfirmedTests(unittest.TestCase):
    def _open_trade(self, **over):
        t = {"id": 5, "symbol": "AAPL", "category": "STOCK", "status": "OPEN", "provider": "etoro",
             "instrument_id": 9422, "entry_price": 100.0, "quantity": 1.0, "allocated_capital": 100.0,
             "position_id": "9001", "position_confirmed": 0, "current_price": 100.0,
             "stop_loss": 90.0, "take_profit": 130.0}
        t.update(over)
        return t

    def test_unconfirmed_trade_not_externally_closed(self):
        broker = Mock()
        broker.get_open_position.return_value = None
        tm = _tm(broker)
        closed = {}
        tm._close_trade_without_position = lambda trade, *a, **k: closed.setdefault("hit", True)
        tm.sync_open_trade(self._open_trade(position_confirmed=0))
        self.assertNotIn("hit", closed)  # never confirmed -> not closed

    def test_confirmed_trade_is_externally_closed(self):
        broker = Mock()
        broker.get_open_position.return_value = None
        tm = _tm(broker)
        closed = {}
        tm._close_trade_without_position = lambda trade, *a, **k: closed.setdefault("hit", True)
        tm.sync_open_trade(self._open_trade(position_confirmed=1))
        self.assertTrue(closed.get("hit"))
```

- [ ] **Step 2: Run, expect FAIL**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_orders.PositionConfirmedTests -v`
Expected: FAIL — `test_unconfirmed_trade_not_externally_closed` fails because current code closes unconditionally.

- [ ] **Step 3: Gate the EXTERNAL_CLOSE and set `position_confirmed`**

In `backend/services/trade_manager.py`, in `sync_open_trade`, replace:
```python
        position = broker.get_open_position(trade["symbol"])
        if position is None:
            self._close_trade_without_position(trade)
            return
```
with:
```python
        position = broker.get_open_position(trade["symbol"])
        if position is None:
            # Only treat a vanished position as an external close once we have
            # actually observed it live; a never-confirmed trade (just filled,
            # portfolio still catching up, or a transient read) is left to retry.
            if trade.get("position_confirmed"):
                self._close_trade_without_position(trade)
            return
        if not trade.get("position_confirmed"):
            with db_cursor(self.config.db_trades) as cursor:
                cursor.execute(
                    "UPDATE trades SET position_confirmed = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (trade["id"],),
                )
```

In `_activate_trade_from_position`, set `position_confirmed` when a live position dict was passed. Change the `UPDATE trades SET ...` statement to also set `position_confirmed` — add `position_confirmed = ?,` to the SET list (e.g. right after `position_id = ?, order_reference_id = ?,`) and add the value `1 if isinstance(position, dict) and position else int(trade.get("position_confirmed") or 0)` to the parameter tuple in the matching position. (The SET clause and the params tuple must stay aligned; insert the new column+value in the same relative position.)

- [ ] **Step 4: Fix the close call to pass `instrument_id`**

In `backend/services/trade_manager.py`, in `_request_market_close`, replace:
```python
            order = broker.close_position_market(str(position_id))
```
with:
```python
            order = broker.close_position_market(str(position_id), instrument_id=int(trade.get("instrument_id") or 0))
```

- [ ] **Step 5: Run, expect PASS**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_orders -v`
Expected: PASS.

- [ ] **Step 6: Run the existing trade-manager suites (regression)**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_trade_manager_etoro tests.test_trade_manager_risk -v`
Expected: PASS. NOTE: a pre-existing test may assume the old immediate-activation behavior of `sync_pending_trade` (e.g. expecting a trade to become OPEN right after the limit is touched). If one fails, it is asserting the superseded behavior: update it to drive the new flow (after the fill it should set `order_id`, then a second `sync_pending_trade`/`_resolve_submitted_order` with `get_order_status.executed=True` activates OPEN). Report exactly which test you changed and why.

- [ ] **Step 7: Commit**
```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_orders.py
git commit -m "fix(orders): gate EXTERNAL_CLOSE on position_confirmed; pass instrument_id to close

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full suite + verification

- [ ] **Step 1: Full suite**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest discover -s tests`
Expected: PASS (ignore intentional "no gpt" tracebacks).

- [ ] **Step 2: Import smoke-check**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -c "import services.trade_manager, clients.etoro_client, core.db, core.utils; print('import ok')"`
Expected: prints `import ok`.

- [ ] **Step 3: Final read-through**

Confirm: `sync_pending_trade` no longer activates immediately (it stores `order_id`); `_resolve_submitted_order` handles executed/waiting/rejected/timeout; `sync_open_trade` only EXTERNAL_CLOSEs confirmed trades and sets `position_confirmed=1` when a live position is seen; `close_position_market` hits the market-close endpoint with `instrument_id`.

---

## Self-Review Notes (author)

- **Spec coverage:** Task 1 → settlementType; Task 2 → get_order_status (by name); Task 3 → close fix + cancel_order; Task 4 → DB columns + await timeout; Task 5 → submit-then-resolve lifecycle (executed/waiting/rejected/timeout); Task 6 → position_confirmed gate + close instrument_id. Status-by-name, async-open, async-close, premature-close, crypto-via-reject-path all covered. (No `ETORO_TRADE_CRYPTO` — removed from spec.)
- **Type/name consistency:** `get_order_status` returns `{executed,waiting,rejected,canceled,position_id,error_message,...}` consumed identically in `_resolve_submitted_order`. `close_position_market(position_id, instrument_id, units=None)` signature matches the caller change in Task 6. New columns `order_id`/`order_submitted_at`/`position_confirmed` surface via `SELECT *`.
- **Known nuance:** `position_confirmed` is set to 1 only when a *live* `get_open_position` dict is observed (in `_activate_trade_from_position` with a position, or in `sync_open_trade`). Activating from a Filled status with no live position dict yet leaves it 0, so a brief portfolio lag cannot trigger a wrong EXTERNAL_CLOSE.
- **Line numbers** are from the `dev-2.0` snapshot; locate by symbol if they drift.
