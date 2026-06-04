# Design: Migrate trading bot from Alpaca → eToro

**Date:** 2026-06-04
**Status:** Approved (pending spec review)
**Scope:** Backend trading bot (`backend/`). Frontend is unaffected except where API response fields change (none planned).

## 1. Goal

Replace the Alpaca brokerage integration with eToro's Public REST API as the **sole** broker. The bot keeps its existing behaviour — GPT-driven signal generation, slot-based capital allocation, script-managed take-profit / stop-loss / trailing logic, scheduler cadence, reports, dashboard — but executes against eToro instead of Alpaca.

This is a **full replacement**, not a dual-broker abstraction: all Alpaca code, dependencies, env, and DB data are removed.

## 2. Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| 1 | Target account | **Demo first**, switchable to Real via `ETORO_ACCOUNT_TYPE` config |
| 2 | Alpaca treatment | **Full replacement** — remove entirely |
| 3 | Order-model adaptation | **Full client-side emulation** of limit entries + trailing TP/SL |
| 4 | Leverage | **1× unleveraged** always (opens eToro *real-asset* positions, `settlementTypeID=1`) |
| 5 | DB & config | **Clean slate** — both SQLite DBs removed, config fully replaced, no legacy columns/aliases |
| 6 | Crypto symbols | Store **eToro-native** symbols (`"BTC"`, `"ETH"`); drop the `"BTC/USD"` suffix convention |

## 3. Why this is smaller than a ground-up rewrite

The codebase is **already provider-aware**:
- `trades.provider` column, `brokers` dict in `trade_manager`, `_trade_broker()` / `_trade_provider()` dispatch.
- Per-provider equity snapshots; `provider_account_currency(provider)`.
- `PROVIDER_ALPACA` / `ALL_PROVIDERS` constants.

The decisive simplification: **eToro maps onto what was previously Alpaca's "crypto + script-protection" path.** eToro has no separate bracket-leg or broker-trailing-stop *order* objects that the bot would manage; instead SL/TP are *position attributes*. So the stock-specific broker-bracket and broker-trailing-order code paths are **deleted**, and every trade (stock and crypto) runs through one unified, script-managed lifecycle.

## 4. eToro API reference (verified against the OpenAPI spec)

- **Base URL:** `https://public-api.etoro.com/api/v1` (orders use `/api/v2`). Demo uses a `/demo/` path segment.
- **Auth headers (every request):** `x-api-key` (app key), `x-user-key` (account key), `x-request-id` (fresh GUID per call; also the idempotency key for order creation).
- **Rate limit:** 60 GET requests/minute.

### Trading
- **Open** — `POST /api/v2/trading/execution/orders`
  Body: `{ action:"open", transaction:"buy", symbol, instrumentId, orderType:"mkt", amount, orderCurrency:"usd", leverage, stopLossRate, takeProfitRate, stopLossType:"fixed" }`.
  Exactly one of `amount` / `units` / `contracts` — we use **`amount`** (USD cash) so no client-side qty math is needed. (`orderType:"mit"` + `triggerRate` and `stopLossType:"trailing"` exist but are intentionally **not** used — see §6.)
- **Close** — `POST /api/v2/trading/execution/orders` with `{ action:"close", positionIds:[…] }` (market close; full or partial). (`/api/v1/.../market-close-orders/positions/{positionId}` is the v1 equivalent.)
- **Order info / fill read-back** — `/api/v2/trading/info/orders:lookup` (or `/trading/info/{mode}/orders/{orderId}`) → resolves the resulting `positionID`, `openRate`, `units`, `amount`.

### Portfolio / account (USD only)
- `GET /trading/info/{mode}/portfolio` → `clientPortfolio.credit` (USD cash), `clientPortfolio.positions[]`.
- `GET /trading/info/{mode}/pnl` → for equity = credit + Σ invested + Σ unrealized PnL.
- **Position fields:** `positionID, instrumentID, openRate, units, amount, isBuy, leverage, stopLossRate, takeProfitRate, isTslEnabled, settlementTypeID`.

### Market data
- **Candles** — `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`; `direction∈{asc,desc}`, `interval∈{OneMinute…OneDay,OneWeek}`. Response: per-candle `{ fromDate, open, high, low, close, volume }`. **No multi-symbol endpoint** — one call per instrument.
- **Rates** — `GET /api/v1/market-data/instruments/rates?instrumentIds=…` → `{ instrumentID, ask, bid, lastExecution }`.

### Instruments
- Catalog: `GET /api/v1/market-data/instruments` (filter by `instrumentTypeIds`), `GET /api/v1/market-data/instrument-types`.
- Resolve symbol: `GET /api/v1/instruments/{symbol}` → `instrumentId, instrumentType, isCurrentlyTradable, isBuyEnabled, isDelisted, isOpen`.

## 5. Components

### 5.1 New: `clients/etoro_client.py` — `EToroClient`
Built on `requests` (already a dependency). Exposes the broker method surface the dispatch already expects so consumers change minimally.

- **Headers:** injects `x-api-key`, `x-user-key`, and a fresh `x-request-id` GUID per call.
- **Account mode:** `demo` | `real` selects the path segment and the open-order endpoint.
- **Rate limiter:** token bucket capped at 60/min, shared across all GET calls.
- **Retries:** reuse `core.utils.retry()` with `_is_transient_etoro_error` (retry 5xx/network/timeouts; fail-fast 4xx).

Method map:

| Method | eToro endpoint | Notes |
|---|---|---|
| `get_available_cash()` | portfolio/pnl | `credit` − Σ pending order amounts (per "calculate available cash" guide) |
| `get_account_equity()` | pnl | credit + Σ invested + Σ unrealized PnL (USD) |
| `list_open_positions()` | portfolio | `clientPortfolio.positions[]` |
| `get_open_position(symbol)` | portfolio | match by resolved `instrumentID` |
| `get_latest_price(symbol)` / `get_latest_quote(symbol)` | rates | `lastExecution` / `bid`+`ask` |
| `get_bars` / `get_multi_bars(symbols)` | candles (per instrument) | loop + rate-limit; daily `OneDay`, `desc` |
| `list_assets(category)` | instruments + instrument-types | returns metadata (symbol, instrumentId, tradable flags) |
| `open_market_position(...)` | v2 orders (open) | `amount`=allocated_capital, `leverage`=1, fixed SL/TP backstop |
| `close_position_market(position_id, units=None)` | v2 orders (close) | full or partial |
| `get_order_info(order_id)` | orders lookup | read back positionId/openRate/units after fill |
| `resolve_instrument(symbol)` | instruments/{symbol} | with cache (see 5.2) |

### 5.2 New: `clients/etoro_instruments.py` + `instrument_map` table
- `instrument_map(symbol TEXT PK, instrument_id INTEGER, category TEXT, display_name TEXT, tradable INTEGER, updated_at TEXT)`.
- `resolve(symbol) → instrument_id` with DB cache + on-demand lookup; refreshed during the weekly universe refresh.
- `trades` and OHLCV tables stay keyed by human-readable `symbol`; `trades` gains an `instrument_id` column for fast position matching.

### 5.3 Strategy — entry (emulated limit, both categories)
1. On GPT `OPEN` signal: validate levels (existing logic unchanged), resolve `instrument_id`, compute `allocated_capital` (cash ÷ free slots, unchanged), and store the trade `PENDING` with `target_entry_price`, SL/TP, trailing params — **no broker order placed yet.**
2. Each 1-min monitor tick, `sync_pending_trade` polls the current rate and reuses today's collar/chase/age logic:
   - Ask within `[target, target·(1+chase_bps)]` (and not below target for a long) → fire **market open by amount** with `leverage=1` + fixed SL/TP backstop (GPT's hard `stop_loss`/`take_profit`). Read back fill via order-info → activate `OPEN`.
   - Ask above chase ceiling: keep waiting; re-evaluate next tick.
   - Age ≥ `entry_cancel_minutes` → cancel as a **pure DB state change** (`ENTRY_PRICE_MOVED` / `ENTRY_TIMEOUT`) — no broker order to cancel (simpler than today's crypto reprice loop).
3. Store the open `x-request-id` GUID as `order_reference_id` to dedupe retries.

This unifies stocks and crypto under one emulated-limit path (stocks previously used a DAY limit order; now emulated identically).

### 5.4 Strategy — exit (runtime logic unchanged, new broker calls)
- `sync_open_trade` keeps computing `high_water_mark`, trailing TP (activation% + min-profit floor), trailing SL, and static TP/SL **exactly as today**.
- On any trigger → `_request_market_close` → eToro close-by-`positionId` (market). Store `exit_order_id` (= close orderId) and `pending_close_reason`.
- `_sync_exit_order` polls portfolio/order-info: position gone → `CLOSED` with reason; close order rejected/position still present → keep `OPEN`, retry next tick.
- The eToro-native **fixed SL/TP backstop** set at open means a hard stop still fires even if the bot is down — a robustness gain over the old Alpaca-crypto path.

### 5.5 Config — `core/utils.py` + `.env.example` (full replacement)
Remove all `ALPACA_*` and the legacy `ACCOUNT_CURRENCY` alias. Add:
- `ETORO_API_KEY`, `ETORO_USER_KEY`
- `ETORO_ACCOUNT_TYPE` = `demo` | `real` (default `demo`) → drives endpoint mode + `demo` property
- `ETORO_DEFAULT_LEVERAGE` = `1`
- `ETORO_MIN_TRADE_AMOUNT` (replaces `alpaca_max_notional_per_order`; eToro has a per-position minimum)
- Keep entry-tuning knobs, renamed generic: `ENTRY_LIMIT_COLLAR_BPS`, `ENTRY_MAX_CHASE_BPS`, `ENTRY_PENDING_CANCEL_MINUTES` (now used for both categories)
- `account_currency` fixed to `"USD"`
- Constants: `PROVIDER_ETORO = "etoro"`, `ALL_PROVIDERS = (PROVIDER_ETORO,)`; `paper`→`demo` property derived from `ETORO_ACCOUNT_TYPE`

### 5.6 DB — `core/db.py` (fresh schema)
`trades` table designed around eToro (no `alpaca_*` columns):
- Identifiers: `instrument_id INTEGER`, `position_id TEXT`, `order_reference_id TEXT`, `exit_order_id TEXT`.
- Keep: `symbol, category, direction, status, entry_price, quantity, allocated_capital, target_entry_price, take_profit, stop_loss, trailing_take_profit_distance, trailing_take_profit_activation_pct, trailing_take_profit_price, trailing_stop_distance, trailing_stop_price, high_water_mark, current_price, pnl, close_price, close_reason, pending_close_reason, open_timestamp, close_timestamp, exit_requested_at, reasoning, confidence, trade_score, provider, account_currency`.
- Drop broker-protection columns (`broker_protection_type`, `protection_order_id`, `protection_client_order_id`) — all trades are script-managed now.
- New `instrument_map` table (5.2). OHLCV tables unchanged (symbol-keyed).

### 5.7 Untouched
`core/fx.py` (still USD→EUR via external API), scheduler cadence, reports, metrics, auth/sessions, `app.sqlite`, and the HTTP API endpoints (they read the generic `brokers` dict + DB). `data_manager` stays symbol-keyed.

### 5.8 Removed
`clients/alpaca_client.py`, the `alpaca-py` dependency, all `ALPACA_*` env, the broker-bracket and broker-trailing-order code paths in `trade_manager`, and `supports_advanced_orders` / `supports_broker_side_trailing_stop` (now always script-side).

## 6. Why not use eToro's native MIT / trailing-stop?
eToro *does* offer `orderType:"mit"` (limit-like) and `stopLossType:"trailing"`. We deliberately keep entry and trailing **client-side** because:
- The bot's trailing **take-profit** has an *activation threshold* and a *minimum-profit floor* that a plain broker trailing **stop-loss** can't replicate.
- Client-side emulation preserves the existing, tested collar/chase/timeout entry logic and avoids resting orders on the book.
- eToro's fixed SL/TP at open is still used as a *backstop*, giving us protection without depending on broker semantics we don't fully control.

## 7. Tests (TDD)
- New `tests/test_etoro_client.py`: request shaping, header + GUID injection, rate-limiter behaviour, error classification, response parsing (positions, candles, rates) — all against mocked HTTP.
- New `tests/test_etoro_instruments.py`: symbol→instrumentId resolution + caching.
- Rewrite `tests/test_trade_manager_orders.py` against an `EToroClient` fake (emulated entry fill, exit close, cancel-as-DB-state).
- Update `tests/test_data_manager.py`, `tests/test_report.py`, `tests/test_scheduler_api.py` fixtures to the eToro fake.

## 8. Build sequence
1. Config + provider constants + `.env.example`.
2. `EToroClient` (HTTP, auth, rate limiter, retries, parsing) + tests.
3. Instrument-map module + table + tests.
4. Market-data + universe rewiring + tests.
5. Account/equity/portfolio reads + equity snapshots.
6. Trade-lifecycle rewrite (emulated entry + runtime exit) + tests.
7. Remove Alpaca; rewire API + scheduler wiring; delete old DBs.
8. Integration pass against the eToro **demo** account.

## 9. Risks & constraints
- **60 GET/min** vs. universe enrichment over many candidates → aggressive caching + throttling; universe refresh is slower. No multi-symbol candle endpoint (N calls; mitigated by daily cadence + incremental DB cache).
- **Stock market hours:** emulated stock entries only fill while the exchange is open (`isOpen`); the monitor must respect it.
- **eToro minimum trade amount** per position; amount-based opens support fractional units.
- **Symbol convention change** for crypto (`"BTC/USD"`→`"BTC"`) touches universe filters and instrument resolution; clean-slate DBs avoid migration pain.
- **Demo vs Real** endpoint divergence is encapsulated entirely inside `EToroClient`.
