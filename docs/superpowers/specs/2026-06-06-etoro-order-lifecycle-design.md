# eToro order lifecycle — honor async order status + fix close path

**Date:** 2026-06-06
**Status:** Approved design (revised after live retest), pending implementation plan
**Area:** `backend/clients/etoro_client.py`, `backend/services/trade_manager.py`, `backend/core/db.py`

## Problem (root causes, confirmed by live debugging)

`POST /api/v2/trading/execution/{mode}orders` returns **2xx with an `orderId`**, but the real outcome is **asynchronous** and only readable via `GET /api/v2/trading/info/{mode}orders:lookup?orderId=…` → `status` (`Filled`/`WaitingForMarket`/`Rejected`/`Canceled`, with `errorCode`/`errorMessage`). Two confirmed bugs:

1. **Open: async status ignored.** The bot treats the 2xx submit as a fill, stores `position_id=None`, marks the trade `OPEN`, then `sync_open_trade` (`trade_manager.py:1010-1012`) closes it `EXTERNAL_CLOSE` because `get_open_position` returns `None`. So freshly-submitted trades are killed before they can fill.
2. **Close: wrong endpoint.** `close_position_market` POSTs `{action:"close", positionIds:[…]}` to the v2 *orders* endpoint, which 400s (`Exactly one of amount/units/contracts… / Either Symbol or InstrumentID…`). **The bot cannot close any position** → stop-loss / take-profit / trailing exits all fail.

### Live evidence (demo account, retested)
- A BTC market buy (`amount=50, leverage=1`, with or without SL/TP) → **`Filled`**, `settlementType` resolves to **REAL**, one position execution. **Crypto trades normally** (as eToro's normal market). An earlier `Rejected (759, "manual Trading is disallowed for this instrument type(10:CRYPTO)")` was **transient** (market/time state), NOT an account restriction.
- Stocks when the US market is closed → **`WaitingForMarket`** (settlement REAL), execute at open. Sending `settlementType="cfd"` for a stock is rejected; the working default is `REAL`.
- **`status.id` is inconsistent** (`3` was "Filled" in one case, "Rejected" in another); **map by `status.name`**, not id.
- Order lookup works by **`orderId`** (the bot stores only `order_reference_id`, which 404s on lookup).
- Correct close endpoint: `POST /api/v1/trading/execution/{mode}market-close-orders/positions/{positionId}` with body `{"InstrumentID": <id>, "UnitsToDeduct": null}` (null/omit = full close) → returns `orderForClose` + accepts; the position closes asynchronously. Verified working in testing.
- Leverage > 1 requires `StopLossRate` (we use leverage 1, so N/A).

## Goals
1. Drive the trade lifecycle from the **real async order status**, not the 2xx submit.
2. **Never `EXTERNAL_CLOSE` a never-confirmed trade** (premature-close defect).
3. **Fix the close path** so exits actually execute.
4. Surface rejections with their reason (no silent churn); transient rejections simply re-enter next cycle.

## Design

### Status mapping (by name)
`name` (case-insensitive) → `"fill"/"execut"` ⇒ executed; `"reject"` ⇒ rejected; `"cancel"` ⇒ canceled; `"wait"` ⇒ waiting; else pending. `status.id` only as a last-resort fallback.

### 1. `EToroClient` (`etoro_client.py`)
- `open_market_position`: add **`"settlementType": "real"`** to the body (the working default; harmless otherwise). Keep returning `order_id`.
- New **`get_order_status(order_id) -> dict | None`**: `GET /api/v2/trading/info/{mode}orders:lookup?orderId=<id>` (reuse `_mode_segment()`); 404/None → `None`. Returns normalized `{order_id, status_name, executed, waiting, rejected, canceled, error_code, error_message, position_id}` where `position_id` = first `positionExecutions[]` with `state=="open"` (else `None`).
- **Fix `close_position_market(position_id, instrument_id, units=None)`**: POST `/api/v1/trading/execution/{mode}market-close-orders/positions/{position_id}` with `{"InstrumentID": int(instrument_id)}` plus `{"UnitsToDeduct": units}` only when a partial close is requested. (Signature gains `instrument_id`; update callers to pass the trade's `instrument_id`.)
- New **`cancel_order(order_id)`**: `DELETE /api/v2/trading/execution/{mode}orders/{orderId}` (idempotent) for abandoning an unfilled order.

### 2. DB (`core/db.py`) — add to `TRADE_OPTIONAL_COLUMNS` (auto-migrated)
- `order_id TEXT` — eToro order id for status lookup.
- `order_submitted_at TEXT` — when the market order was fired.
- `position_confirmed INTEGER NOT NULL DEFAULT 0` — set to 1 once a live position is observed.

### 3. `TradeManager` lifecycle (`trade_manager.py`)
Separate "fired an order" from "position open". A PENDING trade that has fired a market order carries `order_id` and stays PENDING until the order resolves.

- **`sync_pending_trade`** branches at the top:
  - **`order_id` set** (already submitted): poll `get_order_status`:
    - executed → resolve position (`status.position_id` or `get_open_position`), activate `OPEN`, set `position_id` + `position_confirmed=1`.
    - waiting → stay PENDING; do **not** re-fire; do **not** apply the emulated-limit age-cancel while awaiting the market. A separate hard ceiling `order_await_timeout_minutes` (default 360) cancels (`cancel_order`) an order stuck unfilled → trade `CANCELLED` ("ORDER_AWAIT_TIMEOUT").
    - rejected/canceled → best-effort `cancel_order`, mark trade `CANCELLED` reason `ENTRY_REJECTED` + log `error_message` at WARNING; free the slot. (Transient rejections re-enter on the next cycle.)
    - status None/transient → leave; retry next tick.
  - **no `order_id`** (emulated-limit, not yet fired): existing logic; when the limit is touched, fire `open_market_position`, then **store `order_id` + `order_submitted_at`, keep status PENDING** (do NOT activate immediately).
- **`_activate_trade_from_position`**: set `position_confirmed=1` whenever a real position/`position_id` is obtained.
- **`sync_open_trade`** (premature-close fix): when `get_open_position` is `None` → `EXTERNAL_CLOSE` **only if `position_confirmed`**; otherwise do not close (re-resolve next tick).
- **Close flow** (`_request_market_close` / `close_position_market` callers): pass the trade's `instrument_id` into the fixed `close_position_market`. Exit remains async — `_sync_exit_order` already polls `get_open_position` until the position is gone, then marks the trade closed; that now works because the close request succeeds.

## Out of scope / notes
- Real crypto IS tradable (no account change needed); the transient rejection is handled by the rejected→re-enter path. **No `ETORO_TRADE_CRYPTO` flag** (removed from this design).
- No change to GPT signals, sizing, or the risk score.
- `order_reference_id` kept for traceability; `order_id` is the new lookup key.

## Testing
- `get_order_status`: mock Filled (with `positionExecutions`), WaitingForMarket, Rejected (errorCode/message), 404→None; assert flags + `position_id`; mapping by name (incl. id=3 meaning "Filled").
- `open_market_position`: body includes `settlementType="real"`, still no `symbol`.
- `close_position_market`: hits `/api/v1/trading/execution/{mode}market-close-orders/positions/{id}` with `{InstrumentID}` (+ `UnitsToDeduct` only for partial); returns parsed result.
- `cancel_order`: DELETE path + idempotency.
- Lifecycle: fired order `waiting` keeps trade PENDING (not OPEN/cancelled; market-wait not counted against limit timeout); `executed`→OPEN + `position_id` + `position_confirmed=1`; `rejected`→CANCELLED + reason logged; await-timeout cancels.
- `sync_open_trade`: `position_confirmed=0` + `get_open_position None` → NOT closed; confirmed trade that disappears → `EXTERNAL_CLOSE`.
- Regression: existing trade-manager + client tests stay green (update the close-body test + any caller passing `instrument_id`).
