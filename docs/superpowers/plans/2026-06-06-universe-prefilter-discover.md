# Universe Prefilter (discover-based) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the eToro universe selection's "download the whole catalog → fetch bars for all ~10527 → prefilter" flow with a cheap metadata prefilter (via `/instruments/discover`) that fetches bars only for a ~300-stock / ~150-crypto shortlist, restricts stocks to USA+EU exchanges, and excludes crypto dated futures.

**Architecture:** A new `EToroClient.discover_instruments` pulls popularity/momentum/tradability/exchange/price metadata without bar fetches; `EToroClient.list_exchanges` maps exchange IDs to names. `UniverseManager` gains a cheap-filter + score + shortlist stage that runs before the existing (unchanged) bar-enrichment → GPT-dossier pipeline. If discover is unavailable, it falls back to the current full-scan behavior.

**Tech Stack:** Python 3.14, stdlib `unittest` + `unittest.mock`, eToro REST API, SQLite (`instrument_map`). Tests run in Docker.

---

## Conventions

**Working directory:** the git worktree root `/home/mattia/docker/projects/trading/.claude/worktrees/universe-prefilter` (branch `worktree-universe-prefilter`, based on `dev-2.0`).

**Test command (source-mounted, no rebuild needed):**
```bash
docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.<module> -v
```
The compose service is named `backend` and does NOT mount source by default, so the `-v "$PWD/backend:/app"` bind is required to test edited code. Run from the worktree root.

**Full test suite:**
```bash
docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest discover -s tests -v
```

**Commit cadence:** one commit per task (after its tests pass). End every commit message with:
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

---

## File Structure

- **Modify** `backend/core/utils.py` — add `DEFAULT_UNIVERSE_STOCK_EXCHANGES` constant, three `AppConfig` fields, and their env loading in `load_config`.
- **Modify** `backend/clients/etoro_client.py` — add `DISCOVER_PAGE_SIZE`/`DISCOVER_MAX_ITEMS` constants, an `_exchange_cache` init attribute, and methods `list_exchanges`, `discover_instruments`, `_discover_float`.
- **Modify** `backend/services/universe_manager.py` — add `import re`, helpers (`_is_dated_future`, `_asset_name`, `_resolve_exchange_whitelist`, `_cheap_prefilter_score`, `_passes_cheap_filter`, `_build_cheap_shortlist`), update the three `_looks_like_*` helpers to use `_asset_name`, and rewire `_select_etoro_universe`.
- **Modify** `backend/.env.example` — document the three new env vars.
- **Test** `backend/tests/test_etoro_config.py` — config env loading.
- **Test** `backend/tests/test_etoro_client.py` — `list_exchanges`, `discover_instruments`.
- **Test** `backend/tests/test_etoro_universe.py` — cheap helpers, shortlist, fallback.

---

## Task 1: Config fields for exchanges + shortlist sizes

**Files:**
- Modify: `backend/core/utils.py`
- Test: `backend/tests/test_etoro_config.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_etoro_config.py`, inside `class EtoroConfigTests` (after `test_load_config_reads_etoro_env`):

```python
    def test_universe_defaults(self):
        config = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b")
        self.assertEqual(config.universe_stock_shortlist, 300)
        self.assertEqual(config.universe_crypto_shortlist, 150)
        self.assertIn("NASDAQ", config.universe_stock_exchanges)
        self.assertIn("MILAN", config.universe_stock_exchanges)

    def test_load_config_reads_universe_env(self):
        env = {
            "OPENAI_API_KEY": "o",
            "UNIVERSE_STOCK_SHORTLIST": "120",
            "UNIVERSE_CRYPTO_SHORTLIST": "40",
            "UNIVERSE_STOCK_EXCHANGES": "NASDAQ, NYSE , London",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.universe_stock_shortlist, 120)
        self.assertEqual(config.universe_crypto_shortlist, 40)
        self.assertEqual(config.universe_stock_exchanges, ("NASDAQ", "NYSE", "London"))

    def test_load_config_universe_exchanges_default_when_unset(self):
        env = {"OPENAI_API_KEY": "o"}
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertIn("NASDAQ", config.universe_stock_exchanges)
        self.assertEqual(config.universe_stock_shortlist, 300)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_config -v`
Expected: FAIL with `AttributeError: 'AppConfig' object has no attribute 'universe_stock_shortlist'`.

- [ ] **Step 3: Add the module-level default constant**

In `backend/core/utils.py`, immediately after the `SETTINGS_RESTART_REQUIRED_KEYS` block (around line 58), add:

```python
# Default whitelist of exchange-name fragments (case-insensitive substring match
# against eToro's exchangeDescription) used to scope the stock universe to USA +
# major EU venues. Override via the UNIVERSE_STOCK_EXCHANGES env var.
DEFAULT_UNIVERSE_STOCK_EXCHANGES: tuple[str, ...] = (
    "NASDAQ", "NYSE", "NEW YORK", "ARCA", "AMERICAN STOCK",
    "LONDON", "LSE", "XETRA", "FRANKFURT", "EURONEXT", "PARIS",
    "AMSTERDAM", "BRUSSELS", "BORSA ITALIANA", "MILAN",
    "SIX", "SWISS", "ZURICH", "BME", "MADRID",
)
```

- [ ] **Step 4: Add the dataclass fields**

In `backend/core/utils.py`, inside `class AppConfig`, after the `risk_tolerance: int = 5` line (around line 74), add:

```python
    universe_stock_exchanges: tuple[str, ...] = DEFAULT_UNIVERSE_STOCK_EXCHANGES
    universe_stock_shortlist: int = 300
    universe_crypto_shortlist: int = 150
```

- [ ] **Step 5: Wire env loading**

In `backend/core/utils.py`, inside `load_config`, after the `risk_tolerance=...` line (around line 173), add:

```python
        universe_stock_exchanges=tuple(
            fragment.strip()
            for fragment in os.getenv("UNIVERSE_STOCK_EXCHANGES", "").split(",")
            if fragment.strip()
        ) or DEFAULT_UNIVERSE_STOCK_EXCHANGES,
        universe_stock_shortlist=max(10, int(os.getenv("UNIVERSE_STOCK_SHORTLIST", "300"))),
        universe_crypto_shortlist=max(10, int(os.getenv("UNIVERSE_CRYPTO_SHORTLIST", "150"))),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_config -v`
Expected: PASS (all config tests, including the three new ones).

- [ ] **Step 7: Commit**

```bash
git add backend/core/utils.py backend/tests/test_etoro_config.py
git commit -m "feat(universe): add exchange whitelist + shortlist size config

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `EToroClient.list_exchanges`

**Files:**
- Modify: `backend/clients/etoro_client.py`
- Test: `backend/tests/test_etoro_client.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_etoro_client.py`. Reuse the existing module-level `make_client` helper. Add a new test class at the end of the file (before the `if __name__` guard):

```python
class EToroDiscoverTests(unittest.TestCase):
    def test_list_exchanges_maps_id_to_description(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"exchangeInfo": [
            {"exchangeID": 4, "exchangeDescription": "NASDAQ"},
            {"exchangeID": 5, "exchangeDescription": "NYSE"},
            {"exchangeID": None, "exchangeDescription": "ignored"},
        ]})
        out = client.list_exchanges()
        self.assertEqual(out[4], "NASDAQ")
        self.assertEqual(out[5], "NYSE")
        self.assertNotIn(None, out)

    def test_list_exchanges_is_cached(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"exchangeInfo": [
            {"exchangeID": 4, "exchangeDescription": "NASDAQ"},
        ]})
        client.list_exchanges()
        client.list_exchanges()
        self.assertEqual(session.request.call_count, 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroDiscoverTests -v`
Expected: FAIL with `AttributeError: 'EToroClient' object has no attribute 'list_exchanges'`.

- [ ] **Step 3: Add the cache attribute in `__init__`**

In `backend/clients/etoro_client.py`, find the `EToroClient.__init__` method and add this line at the end of the constructor body (alongside the other instance attributes):

```python
        self._exchange_cache: dict[int, str] | None = None
```

- [ ] **Step 4: Add the `list_exchanges` method**

In `backend/clients/etoro_client.py`, add this method to `EToroClient` (place it just before `_instrument_type_ids`, around line 313):

```python
    def list_exchanges(self) -> dict[int, str]:
        """Return ``{exchangeID: exchangeDescription}`` (cached for the run)."""
        if self._exchange_cache is not None:
            return self._exchange_cache
        payload = self._request("GET", "/api/v1/market-data/exchanges")
        out: dict[int, str] = {}
        for row in payload.get("exchangeInfo") or []:
            exchange_id = row.get("exchangeID")
            if exchange_id is None:
                continue
            out[int(exchange_id)] = str(row.get("exchangeDescription") or "")
        self._exchange_cache = out
        return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroDiscoverTests -v`
Expected: PASS for the two `test_list_exchanges_*` tests.

- [ ] **Step 6: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add cached list_exchanges()

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `EToroClient.discover_instruments`

**Files:**
- Modify: `backend/clients/etoro_client.py`
- Test: `backend/tests/test_etoro_client.py`

- [ ] **Step 1: Write the failing test**

Add to `class EToroDiscoverTests` in `backend/tests/test_etoro_client.py`:

```python
    def _types_resp(self):
        return make_response(200, {"instrumentTypes": [
            {"instrumentTypeID": 5, "instrumentTypeDescription": "Stocks"},
            {"instrumentTypeID": 10, "instrumentTypeDescription": "Crypto"},
            {"instrumentTypeID": 6, "instrumentTypeDescription": "ETF"},
        ]})

    def test_discover_instruments_normalizes_and_filters_internal(self):
        client, session = make_client()
        session.request.side_effect = [
            self._types_resp(),
            make_response(200, {"page": 1, "pageSize": 200, "totalItems": 2, "items": [
                {"instrumentId": 101, "displayname": "Apple", "symbol": "AAPL",
                 "instrumentTypeID": 5, "instrumentType": "Stocks", "exchangeID": 4,
                 "isCurrentlyTradable": True, "isBuyEnabled": True, "isDelisted": False,
                 "currentRate": 200.0, "popularityUniques": 5000,
                 "dailyPriceChange": 1.0, "weeklyPriceChange": 2.0,
                 "monthlyPriceChange": 3.0, "threeMonthPriceChange": 4.0,
                 "sixMonthPriceChange": 5.0},
                {"instrumentId": 999, "displayname": "Hidden", "symbol": "HID",
                 "isInternalInstrument": True},
            ]}),
        ]
        rows = client.discover_instruments("STOCK")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["symbol"], "AAPL")
        self.assertEqual(row["instrument_id"], 101)
        self.assertEqual(row["exchange_id"], 4)
        self.assertTrue(row["tradable"])
        self.assertEqual(row["popularity"], 5000)
        self.assertEqual(row["current_rate"], 200.0)
        self.assertEqual(row["price_change_3m"], 4.0)
        # discover call carried the sort + type filter
        discover_kwargs = session.request.call_args_list[1].kwargs
        self.assertEqual(discover_kwargs["params"]["sort"], "-popularityUniques")
        self.assertEqual(discover_kwargs["params"]["instrumentTypeID"], 5)

    def test_discover_instruments_derives_tradable_false(self):
        client, session = make_client()
        session.request.side_effect = [
            self._types_resp(),
            make_response(200, {"page": 1, "pageSize": 200, "totalItems": 1, "items": [
                {"instrumentId": 7, "displayname": "X", "symbol": "X",
                 "isCurrentlyTradable": True, "isBuyEnabled": False},
            ]}),
        ]
        rows = client.discover_instruments("STOCK")
        self.assertFalse(rows[0]["tradable"])

    def test_discover_instruments_stops_on_short_page(self):
        client, session = make_client()
        session.request.side_effect = [
            self._types_resp(),
            make_response(200, {"page": 1, "pageSize": 200, "totalItems": 1, "items": [
                {"instrumentId": 1, "displayname": "A", "symbol": "A",
                 "isCurrentlyTradable": True},
            ]}),
        ]
        rows = client.discover_instruments("STOCK")
        self.assertEqual(len(rows), 1)
        # only types + one discover page (no page 2 because the page was short)
        self.assertEqual(session.request.call_count, 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroDiscoverTests -v`
Expected: FAIL with `AttributeError: 'EToroClient' object has no attribute 'discover_instruments'`.

- [ ] **Step 3: Add the pagination constants**

In `backend/clients/etoro_client.py`, add these two constants to `EToroClient` next to `_ASSET_CLASS_HINTS` (around line 307):

```python
    DISCOVER_PAGE_SIZE = 200
    DISCOVER_MAX_ITEMS = 4000
```

- [ ] **Step 4: Add `_discover_float` and `discover_instruments`**

In `backend/clients/etoro_client.py`, add these methods to `EToroClient` (place them right after `list_assets`, around line 347):

```python
    @staticmethod
    def _discover_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def discover_instruments(self, asset_class: str) -> list[dict[str, Any]]:
        """Cheap metadata discovery for the universe prefilter.

        Uses ``/api/v1/instruments/discover`` (popularity-sorted, paginated) to
        return rich per-instrument metadata WITHOUT fetching any price bars.
        """
        hints = self._ASSET_CLASS_HINTS.get(str(asset_class).upper(), (str(asset_class).lower(),))
        category = "CRYPTO" if "crypto" in hints else "STOCK"
        type_ids = self._instrument_type_ids(hints)
        if not type_ids:
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for type_id in type_ids:
            collected = 0
            page = 1
            while collected < self.DISCOVER_MAX_ITEMS:
                payload = self._request(
                    "GET",
                    "/api/v1/instruments/discover",
                    params={
                        "page": page,
                        "pageSize": self.DISCOVER_PAGE_SIZE,
                        "sort": "-popularityUniques",
                        "instrumentTypeID": type_id,
                        "isDelisted": "false",
                        "isCurrentlyTradable": "true",
                    },
                )
                items = payload.get("items") or []
                if not items:
                    break
                for row in items:
                    if row.get("isInternalInstrument") or row.get("isHiddenFromClient"):
                        continue
                    symbol = str(row.get("symbol") or "").upper().strip()
                    if not symbol or symbol in seen or row.get("instrumentId") is None:
                        continue
                    seen.add(symbol)
                    instrument_id = int(row["instrumentId"])
                    name = str(row.get("displayname") or "")
                    tradable = bool(row.get("isCurrentlyTradable")) and bool(row.get("isBuyEnabled", True))
                    out.append({
                        "symbol": symbol,
                        "name": name,
                        "status": "active",
                        "tradable": tradable,
                        "fractionable": False,
                        "instrument_id": instrument_id,
                        "instrument_type_id": int(row.get("instrumentTypeID") or type_id),
                        "instrument_type": str(row.get("instrumentType") or ""),
                        "exchange_id": (int(row["exchangeID"]) if row.get("exchangeID") is not None else None),
                        "delisted": bool(row.get("isDelisted")),
                        "current_rate": self._discover_float(row.get("currentRate")),
                        "popularity": int(row.get("popularityUniques") or 0),
                        "price_change_1d": self._discover_float(row.get("dailyPriceChange")),
                        "price_change_1w": self._discover_float(row.get("weeklyPriceChange")),
                        "price_change_1m": self._discover_float(row.get("monthlyPriceChange")),
                        "price_change_3m": self._discover_float(row.get("threeMonthPriceChange")),
                        "price_change_6m": self._discover_float(row.get("sixMonthPriceChange")),
                    })
                    collected += 1
                    try:
                        upsert_instrument_mapping(self.config.db_market_data, symbol, instrument_id, category, name, tradable)
                    except Exception:
                        self.logger.debug("Failed to cache instrument mapping for %s", symbol)
                if len(items) < self.DISCOVER_PAGE_SIZE:
                    break
                page += 1
        return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client.EToroDiscoverTests -v`
Expected: PASS (all `EToroDiscoverTests`).

- [ ] **Step 6: Run the full client test module (regression)**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_client -v`
Expected: PASS (existing `list_assets` and other tests unaffected).

- [ ] **Step 7: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add discover_instruments() metadata prefilter source

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: UniverseManager cheap helpers (futures, name, score, exchange whitelist)

**Files:**
- Modify: `backend/services/universe_manager.py`
- Test: `backend/tests/test_etoro_universe.py`

- [ ] **Step 1: Write the failing test**

Add a new test class at the end of `backend/tests/test_etoro_universe.py` (before the `if __name__` guard). It builds a manager with a mock broker; reuse the `AppConfig` construction pattern already used in the file:

```python
class CheapPrefilterHelperTests(unittest.TestCase):
    def _manager(self):
        from services.universe_manager import UniverseManager
        config = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
            etoro_account_type="demo", weekly_universe_stocks=2, weekly_universe_crypto=2,
        )
        gpt = Mock()
        broker = Mock()
        return UniverseManager(config, logging.getLogger("t"), {PE: broker}, gpt), broker

    def test_is_dated_future(self):
        from services.universe_manager import UniverseManager
        for sym in ("BTC.MAY26", "BTC.JUN26", "ETH.DEC25"):
            self.assertTrue(UniverseManager._is_dated_future(sym), sym)
        for sym in ("ETH.SPOT", "HYPE", "JTO", "BTC", "BTC.X"):
            self.assertFalse(UniverseManager._is_dated_future(sym), sym)

    def test_asset_name_handles_dict_and_object(self):
        from services.universe_manager import UniverseManager
        self.assertEqual(UniverseManager._asset_name({"name": "Apple ETF"}), "apple etf")
        obj = Mock()
        obj.name = "Apple Inc"
        self.assertEqual(UniverseManager._asset_name(obj), "apple inc")

    def test_cheap_score_rewards_popularity(self):
        manager, _ = self._manager()
        high = manager._cheap_prefilter_score({"popularity": 100000, "price_change_3m": 10.0})
        low = manager._cheap_prefilter_score({"popularity": 10, "price_change_3m": 10.0})
        self.assertGreater(high, low)

    def test_resolve_exchange_whitelist_matches_patterns(self):
        manager, broker = self._manager()
        broker.list_exchanges.return_value = {
            4: "NASDAQ", 5: "NYSE", 80: "Borsa Italiana", 99: "Tokyo Stock Exchange",
        }
        wanted = manager._resolve_exchange_whitelist(broker)
        self.assertEqual(wanted, {4, 5, 80})

    def test_resolve_exchange_whitelist_none_on_error(self):
        manager, broker = self._manager()
        broker.list_exchanges.side_effect = Exception("boom")
        self.assertIsNone(manager._resolve_exchange_whitelist(broker))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_universe.CheapPrefilterHelperTests -v`
Expected: FAIL with `AttributeError: ... '_is_dated_future'` (and the others).

- [ ] **Step 3: Add `import re`**

In `backend/services/universe_manager.py`, add `import re` to the imports block (after `import math`, around line 10).

- [ ] **Step 4: Add the helpers and update name helpers**

In `backend/services/universe_manager.py`, add these to `class UniverseManager`. Put the regex constant near the top of the class body (after the numeric class constants, around line 47):

```python
    _DATED_FUTURE_RE = re.compile(r"\.[A-Z]{3}\d{2}$")
```

Add these methods (place them next to the other `@staticmethod` helpers, e.g. after `_normalize_symbol`, around line 79):

```python
    @classmethod
    def _is_dated_future(cls, symbol: Any) -> bool:
        text = str(symbol or "").upper().strip()
        return bool(cls._DATED_FUTURE_RE.search(text))

    @staticmethod
    def _asset_name(asset: object) -> str:
        if isinstance(asset, dict):
            return str(asset.get("name") or "").lower()
        return str(getattr(asset, "name", "") or "").lower()
```

Now update the three existing `_looks_like_*` helpers to use `_asset_name`. Replace their bodies' first line `name = str(getattr(asset, "name", "")).lower()` with `name = UniverseManager._asset_name(asset)`:

```python
    @staticmethod
    def _looks_like_etf(asset: object) -> bool:
        name = UniverseManager._asset_name(asset)
        return any(
            token in name
            for token in (
                " etf", " exchange traded fund", " fund", " etn", " etp",
                " index fund", " index trust", " trust",
            )
        )

    @staticmethod
    def _looks_like_non_common_stock(asset: object) -> bool:
        name = UniverseManager._asset_name(asset)
        return any(
            token in name
            for token in (
                " warrant", " rights", " right", " units", " unit",
                " depositary", " preferred", " redeemable",
            )
        )

    @staticmethod
    def _looks_like_shell_company(asset: object) -> bool:
        name = UniverseManager._asset_name(asset)
        return any(
            token in name
            for token in (
                " acquisition corp", " acquisition corporation",
                " blank check", " shell company",
                " special purpose acquisition", " spac",
            )
        )
```

Add the score and exchange-whitelist methods (place them next to `_candidate_prefilter_score`, around line 254):

```python
    def _cheap_prefilter_score(self, asset: dict[str, Any]) -> float:
        popularity = max(self._safe_float(asset.get("popularity")) or 0.0, 0.0)
        pop_score = math.log10(popularity + 1.0) * 12.0
        m1w = self._safe_float(asset.get("price_change_1w")) or 0.0
        m1m = self._safe_float(asset.get("price_change_1m")) or 0.0
        m3m = self._safe_float(asset.get("price_change_3m")) or 0.0
        m6m = self._safe_float(asset.get("price_change_6m")) or 0.0
        momentum = (
            (max(m1w, -15.0) * 0.15)
            + (max(m1m, -25.0) * 0.35)
            + (max(m3m, -40.0) * 0.30)
            + (max(m6m, -60.0) * 0.20)
        )
        daily = abs(self._safe_float(asset.get("price_change_1d")) or 0.0)
        spike_penalty = max(daily - 15.0, 0.0) * 0.20
        return round(pop_score + momentum - spike_penalty, 4)

    def _resolve_exchange_whitelist(self, broker: Any) -> set[int] | None:
        patterns = tuple(self.config.universe_stock_exchanges or ())
        if not patterns:
            return None
        try:
            exchanges = broker.list_exchanges()
        except Exception:
            self.logger.warning("Failed to fetch eToro exchanges; skipping exchange whitelist", exc_info=True)
            return None
        upper_patterns = [p.upper() for p in patterns]
        wanted: set[int] = set()
        for exchange_id, description in (exchanges or {}).items():
            text = str(description).upper()
            if any(pattern in text for pattern in upper_patterns):
                wanted.add(int(exchange_id))
        return wanted or None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_universe.CheapPrefilterHelperTests -v`
Expected: PASS.

- [ ] **Step 6: Run the full universe module (regression on name helpers)**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_universe -v`
Expected: PASS (existing tests still green after the `_looks_like_*` edits).

- [ ] **Step 7: Commit**

```bash
git add backend/services/universe_manager.py backend/tests/test_etoro_universe.py
git commit -m "feat(universe): add cheap prefilter helpers (futures, score, exchange whitelist)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `_passes_cheap_filter` + `_build_cheap_shortlist`

**Files:**
- Modify: `backend/services/universe_manager.py`
- Test: `backend/tests/test_etoro_universe.py`

- [ ] **Step 1: Write the failing test**

Add to `class CheapPrefilterHelperTests` in `backend/tests/test_etoro_universe.py`:

```python
    def _stock(self, symbol, exch=4, rate=100.0, pop=1000, name="Co", tradable=True, delisted=False):
        return {
            "symbol": symbol, "name": name, "tradable": tradable, "delisted": delisted,
            "exchange_id": exch, "current_rate": rate, "popularity": pop,
            "instrument_type": "Stocks",
            "price_change_1d": 0.0, "price_change_1w": 0.0,
            "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0,
        }

    def _crypto(self, symbol, pop=1000, itype="Crypto", tradable=True):
        return {
            "symbol": symbol, "name": symbol, "tradable": tradable, "delisted": False,
            "exchange_id": None, "current_rate": 1.0, "popularity": pop,
            "instrument_type": itype,
            "price_change_1d": 0.0, "price_change_1w": 0.0,
            "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0,
        }

    def test_passes_cheap_filter_stock_rules(self):
        manager, _ = self._manager()
        wl = {4, 5}
        self.assertTrue(manager._passes_cheap_filter("STOCK", self._stock("AAPL", exch=4), wl))
        # wrong exchange
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", exch=99), wl))
        # below price floor (STOCK_MIN_LAST_CLOSE = 5.0)
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", rate=1.0), wl))
        # not tradable
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", tradable=False), wl))
        # ETF by name
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", name="Big Index Fund"), wl))

    def test_passes_cheap_filter_crypto_excludes_futures(self):
        manager, _ = self._manager()
        self.assertTrue(manager._passes_cheap_filter("CRYPTO", self._crypto("ETH.SPOT"), None))
        self.assertTrue(manager._passes_cheap_filter("CRYPTO", self._crypto("HYPE"), None))
        self.assertFalse(manager._passes_cheap_filter("CRYPTO", self._crypto("BTC.MAY26"), None))
        self.assertFalse(manager._passes_cheap_filter("CRYPTO", self._crypto("X", itype="Crypto Futures"), None))

    def test_build_cheap_shortlist_stock_caps_and_filters(self):
        manager, broker = self._manager()
        manager.config.universe_stock_shortlist = 2
        broker.list_exchanges.return_value = {4: "NASDAQ", 99: "Tokyo"}
        broker.discover_instruments.return_value = [
            self._stock("AAA", exch=4, pop=10),
            self._stock("BBB", exch=4, pop=9000),     # higher popularity → ranks first
            self._stock("CCC", exch=4, pop=5000),
            self._stock("TKO", exch=99, pop=99999),    # excluded: exchange not whitelisted
        ]
        wl = manager._resolve_exchange_whitelist(broker)
        shortlist = manager._build_cheap_shortlist(broker, "STOCK", [], wl)
        symbols = [a["symbol"] for a in shortlist]
        self.assertEqual(len(shortlist), 2)
        self.assertEqual(symbols, ["BBB", "CCC"])  # sorted by score (popularity) desc, capped
        self.assertNotIn("TKO", symbols)

    def test_build_cheap_shortlist_pins_preferred(self):
        manager, broker = self._manager()
        manager.config.universe_stock_shortlist = 2
        broker.list_exchanges.return_value = {4: "NASDAQ"}
        broker.discover_instruments.return_value = [
            self._stock("AAA", exch=4, pop=9000),
            self._stock("BBB", exch=4, pop=8000),
            self._stock("KEEP", exch=4, pop=1),  # low pop but pinned
        ]
        wl = manager._resolve_exchange_whitelist(broker)
        shortlist = manager._build_cheap_shortlist(broker, "STOCK", ["KEEP"], wl)
        symbols = [a["symbol"] for a in shortlist]
        self.assertIn("KEEP", symbols)

    def test_build_cheap_shortlist_crypto_drops_futures(self):
        manager, broker = self._manager()
        manager.config.universe_crypto_shortlist = 10
        broker.discover_instruments.return_value = [
            self._crypto("ETH.SPOT", pop=100),
            self._crypto("BTC.MAY26", pop=99999),
            self._crypto("HYPE", pop=50),
        ]
        shortlist = manager._build_cheap_shortlist(broker, "CRYPTO", [], None)
        symbols = [a["symbol"] for a in shortlist]
        self.assertIn("ETH.SPOT", symbols)
        self.assertIn("HYPE", symbols)
        self.assertNotIn("BTC.MAY26", symbols)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_universe.CheapPrefilterHelperTests -v`
Expected: FAIL with `AttributeError: ... '_passes_cheap_filter'`.

- [ ] **Step 3: Add the two methods**

In `backend/services/universe_manager.py`, add these methods to `class UniverseManager` (place them right after `_resolve_exchange_whitelist` from Task 4):

```python
    def _passes_cheap_filter(
        self,
        category: str,
        asset: dict[str, Any],
        exchange_whitelist: set[int] | None,
    ) -> bool:
        if not asset.get("tradable") or asset.get("delisted"):
            return False
        symbol = self._normalize_symbol(asset.get("symbol"))
        if not symbol:
            return False
        if category == "STOCK":
            if (
                self._looks_like_etf(asset)
                or self._looks_like_non_common_stock(asset)
                or self._looks_like_shell_company(asset)
            ):
                return False
            if exchange_whitelist is not None:
                exchange_id = asset.get("exchange_id")
                if exchange_id is None or int(exchange_id) not in exchange_whitelist:
                    return False
            last = self._safe_float(asset.get("current_rate"))
            if last is not None and last < self.STOCK_MIN_LAST_CLOSE:
                return False
            return True
        # CRYPTO
        if self._is_dated_future(symbol):
            return False
        if "futur" in str(asset.get("instrument_type") or "").lower():
            return False
        return True

    def _build_cheap_shortlist(
        self,
        broker: Any,
        category: str,
        preferred_symbols: list[str],
        exchange_whitelist: set[int] | None,
    ) -> list[dict[str, Any]]:
        candidates = broker.discover_instruments(category)
        if not candidates:
            return []
        candidates = self._dedupe_payload_by_symbol(candidates)
        preferred_set = {self._normalize_symbol(symbol) for symbol in preferred_symbols}
        pinned: list[dict[str, Any]] = []
        pinned_symbols: set[str] = set()
        pool: list[dict[str, Any]] = []
        for asset in candidates:
            symbol = self._normalize_symbol(asset.get("symbol"))
            if symbol in preferred_set and symbol not in pinned_symbols:
                pinned_symbols.add(symbol)
                pinned.append(asset)
                continue
            if not self._passes_cheap_filter(category, asset, exchange_whitelist):
                continue
            scored = dict(asset)
            scored["prefilter_score"] = self._cheap_prefilter_score(scored)
            pool.append(scored)
        pool.sort(
            key=lambda asset: (
                self._safe_float(asset.get("prefilter_score")) or float("-inf"),
                str(asset.get("symbol", "")),
            ),
            reverse=True,
        )
        limit = (
            self.config.universe_stock_shortlist
            if category == "STOCK"
            else self.config.universe_crypto_shortlist
        )
        shortlist = (pinned + pool)[: max(limit, len(pinned))]
        self.logger.info(
            "Universe cheap prefilter for %s reduced %s discovered to %s shortlist before bars",
            category,
            len(candidates),
            len(shortlist),
        )
        return shortlist
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_universe.CheapPrefilterHelperTests -v`
Expected: PASS (all cheap-filter and shortlist tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/universe_manager.py backend/tests/test_etoro_universe.py
git commit -m "feat(universe): cheap-stage filter + shortlist builder

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Rewire `_select_etoro_universe` with discover-first + legacy fallback

**Files:**
- Modify: `backend/services/universe_manager.py:649-679` (the `_select_etoro_universe` method)
- Test: `backend/tests/test_etoro_universe.py`

- [ ] **Step 1: Write the failing test**

Add a new test class at the end of `backend/tests/test_etoro_universe.py`:

```python
class SelectEtoroUniverseWiringTests(unittest.TestCase):
    def _manager(self, broker):
        from services.universe_manager import UniverseManager
        config = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
            etoro_account_type="demo", weekly_universe_stocks=1, weekly_universe_crypto=1,
            universe_stock_shortlist=5, universe_crypto_shortlist=5,
        )
        gpt = Mock()
        gpt.request_universe_symbol_dossier.side_effect = Exception("no gpt")
        gpt.request_universe_final_selection_from_dossiers.side_effect = Exception("no gpt")
        return UniverseManager(config, logging.getLogger("t"), {PE: broker}, gpt)

    def _empty_current(self):
        return {PE: {"STOCK": [], "CRYPTO": []}}

    def test_uses_discover_shortlist_when_available(self):
        broker = Mock()
        broker.list_exchanges.return_value = {4: "NASDAQ"}
        broker.discover_instruments.side_effect = lambda cat: (
            [{"symbol": "AAPL", "name": "Apple", "tradable": True, "delisted": False,
              "exchange_id": 4, "current_rate": 100.0, "popularity": 9000,
              "instrument_type": "Stocks", "price_change_1d": 0.0, "price_change_1w": 0.0,
              "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0}]
            if cat == "STOCK" else
            [{"symbol": "ETH.SPOT", "name": "Eth", "tradable": True, "delisted": False,
              "exchange_id": None, "current_rate": 1.0, "popularity": 9000,
              "instrument_type": "Crypto", "price_change_1d": 0.0, "price_change_1w": 0.0,
              "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0}]
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._empty_current())
        # discover path was used; legacy list_assets NOT called
        broker.list_assets.assert_not_called()
        self.assertEqual(result["STOCK"], ["AAPL"])
        self.assertEqual(result["CRYPTO"], ["ETH.SPOT"])

    def test_falls_back_to_list_assets_when_discover_raises(self):
        broker = Mock()
        broker.list_exchanges.return_value = {4: "NASDAQ"}
        broker.discover_instruments.side_effect = Exception("discover down")
        broker.list_assets.side_effect = lambda cls: (
            [_asset("AAPL", "Apple")] if cls in ("US_EQUITY", "STOCK") else [_asset("BTC", "Bitcoin")]
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._empty_current())
        broker.list_assets.assert_called()  # legacy path engaged
        self.assertEqual(result["STOCK"], ["AAPL"])
        self.assertEqual(result["CRYPTO"], ["BTC"])

    def test_falls_back_when_discover_empty(self):
        broker = Mock()
        broker.list_exchanges.return_value = {4: "NASDAQ"}
        broker.discover_instruments.return_value = []
        broker.list_assets.side_effect = lambda cls: (
            [_asset("AAPL", "Apple")] if cls in ("US_EQUITY", "STOCK") else [_asset("BTC", "Bitcoin")]
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._empty_current())
        broker.list_assets.assert_called()
        self.assertEqual(result["STOCK"], ["AAPL"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_universe.SelectEtoroUniverseWiringTests -v`
Expected: FAIL — `test_uses_discover_shortlist_when_available` fails because the current code calls `list_assets` (so `assert_not_called` raises), and discover is never used.

- [ ] **Step 3: Rewire `_select_etoro_universe`**

In `backend/services/universe_manager.py`, replace the body of `_select_etoro_universe` (currently lines 649-679) with:

```python
    def _select_etoro_universe(self, current_universe: ProviderUniverse) -> dict[str, list[str]]:
        broker = self.broker(PROVIDER_ETORO)
        if broker is None:
            return {}
        preferred = universe_for_provider(current_universe, PROVIDER_ETORO)
        try:
            base_stock_payload: list[dict[str, Any]] = []
            base_crypto_payload: list[dict[str, Any]] = []
            try:
                exchange_whitelist = self._resolve_exchange_whitelist(broker)
                base_stock_payload = self._build_cheap_shortlist(
                    broker, "STOCK", preferred.get("STOCK", []), exchange_whitelist
                )
                base_crypto_payload = self._build_cheap_shortlist(
                    broker, "CRYPTO", preferred.get("CRYPTO", []), None
                )
            except Exception:
                self.logger.warning(
                    "eToro discover prefilter failed; falling back to legacy full scan",
                    exc_info=True,
                )
            if not base_stock_payload and not base_crypto_payload:
                self.logger.warning("eToro discover prefilter empty; falling back to legacy full scan")
                base_stock_payload = self._get_etoro_stock_candidate_payload()
                base_crypto_payload = self._get_etoro_crypto_candidate_payload()

            full_stock_payload = self._enrich_payload_with_market_metrics(
                PROVIDER_ETORO, "STOCK", base_stock_payload, preferred.get("STOCK", [])
            )
            full_crypto_payload = self._enrich_payload_with_market_metrics(
                PROVIDER_ETORO, "CRYPTO", base_crypto_payload, preferred.get("CRYPTO", [])
            )
            self._write_candidate_lists(full_stock_payload, full_crypto_payload)

            stocks = self._select_category_universe(
                PROVIDER_ETORO, "STOCK", full_stock_payload,
                self.config.weekly_universe_stocks, self.STOCK_BATCH_SIZE, preferred.get("STOCK", []),
            )
            crypto = self._select_category_universe(
                PROVIDER_ETORO, "CRYPTO", full_crypto_payload,
                self.config.weekly_universe_crypto, self.CRYPTO_BATCH_SIZE, preferred.get("CRYPTO", []),
            )
        except Exception:
            self.logger.exception("Trading universe selection failed for eToro; keeping the previous valid universe")
            return {
                "STOCK": list(preferred.get("STOCK", [])),
                "CRYPTO": list(preferred.get("CRYPTO", [])),
            }
        return {"STOCK": stocks, "CRYPTO": crypto}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_universe.SelectEtoroUniverseWiringTests -v`
Expected: PASS (discover path used when available; legacy fallback on raise/empty).

- [ ] **Step 5: Run the full universe module (regression)**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest tests.test_etoro_universe -v`
Expected: PASS. NOTE: the pre-existing `EtoroUniverseSelectionTests` set up `broker = Mock()` whose `discover_instruments` returns a `Mock` (truthy, non-iterable). If any of those tests call `_select_etoro_universe` and now fail because `_build_cheap_shortlist` iterates a Mock, fix them by adding `self.broker.discover_instruments.side_effect = Exception("no discover")` in their `setUp` so they exercise the legacy fallback they were written for. Make that edit, re-run, and confirm green.

- [ ] **Step 6: Commit**

```bash
git add backend/services/universe_manager.py backend/tests/test_etoro_universe.py
git commit -m "feat(universe): discover-first selection with legacy full-scan fallback

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Document new env vars

**Files:**
- Modify: `backend/.env.example`

- [ ] **Step 1: Add documentation block**

Append to `backend/.env.example` (group it near the other universe/strategy settings; adjust placement to match the file's existing sectioning):

```bash
# --- Universe selection -------------------------------------------------------
# Stock universe is scoped to these exchanges (case-insensitive substring match
# against eToro exchange names). Comma-separated. Leave unset for the built-in
# USA + major-EU default list.
# UNIVERSE_STOCK_EXCHANGES=NASDAQ,NYSE,London,Xetra,Euronext,Borsa Italiana
# Candidates that reach the (expensive) bars + GPT stage. Higher = broader but
# slower. Defaults: 300 stocks / 150 crypto.
UNIVERSE_STOCK_SHORTLIST=300
UNIVERSE_CRYPTO_SHORTLIST=150
```

- [ ] **Step 2: Commit**

```bash
git add backend/.env.example
git commit -m "docs(env): document universe prefilter env vars

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Full suite + verification

- [ ] **Step 1: Run the whole backend test suite**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -m unittest discover -s tests -v`
Expected: PASS (no regressions across all modules).

- [ ] **Step 2: Smoke-check imports**

Run: `docker compose run --rm --no-deps -v "$PWD/backend:/app" -w /app backend python -c "import services.universe_manager, clients.etoro_client, core.utils; print('import ok')"`
Expected: prints `import ok`.

- [ ] **Step 3: Final review**

Re-read `_select_etoro_universe` and confirm: discover path is primary; legacy fallback fires on exception AND on empty; the bar-enrichment + `_select_category_universe` stages are byte-for-byte unchanged in behavior; `universe_candidates.log` still written.

---

## Self-Review Notes (author)

- **Spec coverage:** Task 1 → config (exchanges + shortlists); Task 2 → `list_exchanges`; Task 3 → `discover_instruments` (+ real `tradable`); Task 4 → futures/name/score/whitelist helpers; Task 5 → cheap filter + shortlist; Task 6 → rewire + fallback; Task 7 → env docs. All spec components mapped.
- **Type consistency:** discover row keys (`symbol`, `name`, `tradable`, `delisted`, `exchange_id`, `current_rate`, `popularity`, `price_change_1d/1w/1m/3m/6m`, `instrument_type`) are produced in Task 3 and consumed identically in Tasks 4–6. Method names stable: `_is_dated_future`, `_asset_name`, `_cheap_prefilter_score`, `_resolve_exchange_whitelist`, `_passes_cheap_filter`, `_build_cheap_shortlist`.
- **Known assumption:** discover `*PriceChange` unit (fraction vs percent) is unverified; it only affects relative ranking in the cheap prefilter, which is refined downstream by bar metrics + GPT, so correctness does not depend on it. Noted in spec "Out of scope".
- **Line numbers** (e.g. `649-679`) are from the `dev-2.0` snapshot and may drift as edits land; locate by symbol name if they don't match.
