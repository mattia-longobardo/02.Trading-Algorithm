# Universe selection: cheap metadata prefilter + exchange/futures filtering

**Date:** 2026-06-06
**Status:** Approved design, pending implementation plan
**Area:** `backend/clients/etoro_client.py`, `backend/services/universe_manager.py`, `backend/core/utils.py`

## Problem

The weekly universe selection (eToro) has three problems observed in production:

1. **Too many candidates (10527 stocks).** `EToroClient.list_assets("STOCK")` pulls eToro's entire global equity catalog. The only real filters are name-based (ETF/warrant/SPAC) and a `tradable` flag that is **hardcoded to `True`** (`etoro_client.py:342`), so it filters nothing. Of the 10527 stock candidates, 3156 have zero dollar volume (illiquid / no data / effectively untradeable).

2. **~6 hour runtime.** `_select_etoro_universe` enriches the **full** 10527-stock payload with market metrics *before* prefiltering (`universe_manager.py:657-662`). Enrichment calls `get_multi_bars`, which issues **one HTTP candles request per symbol** (`etoro_client.py:222-227`), each fetching ~400 days. So ~10527 sequential requests run before the cheap deterministic prefilter (which cuts to `required_count × 72`) gets a chance — the prefilter happens too late to save any work.

3. **Crypto dated futures selected.** The "Crypto" instrument type includes dated futures (e.g. `BTC.MAY26`, `BTC.JUN26`). Nothing excludes them, and because eToro supplies no volume for most crypto (298/324 candidates have zero dollar volume), the liquidity prefilter cannot distinguish them, so GPT picks futures into the live universe.

## Decisions (from brainstorming)

- **Stock markets:** USA + major EU exchanges only.
- **Crypto:** spot only — exclude dated futures.
- **Performance approach:** cheap metadata prefilter via `discover-instruments`, then fetch bars only for a shortlist.
- **Stock shortlist size:** ~300 symbols reach the bars + GPT stage.

## Approach

Replace "download whole catalog → fetch bars for all → prefilter" with **"cheap metadata prefilter → fetch bars only for a shortlist"**.

eToro exposes `GET /api/v1/instruments/discover` (Asset Explorer), which returns, **without any bar fetch**: `symbol`, `displayname`, `instrumentTypeID`, `instrumentType`, `exchangeID`, `isCurrentlyTradable`, `isDelisted`, `isBuyEnabled`, `currentRate`, `popularityUniques`, and price-change fields (`dailyPriceChange`, `weeklyPriceChange`, `monthlyPriceChange`, `threeMonthPriceChange`, `sixMonthPriceChange`, `oneYearPriceChange`, …). It supports `sort` (e.g. `-popularityUniques`), `page`/`pageSize`, and per-field filters. These fields give a popularity + momentum signal good enough to rank candidates before any expensive work.

`GET /api/v1/market-data/exchanges` returns `exchangeID → exchangeDescription`, used to resolve the exchange whitelist.

## Components

### 1. `EToroClient` (`backend/clients/etoro_client.py`)

**New `discover_instruments(asset_class: str) -> list[dict]`**
- Resolves instrument-type IDs via the existing `_instrument_type_ids` / `_ASSET_CLASS_HINTS`.
- Calls `/api/v1/instruments/discover` once per type ID with `sort=-popularityUniques`, and best-effort server filters `isDelisted=false`, `isCurrentlyTradable=true`, `instrumentTypeID=<id>`.
- Paginates (`page`/`pageSize=200`) up to a bounded cap `DISCOVER_MAX_ITEMS` (4000) per type. Stops when a page is short, empty, or the cap is reached.
- Returns normalized rows: `symbol` (upper), `name`, `status`, `tradable` (= `isCurrentlyTradable && isBuyEnabled`), `fractionable` (False — unknown), `instrument_id`, `instrument_type_id`, `instrument_type`, `exchange_id`, `delisted`, `current_rate`, `popularity`, `price_change_1d/1w/1m/3m/6m`.
- Skips `isInternalInstrument` / `isHiddenFromClient` rows; dedupes by symbol; caches symbol→instrument_id via `upsert_instrument_mapping`.

**New `list_exchanges() -> dict[int, str]`**
- Calls `/api/v1/market-data/exchanges`, returns `{exchangeID: exchangeDescription}`, cached on the client instance.

**`list_assets` stays as the fallback path** (its hardcoded `tradable=True` is acceptable there because the cheap stage is the primary path and carries real tradability; the legacy path still applies the post-bar liquidity prefilter).

### 2. Config (`backend/core/utils.py`)

- **`universe_stock_exchanges: tuple[str, ...]`** — whitelist of exchange-name patterns (case-insensitive substring match against live `exchangeDescription`). Default `DEFAULT_UNIVERSE_STOCK_EXCHANGES`: USA (`NASDAQ`, `NYSE`, `NEW YORK`, `ARCA`, `AMERICAN STOCK`) + EU (`LONDON`, `LSE`, `XETRA`, `FRANKFURT`, `EURONEXT`, `PARIS`, `AMSTERDAM`, `BRUSSELS`, `BORSA ITALIANA`, `MILAN`, `SIX`, `SWISS`, `ZURICH`, `BME`, `MADRID`). Overridable via env `UNIVERSE_STOCK_EXCHANGES` (comma-separated).
- **`universe_stock_shortlist: int`** = 300 (env `UNIVERSE_STOCK_SHORTLIST`).
- **`universe_crypto_shortlist: int`** = 150 (env `UNIVERSE_CRYPTO_SHORTLIST`).
- The cheap-stage stock price floor reuses the existing `UniverseManager.STOCK_MIN_LAST_CLOSE` (5.0) against `current_rate`.

### 3. `UniverseManager` (`backend/services/universe_manager.py`)

**New helpers**
- `_is_dated_future(symbol)` — `True` if symbol matches `\.[A-Z]{3}\d{2}$` (e.g. `.MAY26`). Defensive: also treat `instrument_type` containing "futur" as a future.
- `_asset_name(asset)` — returns lowercased name from either a dict (`asset["name"]`) or an object (`asset.name`); the existing `_looks_like_etf` / `_looks_like_non_common_stock` / `_looks_like_shell_company` switch to it so they work on discover dicts too.
- `_resolve_exchange_whitelist(broker)` — calls `broker.list_exchanges()`, returns the set of `exchange_id`s whose description matches any whitelist pattern, or `None` (don't filter) on failure/empty.
- `_cheap_prefilter_score(asset)` — score from discover fields only: `log10(popularity+1)` weighted + blended momentum (1w/1m/3m/6m) − a spike penalty on extreme 1-day moves. No bars.
- `_passes_cheap_filter(category, asset, exchange_whitelist)` — STOCK: tradable, not delisted, exchange in whitelist, `current_rate >= STOCK_MIN_LAST_CLOSE`, not ETF/warrant/SPAC. CRYPTO: tradable, not delisted, not a dated future.
- `_build_cheap_shortlist(broker, category, preferred_symbols, exchange_whitelist)` — discover → filter → score → sort desc → pin current-universe symbols → cap to `universe_stock_shortlist` / `universe_crypto_shortlist`.

**Rewire `_select_etoro_universe`**
1. Cheap stage: build stock + crypto shortlists. On any failure or empty result, fall back to the legacy `_get_etoro_*_candidate_payload` full scan (logged at WARNING).
2. Expensive stage (shortlist only): existing `_enrich_payload_with_market_metrics` (bars) → existing `_select_category_universe` (liquidity prefilter → parallel GPT dossiers → final GPT consolidation). **Unchanged** below this line.
3. `universe_candidates.log` now records the shortlist with both cheap and bar-derived metrics.

## Data flow

```
discover (paginated, sorted by popularity)
  → hard filters: tradable, not delisted, exchange whitelist (stock) / not future (crypto), price floor, name filters
  → cheap score (popularity + momentum)
  → top-N shortlist (300 stock / 150 crypto) + pinned current universe
  → bar enrichment (shortlist only)            ← the only expensive step, now ~300 not ~10527
  → existing liquidity prefilter
  → parallel GPT dossiers
  → final GPT consolidation
  → universe.json
```

## Error handling

- Discover pagination: stop on short/empty page; bounded by `DISCOVER_MAX_ITEMS`.
- Exchanges call failure: fall back to **not** filtering by exchange (log WARNING) rather than emptying the universe.
- Whole cheap stage failure or empty: fall back to legacy `list_assets` flow.
- Per-symbol bar failure in the shortlist: unchanged (already tolerated).

## Testing

- `discover_instruments`: mock paginated `/instruments/discover`; assert sort param, instrument-type filter, pagination stop, cap, normalized output incl. real `tradable`, internal/hidden skipped.
- `list_exchanges`: mock response; assert id→description map.
- `_is_dated_future`: table test — `BTC.MAY26`/`BTC.JUN26`/`ETH.DEC25` → True; `ETH.SPOT`/`HYPE`/`JTO`/`BTC` → False.
- `_resolve_exchange_whitelist`: mock exchanges map + default patterns → NASDAQ/NYSE/Milan included, APAC excluded.
- `_build_cheap_shortlist`: stocks — exchange filtering, price floor, ETF exclusion, cap, pinned preferred survive; crypto — futures excluded.
- Fallback: when `discover_instruments` raises, assert legacy `list_assets` path is used.
- Regression: existing `_select_category_universe` / dossier tests stay green (that stage is unchanged).

## Out of scope / YAGNI

- No change to GPT dossier prompts or final-selection logic.
- No new persistence/schema (reuse `instrument_map`).
- No marketCap/PE filtering (not present in this API version's `Instrument` schema; popularity + momentum + exchange + price cover the need).
- Crypto is not split by exchange.
