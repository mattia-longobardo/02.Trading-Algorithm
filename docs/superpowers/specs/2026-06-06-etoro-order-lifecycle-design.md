# eToro order lifecycle — honor async order status

**Date:** 2026-06-06
**Status:** Approved design, pending implementation plan
**Area:** `backend/clients/etoro_client.py`, `backend/services/trade_manager.py`, `backend/core/db.py`, `backend/core/utils.py`

## Problem (root cause, confirmed by live debugging)

`POST /api/v2/trading/execution/{mode}orders` returns **2xx with an `orderId`**, but the real outcome is **asynchronous** and only readable via `GET /api/v2/trading/info/{mode}orders:lookup?orderId=…` → `status` (`Executed` / `WaitingForMarket` / `Rejected` / `Canceled`, with `errorCode`/`errorMessage`). The bot never checks it: it assumes success, stores `position_id=None`, marks the trade `OPEN`, then `sync_open_trade` (`trade_manager.py:1010-1012`) closes it as `EXTERNAL_CLOSE` because `get_open_position` returns `None`.

Live evidence (demo account):
- **Stocks** (e.g. AAPL) are **accepted**: `WaitingForMarket`, `settlementType` resolves to `REAL` (the default). They execute when the market opens — but the bot kills them first. So stocks would work once the lifecycle is honored.
- **Crypto** (e.g. BTC) is **always `Rejected` (errorCode 759, "manual Trading is disallowed for this instrument type(10:CRYPTO)")** on this demo account. Every `settlementType` value (`real`, `realFutures`, `marginTrade`, none) resolves to `CFD`; real crypto is **not available on this account** (eToro account-level restriction, not a code bug).
- The create response's `referenceId` cannot be looked up (`orders:lookup?referenceId=` → 404); **`orderId` works**. The bot currently stores only `order_reference_id`.
- Sending `settlementType="cfd"` for a stock is rejected ("settlement type CFD disallowed"); the working default for stocks is `REAL`.

## Goals

1. Don't treat a 2xx submit as a fill. **Resolve each order's real status** and drive the trade lifecycle from it.
2. **Never mark a never-confirmed trade `EXTERNAL_CLOSE`** (the premature-close defect).
3. Surface rejections (incl. crypto) with their reason instead of silent churn.
4. Provide a clean way to **disable a category** that the account can't trade (crypto here).

## Design

### Order-status state machine
A submitted order resolves to one of: **Executed**, **Waiting** (WaitingForMarket / not-yet-executed), **Rejected**, **Canceled**. Map by `status.name` (case-insensitive substring: "execut"→executed, "reject"→rejected, "cancel"→canceled, "wait"→waiting), with the numeric `status.id` as a fallback (1=Executed, 2/7=Canceled, 3/4=Rejected, 11=Waiting).

### 1. `EToroClient` (`etoro_client.py`)
- `open_market_position`: add **`"settlementType": "real"`** to the body (matches the working stock default; harmless where forced to CFD). Keep returning `order_id`.
- New **`get_order_status(order_id) -> dict | None`**: `GET /api/v2/trading/info/{mode}orders:lookup?orderId=<id>` (reuse `_mode_segment()`); on 404/None return `None`. Returns a normalized dict:
  `{order_id, status_id, status_name, executed, waiting, rejected, canceled, error_code, error_message, position_id}` where `position_id` is taken from the first `positionExecutions[]` whose `state == "open"` (else `None`).
- New **`cancel_order(order_id)`**: `DELETE /api/v2/trading/execution/{mode}orders/{orderId}` (idempotent) — used when abandoning an unfilled order.

### 2. DB (`core/db.py`)
Add optional columns via `TRADE_OPTIONAL_COLUMNS` (auto-migrated):
- `order_id TEXT` — the eToro order id (for status lookup).
- `order_submitted_at TEXT` — when the market order was fired.
- `position_confirmed INTEGER NOT NULL DEFAULT 0` — set to 1 once a live position has been observed at least once.

### 3. `TradeManager` lifecycle (`trade_manager.py`)
Split "fired an order" from "position open". A PENDING trade that has fired a market order carries `order_id` and stays PENDING until the order resolves.

- **`sync_pending_trade`** branches at the top:
  - **If `trade["order_id"]` is set** (order already submitted): poll `get_order_status`:
    - `executed` → resolve the position (`status.position_id` or `get_open_position`) and activate `OPEN` (set `position_id`, `position_confirmed=1`).
    - `waiting` → leave PENDING; do **not** re-fire, and do **not** apply the emulated-limit age-cancel while waiting on the market (guard the existing `crypto_pending_cancel_minutes` timeout with "only when no `order_id`"). Add a separate hard ceiling `order_await_timeout_minutes` (default 360) after which an unfilled order is cancelled (`cancel_order`) and the trade `CANCELLED` ("ORDER_AWAIT_TIMEOUT").
    - `rejected`/`canceled` → `cancel_order` (best-effort) and mark the trade `CANCELLED` with reason `ENTRY_REJECTED` plus the `error_message` logged at WARNING; free the slot.
    - status unavailable (None / transient) → leave; retry next tick.
  - **Else** (emulated-limit, not yet fired): existing logic; when the limit is touched, fire `open_market_position`, then **store `order_id` + `order_submitted_at` and keep status PENDING** (do NOT call `_activate_trade_from_position` immediately). Resolution happens on the next tick via the branch above.
- **`_activate_trade_from_position`**: set `position_confirmed = 1` whenever a real position/`position_id` is obtained.
- **`sync_open_trade`** (premature-close fix): when `get_open_position` is `None`:
  - if `position_confirmed` (the trade was genuinely open before) → `EXTERNAL_CLOSE` as today.
  - else (never confirmed — should be rare under the new flow) → do **not** close; re-resolve via `get_order_status`/`get_open_position` next tick (defense in depth).

### 4. Category enable/disable (`core/utils.py`)
Add **`etoro_trade_crypto: bool = True`** (env `ETORO_TRADE_CRYPTO`). When false: universe selection skips CRYPTO and the entry path won't open crypto. Lets the operator cleanly disable crypto on accounts where it's not tradable (this demo). Default stays `True`; **recommended `false` on the current demo account** until eToro enables real crypto.

## Out of scope / notes
- Enabling real crypto on the eToro account (account/permission change on eToro's side; not code).
- No change to GPT signal generation, sizing, or the risk score.
- Reuse `order_reference_id` as-is (kept for traceability); `order_id` is the new lookup key.

## Testing
- `get_order_status`: mock lookup payloads for Executed (with `positionExecutions`), WaitingForMarket, Rejected (errorCode/message), 404 → None; assert normalized flags + `position_id`.
- `open_market_position`: body now includes `settlementType="real"`; still no `symbol`.
- `cancel_order`: DELETE path + idempotency.
- Lifecycle: a fired order in `waiting` keeps the trade PENDING (not OPEN, not cancelled, market-wait not counted against the limit timeout); `executed` → OPEN with `position_id` + `position_confirmed=1`; `rejected` → CANCELLED with reason logged; await-timeout cancels.
- `sync_open_trade`: never-confirmed trade (`position_confirmed=0`) with `get_open_position None` is NOT closed; confirmed trade that disappears IS closed `EXTERNAL_CLOSE`.
- Config: `ETORO_TRADE_CRYPTO=false` removes crypto from selection/entry.
- Regression: existing trade-manager + client tests stay green.
