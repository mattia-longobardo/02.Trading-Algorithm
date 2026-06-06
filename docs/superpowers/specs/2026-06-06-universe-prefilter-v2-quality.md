# Universe prefilter v2 — quality/size gate via discover (verified against live API)

**Date:** 2026-06-06
**Status:** Approved design (supersedes the discover details in `2026-06-06-universe-prefilter-discover-design.md`)
**Area:** `backend/clients/etoro_client.py`, `backend/services/universe_manager.py`, `backend/core/utils.py`

## Why v2

The v1 prefilter ranked by popularity + momentum, which lets small, unreliable companies with pumped momentum into the universe. The user wants a **quality/size-first** prefilter. A live probe of `/api/v1/instruments/discover` revealed that v1's discover integration also did not match the real API, so this revision fixes both.

## Verified API facts (live probe, demo account)

- **`assetClass` is the working server-side type filter**, NOT `instrumentTypeID` (which does not filter — discover otherwise returns all asset classes mixed, incl. Forex/Indices/Commodities). Values: `assetClass=Stocks` (12382), `assetClass=Crypto` (676). (`Stock`/`Cryptocurrencies` → 0.)
- **`marketCapMin` works server-side**: Stocks ≥$2B → 4220; ≥$10B → 2383. `sort=-marketCap` works.
- **Default response projection is minimal** (~6–44 keys). Passing **any `fields=` list triggers the FULL fundamentals object (~162 keys)**. So we pass an explicit `fields` projection.
- **Correct field names differ from the OpenAPI schema**: `displayName` (not `displayname`), `exchangeName` (string; `exchangeID` returns null), `marketCapInUSD`. 
- **Rich fundamentals available with no bar fetch**: `marketCapInUSD`, `averageDailyVolumeLast3Months-TTM` (avg daily share volume), `daysSinceFirstTrade`, `countryCode`, `isin`, `isBuyEnabled`, `isDelisted` (null for crypto), `beta`, `peRatio`, `priceToSales-TTM`, `priceToBook-TTM`, `tipranksAllConsensus` (StrongBuy/Buy/Hold/Sell/StrongSell), `tipranksAllUpside`, `tipranksAllTotalAnalysts`, `oneYearAnnualRevenueGrowthRate`, `netProfitMargin`, `sectorName`, price changes (`dailyPriceChange`,`weeklyPriceChange`,`monthlyPriceChange`,`threeMonthPriceChange`,`sixMonthPriceChange`).
- **`countryCode` = company domicile** (cleaner than the messy `exchangeName` values like "Regular Trading Hours - RTH", "Hong Kong Exchanges", "Stockholm  Stock Exchange"). USA+EU set is well-covered by ISO codes.
- **Duplicate listings share `isin`**: e.g. `NVDA` and `NVDA.RTH` both ISIN `US67066G1040`. Fundamentals (marketCap, volume, growth, margin) are identical across variants; `tipranksAll*` is populated on the canonical symbol but null on the `.RTH` variant; `popularityUniques` is higher on `.RTH`.
- **`assetClass=Crypto` still includes 152 dated futures** (`BTC.JUN26` … `BTC.JUN28`), so the dated-future exclusion is still required. Crypto rows carry `marketCapInUSD` and `daysSinceFirstTrade`; `isDelisted` is null → rely on `isBuyEnabled`.

## Design

### Config (`core/utils.py`)
Replace the exchange whitelist with a country whitelist + quality gates:
- **`universe_countries: tuple[str, ...]`** default USA+EU: `("US","GB","DE","FR","NL","IT","ES","CH","SE","DK","NO","FI","IE","BE","AT","PT","LU")`. Env `UNIVERSE_COUNTRIES` (comma-separated, upper-cased).
- **`universe_stock_min_market_cap: float = 2_000_000_000`** — env `UNIVERSE_STOCK_MIN_MARKET_CAP`. Used as the discover `marketCapMin` server filter AND a client-side guard.
- **`universe_stock_min_dollar_volume: float = 5_000_000`** — env `UNIVERSE_STOCK_MIN_DOLLAR_VOLUME`. Avg daily $ volume floor (`averageDailyVolumeLast3Months × currentRate`).
- **`universe_crypto_min_market_cap: float = 100_000_000`** — env `UNIVERSE_CRYPTO_MIN_MARKET_CAP`. Drops microcap coins.
- Keep `universe_stock_shortlist=300`, `universe_crypto_shortlist=150`.
- **Remove** `universe_stock_exchanges` / `DEFAULT_UNIVERSE_STOCK_EXCHANGES` (superseded by `universe_countries`). Keep `EToroClient.list_exchanges` (harmless, unused) or remove its use.

### `EToroClient.discover_instruments(asset_class)` (rewrite)
- Map asset_class → `assetClass` param: STOCK→"Stocks", CRYPTO→"Crypto".
- Per page call `GET /api/v1/instruments/discover` with:
  - `assetClass`, `page`, `pageSize=200`, `fields=<projection>`,
  - STOCK: `marketCapMin=<universe_stock_min_market_cap>`, `sort=-marketCap`;
  - CRYPTO: `sort=-popularityUniques`.
- `fields` projection (one string): `symbol,isin,displayName,assetClass,exchangeName,countryCode,marketCapInUSD,currentRate,popularityUniques,isBuyEnabled,isDelisted,daysSinceFirstTrade,averageDailyVolumeLast3Months-TTM,tipranksAllConsensus,tipranksAllUpside,tipranksAllTotalAnalysts,oneYearAnnualRevenueGrowthRate,netProfitMargin,dailyPriceChange,weeklyPriceChange,monthlyPriceChange,threeMonthPriceChange,sixMonthPriceChange`.
- Paginate until a short/empty page or a global cap `DISCOVER_MAX_ITEMS` (stocks 2500; crypto 1000).
- Skip rows with no `symbol` or no `instrumentId`. Dedupe by symbol within the fetch.
- Normalized row dict keys:
  `symbol, name(displayName), isin, instrument_id, asset_class(assetClass), exchange_name, country_code, tradable(=isBuyEnabled and not isDelisted), delisted(bool(isDelisted)), market_cap(marketCapInUSD), current_rate, avg_daily_volume(averageDailyVolumeLast3Months-TTM), dollar_volume(=avg_daily_volume*current_rate when both present else None), days_since_first_trade, popularity(popularityUniques int), analyst_consensus(str), analyst_upside(float), analyst_count(int), revenue_growth(oneYearAnnualRevenueGrowthRate), net_margin(netProfitMargin), price_change_1d/1w/1m/3m/6m, fractionable=False, status="active"`.
- Cache mapping via `upsert_instrument_mapping(db, symbol, instrument_id, "STOCK"|"CRYPTO", name, tradable)`.
- All numeric coercions via the safe `_discover_float` helper.

### `UniverseManager` changes
**ISIN dedup** `_dedupe_by_isin(rows)`:
- Group rows with a non-empty `isin`; rows with empty isin pass through untouched.
- Per group: choose representative = highest `popularity`; then for any field in `{analyst_consensus, analyst_upside, analyst_count, market_cap, dollar_volume, days_since_first_trade, revenue_growth, net_margin}` that is None/0 on the representative, fill from a sibling that has it. Keep representative's `symbol`/`instrument_id`.

**Cheap filter** `_passes_cheap_filter(category, asset)` (drop the exchange-whitelist arg):
- common: `tradable` true, not `delisted`, non-empty symbol.
- STOCK: `country_code` in `universe_countries`; `market_cap >= universe_stock_min_market_cap` (drops null marketCap, e.g. HK rows); `dollar_volume is not None and dollar_volume >= universe_stock_min_dollar_volume`; not ETF/non-common/shell by name.
- CRYPTO: not `_is_dated_future(symbol)`; `instrument_type` not containing "futur"; if `market_cap` is not None, `market_cap >= universe_crypto_min_market_cap` (keep if marketCap missing).

**Quality-composite score** `_cheap_prefilter_score(asset)` — replaces popularity+momentum:
```
liquidity = log10(max(dollar_volume,1)) * 6.0            # dominant, established turnover
size      = log10(max(market_cap,1))  * 3.0
consensus_map = {STRONGBUY:2, BUY:1, HOLD:0, SELL:-1, STRONGSELL:-2}   # case-insensitive, default 0
conf      = min(analyst_count or 0, 15) / 15.0
analyst   = (consensus_map.get(consensus,0)*6.0 + clamp(upside, -20, 40)*0.25) * conf
quality   = clamp(revenue_growth, -25, 50)*0.15 + clamp(net_margin, -20, 40)*0.20
m1m=clamp(price_change_1m,-25,25); m3m=clamp(price_change_3m,-40,40); m6m=clamp(price_change_6m,-60,60)
momentum  = (m1m*0.10 + m3m*0.10 + m6m*0.05)             # light, bounded
daily=abs(price_change_1d or 0); pump_penalty = max(daily-12,0)*0.30
score = round(liquidity + size + analyst + quality + momentum - pump_penalty, 4)
```
(`clamp(x,lo,hi)=max(lo,min(hi,x))`; all reads via `_safe_float`/defaults.)

**`_build_cheap_shortlist`** — call `discover_instruments`, `_dedupe_by_isin`, then pin current-universe symbols, filter the rest via `_passes_cheap_filter`, score, sort desc, cap to shortlist (stocks 300 / crypto 150). (Signature loses the `exchange_whitelist` param.)

**`_select_etoro_universe`** — unchanged structure (discover-first, per-category legacy fallback, then enrich→write→select). Drop the `_resolve_exchange_whitelist` call; `_build_cheap_shortlist` no longer takes a whitelist.

### Out of scope / notes
- Bars are still fetched for the final shortlist (technical metrics + GPT) — unchanged.
- `peRatio`/`beta`/`priceToBook` are available but not used in the score (YAGNI; can add later).
- The price-change unit (percent vs fraction) is unverified but only affects the light momentum term; clamps bound its influence.
- Legacy fallback (`list_assets`) keeps the dated-future guard for crypto.

## Testing
- `discover_instruments`: mock paginated discover responses with the real field names; assert `assetClass`/`marketCapMin`/`sort`/`fields` params, normalization (incl. `tradable=isBuyEnabled and not isDelisted`, `dollar_volume` computed), pagination stop + cap, symbol dedup.
- `_dedupe_by_isin`: two variants same ISIN (one with analyst data + low pop, one without + high pop) → one row, highest-pop symbol, analyst fields filled from sibling. Empty-isin rows pass through.
- `_passes_cheap_filter`: stock country/marketcap/dollar-volume/ETF rules; crypto futures + microcap rules.
- `_cheap_prefilter_score`: higher for liquid/large/StrongBuy vs small/Sell; pump penalty lowers a 1d-spiked name; analyst term scales with analyst_count.
- `_build_cheap_shortlist`: dedup + filter + cap + pin.
- Wiring/fallback tests from v1 still pass (per-category fallback, discover-empty, raise).
