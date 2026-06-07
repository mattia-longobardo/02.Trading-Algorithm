# eToro Migration — Plan 2: Market-Data Adapter & Account Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `EToroClient` the broker-agnostic consumer API the data/account layers already call (`get_bars`, `get_multi_bars`, `get_latest_price`, `get_latest_quote`, `get_open_position`), backed by a symbol→instrumentId resolution cache; make equity snapshots provider-aware; and wire the eToro broker into `main.py`.

**Architecture:** Additive. The data layer (`services/data_manager.py`) already dispatches `broker.get_bars(symbol, category, start)` to whichever broker owns a symbol, so making eToro work there only requires `EToroClient` to expose those exact method signatures. Internally each method resolves the ticker to an eToro `instrumentId` (cached in the `instrument_map` table from Plan 1, falling back to the live `resolve_instrument` lookup) and calls the raw endpoints built in Plan 1 (`get_candles_by_instrument`, `get_rate_by_instrument`, `list_open_positions`). Alpaca stays wired in parallel; it is removed in the cutover plan.

**Tech Stack:** Python 3.11+, `requests`, `unittest` under Docker (`docker run --rm -v <worktree>/backend:/app -w /app trading-backend:test python -m unittest ...`); host `python3 -m unittest` works for tests that don't need pandas/fastapi.

**Depends on:** Plan 1 (EToroClient raw methods, `instrument_map` table + `upsert_instrument_mapping`/`get_instrument_mapping`, eToro config).

**Consumer call sites this unblocks (verified):**
- `services/data_manager.py:97` → `broker.get_bars(symbol=…, category=…, start=…)`
- `services/universe_manager.py:252` → `broker.get_multi_bars(symbols, category, start)` (enrichment; discovery/`list_assets` is Plan 3)
- `services/trade_manager.py` → `broker.get_latest_price(symbol, category)`, `broker.get_latest_quote(symbol, category)`, `broker.get_open_position(symbol)` (consumed in Plan 4)
- `services/equity_snapshots.py` → `broker.get_account_equity()` (already added in Plan 1)

**Normalized shapes (from Plan 1, reused unchanged):** Bar dict `{symbol,timestamp,open,high,low,close,volume}`; Quote dict extended here to the broker-agnostic `{bid_price,ask_price,bid_size,ask_size}`; Position dict `{position_id,instrument_id,symbol,units,open_rate,amount,is_buy,leverage,stop_loss_rate,take_profit_rate}`.

---

## File Structure

| File | Responsibility |
|---|---|
| `clients/etoro_client.py` (modify) | Add `instrument_id_for_symbol` (cache+resolve+upsert) and the consumer adapter methods. |
| `services/equity_snapshots.py` (modify) | `record_snapshots_all` iterates `config.active_providers()` instead of the hardcoded `(PROVIDER_ALPACA,)`. |
| `main.py` (modify) | Instantiate `EToroClient` into the `brokers` dict when `config.etoro_enabled`. |
| `tests/test_etoro_client.py` (modify) | Append adapter test classes. |
| `tests/test_etoro_equity_snapshots.py` (create) | Provider-aware snapshot test. |

---

## Task 1: Symbol → instrumentId resolution cache

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append `EToroResolutionTests`)

The resolver checks the `instrument_map` cache first; on a miss it calls the live `resolve_instrument` and upserts the result so subsequent calls are cache hits. It reads/writes the market DB at `self.config.db_market_data`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
import tempfile
from pathlib import Path
from core.db import initialize_databases, upsert_instrument_mapping, get_instrument_mapping


class EToroResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "trades.sqlite")
        initialize_databases(self.market_db, self.trades_db)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def test_resolution_cache_hit_skips_http(self):
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple", True)
        client, session = self._client()
        self.assertEqual(client.instrument_id_for_symbol("AAPL"), 101)
        session.request.assert_not_called()

    def test_resolution_miss_calls_api_and_caches(self):
        client, session = self._client()
        session.request.return_value = make_response(200, {
            "instrumentId": 100000, "symbol": "BTC", "instrumentType": "Crypto",
            "displayname": "Bitcoin", "isCurrentlyTradable": True, "isBuyEnabled": True,
        })
        self.assertEqual(client.instrument_id_for_symbol("BTC"), 100000)
        # now cached
        cached = get_instrument_mapping(self.market_db, "BTC")
        self.assertEqual(cached["instrument_id"], 100000)
        self.assertEqual(cached["category"], "CRYPTO")

    def test_resolution_unknown_returns_none(self):
        client, session = self._client()
        session.request.return_value = make_response(404, {})
        self.assertIsNone(client.instrument_id_for_symbol("NOPE"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroResolutionTests -v`
Expected: FAIL with `AttributeError: ... 'instrument_id_for_symbol'`.

- [ ] **Step 3: Implement the resolver**

In `clients/etoro_client.py`, add the import near the top (after `from core.utils import AppConfig, retry`):

```python
from core.db import get_instrument_mapping, upsert_instrument_mapping
```

Then append to the `EToroClient` class, in the instruments section (after `resolve_instrument`):

```python
    def instrument_id_for_symbol(self, symbol: str) -> int | None:
        """Resolve a ticker to an eToro instrumentId, caching in instrument_map."""

        normalized = str(symbol).upper().strip()
        cached = get_instrument_mapping(self.config.db_market_data, normalized)
        if cached:
            return int(cached["instrument_id"])
        asset = self.resolve_instrument(normalized)
        if asset is None:
            return None
        upsert_instrument_mapping(
            self.config.db_market_data,
            asset["symbol"],
            asset["instrument_id"],
            asset["category"],
            asset["name"],
            asset["tradable"],
        )
        return asset["instrument_id"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroResolutionTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add symbol->instrumentId resolution cache"
```

---

## Task 2: `get_bars` and `get_multi_bars`

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append `EToroBarsTests`)

`get_bars(symbol, category, start, end=None)` resolves the instrument, asks for enough daily candles to cover `start` (one per day since `start`, capped at 1000), then filters to `timestamp >= start`. Signature matches `data_manager`'s call exactly. `get_multi_bars` loops (rate-limited inside each raw call) and returns `{symbol: [bars]}`, defaulting unknown symbols to `[]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
from datetime import datetime, timedelta, UTC


class EToroBarsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        initialize_databases(self.market_db, str(Path(self.tmp.name) / "t.sqlite"))
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple", True)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def _candles_response(self):
        return make_response(200, {"candles": [{"instrumentId": 101, "candles": [
            {"fromDate": "2026-01-01T00:00:00Z", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
            {"fromDate": "2026-06-01T00:00:00Z", "open": 2, "high": 3, "low": 1.5, "close": 2.5, "volume": 20},
        ]}]})

    def test_get_bars_filters_by_start(self):
        client, session = self._client()
        session.request.return_value = self._candles_response()
        start = datetime(2026, 3, 1, tzinfo=UTC)
        bars = client.get_bars(symbol="AAPL", category="STOCK", start=start)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 2.5)
        self.assertEqual(bars[0]["symbol"], "AAPL")

    def test_get_bars_unknown_symbol_returns_empty(self):
        client, session = self._client()
        session.request.return_value = make_response(404, {})
        bars = client.get_bars(symbol="NOPE", category="STOCK", start=datetime(2026, 1, 1, tzinfo=UTC))
        self.assertEqual(bars, [])

    def test_get_multi_bars_keys_every_requested_symbol(self):
        client, session = self._client()
        session.request.return_value = self._candles_response()
        out = client.get_multi_bars(["AAPL"], "STOCK", datetime(2025, 1, 1, tzinfo=UTC))
        self.assertIn("AAPL", out)
        self.assertEqual(len(out["AAPL"]), 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroBarsTests -v`
Expected: FAIL with `AttributeError: ... 'get_bars'`.

- [ ] **Step 3: Implement the bar adapters**

In `clients/etoro_client.py`, add to the imports from `core.utils`:

```python
from core.utils import AppConfig, parse_datetime, retry, utc_now
```

(Replace the existing `from core.utils import AppConfig, retry` line.)

Append to the `EToroClient` class in the market-data section:

```python
    _MAX_DAILY_CANDLES = 1000

    def _candles_count_for_start(self, start: Any) -> int:
        start_dt = parse_datetime(start) if isinstance(start, str) else start
        if start_dt is None:
            return self._MAX_DAILY_CANDLES
        days = (utc_now() - start_dt).days + 2
        return max(1, min(self._MAX_DAILY_CANDLES, days))

    def get_bars(self, symbol: str, category: str, start: Any, end: Any = None) -> list[dict[str, Any]]:
        normalized = str(symbol).upper().strip()
        instrument_id = self.instrument_id_for_symbol(normalized)
        if instrument_id is None:
            return []
        count = self._candles_count_for_start(start)
        rows = self.get_candles_by_instrument(instrument_id, normalized, count=count)
        start_dt = parse_datetime(start) if isinstance(start, str) else start
        end_dt = parse_datetime(end) if isinstance(end, str) else end
        out: list[dict[str, Any]] = []
        for row in rows:
            ts = parse_datetime(row["timestamp"])
            if ts is None:
                continue
            if start_dt is not None and ts < start_dt:
                continue
            if end_dt is not None and ts > end_dt:
                continue
            out.append(row)
        return out

    def get_multi_bars(
        self, symbols: list[str], category: str, start: Any, end: Any = None
    ) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for symbol in symbols:
            normalized = str(symbol).upper().strip()
            if not normalized:
                continue
            try:
                out[normalized] = self.get_bars(normalized, category, start, end)
            except Exception:
                self.logger.exception("eToro get_bars failed for %s", normalized)
                out[normalized] = []
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroBarsTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add get_bars/get_multi_bars data adapters"
```

---

## Task 3: `get_latest_price` and `get_latest_quote`

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append `EToroPriceTests`)

Signatures match the Alpaca client's: `get_latest_price(symbol, category) -> float` and `get_latest_quote(symbol, category) -> {bid_price, ask_price, bid_size, ask_size}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
class EToroPriceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        initialize_databases(self.market_db, str(Path(self.tmp.name) / "t.sqlite"))
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple", True)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def _rate(self):
        return make_response(200, {"rates": [{"instrumentID": 101, "ask": 10.5, "bid": 10.4, "lastExecution": 10.45}]})

    def test_get_latest_price_uses_last_execution(self):
        client, session = self._client()
        session.request.return_value = self._rate()
        self.assertEqual(client.get_latest_price("AAPL", "STOCK"), 10.45)

    def test_get_latest_quote_maps_bid_ask(self):
        client, session = self._client()
        session.request.return_value = self._rate()
        quote = client.get_latest_quote("AAPL", "STOCK")
        self.assertEqual(quote["bid_price"], 10.4)
        self.assertEqual(quote["ask_price"], 10.5)
        self.assertIsNone(quote["bid_size"])
        self.assertIsNone(quote["ask_size"])

    def test_get_latest_price_unknown_symbol_raises(self):
        client, session = self._client()
        session.request.return_value = make_response(404, {})
        with self.assertRaises(EToroAPIError):
            client.get_latest_price("NOPE", "STOCK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroPriceTests -v`
Expected: FAIL with `AttributeError: ... 'get_latest_price'`.

- [ ] **Step 3: Implement the price adapters**

Append to the `EToroClient` class in the market-data section:

```python
    def _resolve_or_raise(self, symbol: str) -> int:
        instrument_id = self.instrument_id_for_symbol(symbol)
        if instrument_id is None:
            raise EToroAPIError(404, f"unknown instrument for symbol {symbol}")
        return instrument_id

    def get_latest_price(self, symbol: str, category: str) -> float:
        instrument_id = self._resolve_or_raise(symbol)
        quote = self.get_rate_by_instrument(instrument_id)
        price = quote.get("last_price") or quote.get("ask_price") or quote.get("bid_price")
        if not price:
            raise EToroAPIError(404, f"no price for {symbol}")
        return float(price)

    def get_latest_quote(self, symbol: str, category: str) -> dict[str, float | None]:
        instrument_id = self._resolve_or_raise(symbol)
        quote = self.get_rate_by_instrument(instrument_id)
        return {
            "bid_price": quote.get("bid_price"),
            "ask_price": quote.get("ask_price"),
            "bid_size": None,
            "ask_size": None,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroPriceTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add get_latest_price/get_latest_quote adapters"
```

---

## Task 4: `get_open_position`

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append `EToroPositionLookupTests`)

`get_open_position(symbol) -> Position dict | None`: resolve the symbol to an instrumentId, scan `list_open_positions()` for a matching `instrument_id`, and stamp the `symbol` onto the returned dict.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
class EToroPositionLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        initialize_databases(self.market_db, str(Path(self.tmp.name) / "t.sqlite"))
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple", True)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def _portfolio(self, instrument_id):
        return make_response(200, {"clientPortfolio": {"credit": 100.0, "orders": [], "positions": [
            {"positionID": "p1", "instrumentID": instrument_id, "units": 2.0, "openRate": 50.0,
             "amount": 100.0, "isBuy": True, "leverage": 1, "stopLossRate": 45.0, "takeProfitRate": 60.0},
        ]}})

    def test_get_open_position_match(self):
        client, session = self._client()
        session.request.return_value = self._portfolio(101)
        pos = client.get_open_position("AAPL")
        self.assertIsNotNone(pos)
        self.assertEqual(pos["position_id"], "p1")
        self.assertEqual(pos["symbol"], "AAPL")

    def test_get_open_position_no_match(self):
        client, session = self._client()
        session.request.return_value = self._portfolio(999)
        self.assertIsNone(client.get_open_position("AAPL"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroPositionLookupTests -v`
Expected: FAIL with `AttributeError: ... 'get_open_position'`.

- [ ] **Step 3: Implement the lookup**

Append to the `EToroClient` class in the account section:

```python
    def get_open_position(self, symbol: str) -> dict[str, Any] | None:
        instrument_id = self.instrument_id_for_symbol(symbol)
        if instrument_id is None:
            return None
        for position in self.list_open_positions():
            if position["instrument_id"] == instrument_id:
                position["symbol"] = str(symbol).upper().strip()
                return position
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroPositionLookupTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add get_open_position lookup by symbol"
```

---

## Task 5: Provider-aware equity snapshots

**Files:**
- Modify: `services/equity_snapshots.py`
- Test: `tests/test_etoro_equity_snapshots.py` (create)

`record_snapshots_all` currently loops the hardcoded tuple `(PROVIDER_ALPACA,)`. Change it to iterate `config.active_providers()` so eToro (and any future broker) is sampled.

- [ ] **Step 1: Write the failing test**

Create `tests/test_etoro_equity_snapshots.py`:

```python
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.app_db import initialize_app_database
from core.utils import AppConfig
from services.equity_snapshots import record_snapshots_all, latest_snapshot


class EquitySnapshotProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_db = str(Path(self.tmp.name) / "app.sqlite")
        initialize_app_database(self.app_db)
        self.config = AppConfig(
            openai_api_key="k", alpaca_api_key="", alpaca_secret_key="", alpaca_base_url="x",
            etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo", db_app=self.app_db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_etoro_when_active(self):
        broker = Mock()
        broker.get_account_equity.return_value = 1234.0
        out = record_snapshots_all(self.config, {"etoro": broker}, logging.getLogger("t"))
        self.assertIn("etoro", out)
        snap = latest_snapshot(self.app_db, provider="etoro")
        self.assertEqual(snap["equity"], 1234.0)
        self.assertEqual(snap["currency"], "USD")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_equity_snapshots -v`
Expected: FAIL — `out` does not contain `"etoro"` (loop still hardcoded to Alpaca).

- [ ] **Step 3: Make the loop provider-aware**

In `services/equity_snapshots.py`, change the loop inside `record_snapshots_all` (currently `for provider in (PROVIDER_ALPACA,):`) to:

```python
    out: dict[str, dict[str, Any] | None] = {}
    for provider in config.active_providers():
        broker = brokers.get(provider)
        if broker is None:
            continue
        try:
            out[provider] = record_snapshot(config, broker, logger, provider=provider)
        except Exception:
            logger.exception("equity snapshot: provider %s failed", provider)
            out[provider] = None
    return out
```

(The `PROVIDER_ALPACA` import may now be unused for the loop but is still used elsewhere in the module — leave the import.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_equity_snapshots -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/equity_snapshots.py backend/tests/test_etoro_equity_snapshots.py
git commit -m "feat(etoro): make equity snapshots iterate active providers"
```

---

## Task 6: Wire eToro into `main.py`

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add the import**

In `main.py`, after the `from clients.alpaca_client import AlpacaClient` line, add:

```python
from clients.etoro_client import EToroClient
```

And add `PROVIDER_ETORO` to the `from core.utils import (...)` block (alongside `PROVIDER_ALPACA`).

- [ ] **Step 2: Instantiate the eToro broker**

In `main.py`, in the provider auto-detection block, after the Alpaca `if/else` (the block ending with `logger.info("Alpaca credentials missing; module disabled")`), add:

```python
    if config.etoro_enabled:
        brokers[PROVIDER_ETORO] = EToroClient(config, logger)
        logger.info("eToro client enabled (%s account)", "demo" if config.demo else "real")
    else:
        logger.info("eToro credentials missing; module disabled")
```

- [ ] **Step 3: Verify the module imports cleanly (in Docker, which has all deps)**

Run:
```bash
docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -c "import ast; ast.parse(open('main.py').read()); print('main.py parses')"
```
Expected: `main.py parses`.

(A full `import main` pulls in fastapi/apscheduler and starts wiring; `ast.parse` confirms syntax without side effects. The eToro branch is exercised end-to-end in Plan 4's demo integration.)

- [ ] **Step 4: Commit**

```bash
git add backend/main.py
git commit -m "feat(etoro): wire EToroClient into broker registry in main.py"
```

---

## Final verification

- [ ] **Run the whole backend suite in Docker and confirm no new failures vs. the Plan 1 baseline**

Run:
```bash
docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest discover -s tests -v 2>&1 | tail -15
```
Expected: the only failures are the **pre-existing** `test_trade_manager_orders.py` 4 failures + 1 error (unchanged from `dev-2.0`). Every new eToro test passes. Confirm the new-test count grew by the adapter + snapshot tests.

- [ ] **Run just the eToro suites for a clean green**

Run:
```bash
docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest tests.test_etoro_client tests.test_etoro_equity_snapshots tests.test_etoro_config tests.test_etoro_instruments_db tests.test_etoro_rate_limiter
```
Expected: `OK`.

---

## Self-Review (completed during planning)

- **Spec coverage (Plan 2 scope):** market-data adapter `get_bars`/`get_multi_bars` (§5.1, build-seq step 4) — Task 2 ✓; price/quote (§5.1) — Task 3 ✓; symbol→instrumentId cache over `instrument_map` (§5.2) — Task 1 ✓; position lookup (§5.1) — Task 4 ✓; account equity wiring / snapshots (§5.4 build-seq step 5) — Task 5 ✓; broker registry wiring (§5.1) — Task 6 ✓.
- **Deferred (by design):** `list_assets` + universe discovery rewrite → Plan 3 (entangled with the GPT dossier pipeline); trade lifecycle → Plan 4; Alpaca removal + fresh DB schema → Plan 5 (cutover). Provider tagging of universe symbols to `"etoro"` is owned by Plan 3 (universe writer).
- **Placeholder scan:** none.
- **Type consistency:** adapter signatures match the Alpaca client surface the consumers call (`get_bars(symbol, category, start)`, `get_latest_price(symbol, category)`, `get_latest_quote(...)→{bid_price,ask_price,bid_size,ask_size}`, `get_open_position(symbol)`). `instrument_id_for_symbol`, `_candles_count_for_start`, `_resolve_or_raise` names are used consistently. The `parse_datetime`/`utc_now` import line replacement is called out explicitly in Task 2 Step 3.
