# eToro Migration — Plan 3: Universe Discovery & Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the weekly universe selection produce an eToro-tagged universe — `EToroClient.list_assets` discovers tradable stock/crypto instruments from eToro, the `UniverseManager` selection path is generalized to run per provider, and `universe_admin` validates/normalizes eToro symbols.

**Architecture:** The consumption side is already provider-generic — `trade_manager.symbols_to_monitor` threads each universe entry's `provider` into `{symbol:{category,provider}}`, `data_manager` dispatches by provider, and `_evaluate_cycle` iterates providers. So this plan only needs to (a) give `EToroClient` a `list_assets` that returns Alpaca-shaped asset objects, (b) register `PROVIDER_ETORO` in the universe-file plumbing, (c) generalize the `UniverseManager` Alpaca selection methods to take a `provider` argument and add eToro candidate payloads + dispatch, and (d) teach `universe_admin` the eToro provider/category/symbol rules. The shared enrichment → prefilter → GPT-dossier → final-selection machinery is reused unchanged. Alpaca stays wired in parallel until the Plan 5 cutover.

**Tech Stack:** Python 3.11+, `requests`, `unittest` (host for non-pandas tests; Docker for the full suite).

**Depends on:** Plan 1 (raw client + `instrument_map`), Plan 2 (`instrument_id_for_symbol`, market-data adapter).

**eToro discovery endpoints (verified):**
- `GET /api/v1/market-data/instrument-types` → `{"instrumentTypes":[{"instrumentTypeID","instrumentTypeDescription"}]}` (e.g. "Stocks", "Crypto", "ETF").
- `GET /api/v1/market-data/instruments?instrumentTypeIds=<csv>` → `{"instrumentDisplayDatas":[{"instrumentID","instrumentDisplayName","instrumentTypeID","symbolFull","isInternalInstrument"}]}`.

**Asset object contract (what `UniverseManager` reads via `getattr`):** `.symbol`, `.name`, `.status` ("active"), `.tradable` (bool), `.fractionable` (bool). eToro returns no per-listing tradable flag in the bulk endpoint, so discovered non-internal instruments are treated as tradable+active+fractionable (amount-based opens are inherently fractional); ETFs are excluded by selecting only the Stocks type ID.

---

## File Structure

| File | Responsibility |
|---|---|
| `clients/etoro_client.py` (modify) | Add `EToroAsset` + `list_assets(asset_class)` (type-ID resolution, bulk discovery, seeds `instrument_map`). |
| `core/utils.py` (modify) | `ALL_PROVIDERS` includes `PROVIDER_ETORO`; `_empty_universe` seeds both providers. |
| `services/universe_manager.py` (modify) | Generalize `_select_alpaca_category_universe`→`_select_category_universe(provider,…)`; add `_get_etoro_*_candidate_payload`, `_select_etoro_universe`; dispatch in `select_trading_universe`. |
| `services/universe_admin.py` (modify) | eToro provider/category map; eToro crypto symbol normalization (no slash); eToro validation via instrument resolution. |
| `tests/test_etoro_client.py` (modify) | `EToroListAssetsTests`. |
| `tests/test_etoro_universe.py` (create) | Provider plumbing + eToro selection + admin tests. |

---

## Task 1: `EToroClient.list_assets`

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append `EToroListAssetsTests`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
class EToroListAssetsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        initialize_databases(self.market_db, str(Path(self.tmp.name) / "t.sqlite"))

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def _types(self):
        return make_response(200, {"instrumentTypes": [
            {"instrumentTypeID": 5, "instrumentTypeDescription": "Stocks"},
            {"instrumentTypeID": 10, "instrumentTypeDescription": "Crypto"},
            {"instrumentTypeID": 6, "instrumentTypeDescription": "ETF"},
        ]})

    def test_list_assets_stock_filters_and_seeds_cache(self):
        client, session = self._client()
        session.request.side_effect = [
            self._types(),
            make_response(200, {"instrumentDisplayDatas": [
                {"instrumentID": 101, "instrumentDisplayName": "Apple", "symbolFull": "AAPL", "isInternalInstrument": False},
                {"instrumentID": 999, "instrumentDisplayName": "Internal", "symbolFull": "INT", "isInternalInstrument": True},
            ]}),
        ]
        assets = client.list_assets("US_EQUITY")
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0].symbol, "AAPL")
        self.assertTrue(assets[0].tradable)
        # type filter used the Stocks id (5)
        params = session.request.call_args_list[1].kwargs["params"]
        self.assertEqual(params["instrumentTypeIds"], "5")
        # cache seeded
        cached = get_instrument_mapping(self.market_db, "AAPL")
        self.assertEqual(cached["instrument_id"], 101)
        self.assertEqual(cached["category"], "STOCK")

    def test_list_assets_crypto_uses_crypto_type(self):
        client, session = self._client()
        session.request.side_effect = [
            self._types(),
            make_response(200, {"instrumentDisplayDatas": [
                {"instrumentID": 100000, "instrumentDisplayName": "Bitcoin", "symbolFull": "BTC", "isInternalInstrument": False},
            ]}),
        ]
        assets = client.list_assets("CRYPTO")
        self.assertEqual(assets[0].symbol, "BTC")
        params = session.request.call_args_list[1].kwargs["params"]
        self.assertEqual(params["instrumentTypeIds"], "10")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroListAssetsTests -v`
Expected: FAIL with `AttributeError: ... 'list_assets'`.

- [ ] **Step 3: Implement `EToroAsset` and `list_assets`**

In `clients/etoro_client.py`, add the asset class just above `class EToroClient`:

```python
class EToroAsset:
    """Minimal Alpaca-asset-compatible view of an eToro instrument."""

    __slots__ = ("symbol", "name", "status", "tradable", "fractionable", "instrument_id")

    def __init__(self, symbol: str, name: str, status: str, tradable: bool, fractionable: bool, instrument_id: int) -> None:
        self.symbol = symbol
        self.name = name
        self.status = status
        self.tradable = tradable
        self.fractionable = fractionable
        self.instrument_id = instrument_id
```

Append to the `EToroClient` class, in the instruments section (after `instrument_id_for_symbol`):

```python
    _ASSET_CLASS_HINTS = {
        "US_EQUITY": ("stock",),
        "STOCK": ("stock",),
        "CRYPTO": ("crypto",),
    }

    def _instrument_type_ids(self, hints: tuple[str, ...]) -> list[int]:
        payload = self._request("GET", "/api/v1/market-data/instrument-types")
        out: list[int] = []
        for entry in payload.get("instrumentTypes") or []:
            desc = str(entry.get("instrumentTypeDescription") or "").lower()
            if any(hint in desc for hint in hints) and entry.get("instrumentTypeID") is not None:
                out.append(int(entry["instrumentTypeID"]))
        return out

    def list_assets(self, asset_class: str) -> list[EToroAsset]:
        hints = self._ASSET_CLASS_HINTS.get(str(asset_class).upper(), (str(asset_class).lower(),))
        category = "CRYPTO" if "crypto" in hints else "STOCK"
        type_ids = self._instrument_type_ids(hints)
        if not type_ids:
            return []
        payload = self._request(
            "GET",
            "/api/v1/market-data/instruments",
            params={"instrumentTypeIds": ",".join(str(i) for i in type_ids)},
        )
        assets: list[EToroAsset] = []
        for row in payload.get("instrumentDisplayDatas") or []:
            if row.get("isInternalInstrument"):
                continue
            symbol = str(row.get("symbolFull") or "").upper().strip()
            if not symbol or row.get("instrumentID") is None:
                continue
            instrument_id = int(row["instrumentID"])
            name = str(row.get("instrumentDisplayName") or "")
            assets.append(EToroAsset(symbol, name, "active", True, True, instrument_id))
            try:
                upsert_instrument_mapping(self.config.db_market_data, symbol, instrument_id, category, name, True)
            except Exception:
                self.logger.debug("Failed to cache instrument mapping for %s", symbol)
        return assets
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_client.EToroListAssetsTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add list_assets instrument discovery (seeds instrument_map)"
```

---

## Task 2: Provider plumbing for the universe file

**Files:**
- Modify: `core/utils.py`
- Test: `tests/test_etoro_universe.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_etoro_universe.py`:

```python
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import ALL_PROVIDERS, PROVIDER_ETORO, _empty_universe, _normalize_universe_payload


class UniversePlumbingTests(unittest.TestCase):
    def test_etoro_in_all_providers(self):
        self.assertIn(PROVIDER_ETORO, ALL_PROVIDERS)

    def test_empty_universe_has_etoro(self):
        u = _empty_universe()
        self.assertIn(PROVIDER_ETORO, u)
        self.assertEqual(u[PROVIDER_ETORO], {"STOCK": [], "CRYPTO": []})

    def test_normalize_reads_etoro_entry(self):
        norm = _normalize_universe_payload({"etoro": {"STOCK": ["aapl"], "CRYPTO": ["btc"]}})
        self.assertEqual(norm[PROVIDER_ETORO]["STOCK"], ["AAPL"])
        self.assertEqual(norm[PROVIDER_ETORO]["CRYPTO"], ["BTC"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_universe.UniversePlumbingTests -v`
Expected: FAIL — `PROVIDER_ETORO` not in `ALL_PROVIDERS`.

- [ ] **Step 3: Register eToro in the provider tuple and empty universe**

In `core/utils.py`, change line 23 from:

```python
ALL_PROVIDERS: tuple[str, ...] = (PROVIDER_ALPACA,)
```

to (note `PROVIDER_ETORO` is defined on the preceding line from Plan 1):

```python
ALL_PROVIDERS: tuple[str, ...] = (PROVIDER_ALPACA, PROVIDER_ETORO)
```

Then change `_empty_universe` (currently returns only the Alpaca entry) to:

```python
def _empty_universe() -> ProviderUniverse:
    return {
        PROVIDER_ALPACA: {"STOCK": [], "CRYPTO": []},
        PROVIDER_ETORO: {"STOCK": [], "CRYPTO": []},
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_universe.UniversePlumbingTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/core/utils.py backend/tests/test_etoro_universe.py
git commit -m "feat(etoro): register eToro provider in universe-file plumbing"
```

---

## Task 3: eToro universe selection in `UniverseManager`

**Files:**
- Modify: `services/universe_manager.py`
- Test: `tests/test_etoro_universe.py` (append `EtoroUniverseSelectionTests`)

This generalizes the Alpaca per-category selector to accept a `provider` and adds eToro candidate payloads + an eToro selection path that reuses all shared machinery.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_universe.py`:

```python
import logging
import tempfile
from pathlib import Path
from unittest.mock import Mock

from core.utils import AppConfig, PROVIDER_ETORO as PE


def _asset(symbol, name="X"):
    a = Mock()
    a.symbol = symbol
    a.name = name
    a.status = "active"
    a.tradable = True
    a.fractionable = True
    return a


class EtoroUniverseSelectionTests(unittest.TestCase):
    def setUp(self):
        from services.universe_manager import UniverseManager
        self.tmp = tempfile.TemporaryDirectory()
        # isolate the universe file write by pointing UNIVERSE_FILE-derived paths via cwd-independent config
        self.config = AppConfig(
            openai_api_key="k", alpaca_api_key="", alpaca_secret_key="", alpaca_base_url="x",
            etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo",
            weekly_universe_stocks=1, weekly_universe_crypto=1,
        )
        self.broker = Mock()
        # discovery
        self.broker.list_assets.side_effect = lambda cls: (
            [_asset("AAPL", "Apple")] if cls in ("US_EQUITY", "STOCK") else [_asset("BTC", "Bitcoin")]
        )
        # enrichment bars (enough to pass prefilter is not required; selection tops up)
        self.broker.get_multi_bars.return_value = {}
        self.gpt = Mock()
        # no dossiers -> deterministic top-up path
        self.gpt.request_universe_symbol_dossier.side_effect = Exception("no gpt")
        self.manager = UniverseManager(self.config, logging.getLogger("t"), {PE: self.broker}, self.gpt)

    def tearDown(self):
        self.tmp.cleanup()

    def test_etoro_candidate_payloads(self):
        stock = self.manager._get_etoro_stock_candidate_payload()
        crypto = self.manager._get_etoro_crypto_candidate_payload()
        self.assertEqual(stock[0]["symbol"], "AAPL")
        self.assertEqual(crypto[0]["symbol"], "BTC")

    def test_select_etoro_universe_tops_up_when_no_dossiers(self):
        result = self.manager._select_etoro_universe(self.manager.get_current_universe())
        self.assertEqual(result["STOCK"], ["AAPL"])
        self.assertEqual(result["CRYPTO"], ["BTC"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_universe.EtoroUniverseSelectionTests -v`
Expected: FAIL with `AttributeError: ... '_get_etoro_stock_candidate_payload'`.

- [ ] **Step 3: Generalize the per-category selector to take a provider**

In `services/universe_manager.py`, rename `_select_alpaca_category_universe` to `_select_category_universe` and add a leading `provider: str` parameter. Replace every hard-coded `PROVIDER_ALPACA` inside that method body with the `provider` argument. The full replacement method:

```python
    def _select_category_universe(
        self,
        provider: str,
        category: str,
        payload: list[dict[str, Any]],
        required_count: int,
        batch_size: int,
        preferred_symbols: list[str] | None = None,
    ) -> list[str]:
        if not payload or required_count <= 0:
            return []

        preferred_symbols = preferred_symbols or []
        prefiltered_payload = self._build_prefiltered_payload(
            category=category,
            payload=payload,
            required_count=required_count,
            batch_size=batch_size,
            preferred_symbols=preferred_symbols,
        )
        if not prefiltered_payload:
            return []

        dossier_candidates = self._build_dossier_candidates(category, prefiltered_payload, required_count)
        dossiers = self._generate_parallel_symbol_dossiers(
            provider=provider,
            category=category,
            candidates=dossier_candidates,
            required_count=required_count,
            preferred_symbols=preferred_symbols,
        )
        if not dossiers:
            return self._top_up_selection(provider, category, [], prefiltered_payload, required_count)

        dossier_symbols = [self._normalize_symbol(dossier.get("symbol")) for dossier in dossiers]
        successful_dossier_payload = self._filter_payload_by_symbols(dossier_candidates, dossier_symbols)

        try:
            final_result = self.gpt_client.request_universe_final_selection_from_dossiers(
                category=category,
                dossiers=dossiers,
                required_count=min(required_count, len(dossiers)),
                current_universe=preferred_symbols,
                provider=provider,
            )
            selected_symbols = self._sanitize_selection(
                provider,
                category,
                final_result.get("symbols", []),
                {self._normalize_symbol(dossier.get("symbol")) for dossier in dossiers},
            )
        except Exception:
            self.logger.exception("GPT dossier-based final universe selection failed for %s; using deterministic fallback", category)
            selected_symbols = []

        completed_selection = self._top_up_selection(provider, category, selected_symbols, successful_dossier_payload, required_count)
        if len(completed_selection) >= required_count:
            return completed_selection
        return self._top_up_selection(provider, category, completed_selection, prefiltered_payload, required_count)
```

Then update the two call sites inside `_select_alpaca_universe` (currently calling `self._select_alpaca_category_universe(category="STOCK"/"CRYPTO", …)`) to call `self._select_category_universe(PROVIDER_ALPACA, "STOCK"/"CRYPTO", …)` — i.e. add `PROVIDER_ALPACA` as the first positional argument and keep the rest. Concretely, change `self._select_alpaca_category_universe(\n                category="STOCK",` to `self._select_category_universe(\n                PROVIDER_ALPACA,\n                category="STOCK",` and likewise for the `"CRYPTO"` call.

- [ ] **Step 4: Add eToro candidate payloads and selection path**

In `services/universe_manager.py`, add the import of `PROVIDER_ETORO` to the `from core.utils import (...)` block (alongside `PROVIDER_ALPACA`). Then add, right after `_write_alpaca_candidate_lists` (before `# -- public entry points`):

```python
    # -- eToro path -------------------------------------------------------

    def _get_etoro_stock_candidate_payload(self) -> list[dict[str, Any]]:
        broker = self.broker(PROVIDER_ETORO)
        if broker is None:
            return []
        assets = broker.list_assets("STOCK")
        payload = [
            self._asset_snapshot(asset)
            for asset in assets
            if getattr(asset, "tradable", False)
            and not self._looks_like_etf(asset)
            and not self._looks_like_non_common_stock(asset)
            and not self._looks_like_shell_company(asset)
        ]
        payload = self._dedupe_payload_by_symbol(payload)
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload

    def _get_etoro_crypto_candidate_payload(self) -> list[dict[str, Any]]:
        broker = self.broker(PROVIDER_ETORO)
        if broker is None:
            return []
        assets = broker.list_assets("CRYPTO")
        payload = [
            self._asset_snapshot(asset)
            for asset in assets
            if getattr(asset, "tradable", False)
        ]
        payload = self._dedupe_payload_by_symbol(payload)
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload

    def _select_etoro_universe(self, current_universe: ProviderUniverse) -> dict[str, list[str]]:
        broker = self.broker(PROVIDER_ETORO)
        if broker is None:
            return {}
        preferred = universe_for_provider(current_universe, PROVIDER_ETORO)
        try:
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

Rename `_write_alpaca_candidate_lists` to `_write_candidate_lists` (drop the `alpaca` name; the body is provider-agnostic) and update its one caller inside `_select_alpaca_universe` from `self._write_alpaca_candidate_lists(` to `self._write_candidate_lists(`.

- [ ] **Step 5: Dispatch eToro in `select_trading_universe`**

In `services/universe_manager.py`, replace the body of `select_trading_universe` with:

```python
    def select_trading_universe(self) -> ProviderUniverse:
        current_universe = self.get_current_universe()
        result: ProviderUniverse = {provider: {} for provider in ALL_PROVIDERS}

        if self.alpaca_client is not None:
            result[PROVIDER_ALPACA] = self._select_alpaca_universe(current_universe)
        else:
            result[PROVIDER_ALPACA] = {"STOCK": [], "CRYPTO": []}

        if self.broker(PROVIDER_ETORO) is not None:
            result[PROVIDER_ETORO] = self._select_etoro_universe(current_universe)
        else:
            result[PROVIDER_ETORO] = {"STOCK": [], "CRYPTO": []}

        write_universe_file(result)
        self.logger.info("Selected trading universe: %s", result)
        return result
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_universe.EtoroUniverseSelectionTests -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/services/universe_manager.py backend/tests/test_etoro_universe.py
git commit -m "feat(etoro): add eToro universe discovery and selection path"
```

---

## Task 4: `universe_admin` eToro support

**Files:**
- Modify: `services/universe_admin.py`
- Test: `tests/test_etoro_universe.py` (append `EtoroUniverseAdminTests`)

eToro categories mirror Alpaca's (`STOCK`, `CRYPTO`); crypto symbols are native (no `BASE/QUOTE` slash); validation resolves the instrument and checks a live price rather than scanning a catalogue.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_universe.py`:

```python
class EtoroUniverseAdminTests(unittest.TestCase):
    def setUp(self):
        from services import universe_admin
        self.universe_admin = universe_admin
        self.config = AppConfig(
            openai_api_key="k", alpaca_api_key="", alpaca_secret_key="", alpaca_base_url="x",
            etoro_api_key="a", etoro_user_key="b",
        )

    def test_etoro_crypto_symbol_keeps_native_form(self):
        sym = self.universe_admin._normalize_symbol("btc", "etoro", "CRYPTO", self.config)
        self.assertEqual(sym, "BTC")  # no /USD suffix

    def test_etoro_category_accepts_stock_crypto(self):
        self.assertEqual(self.universe_admin._normalize_category("etoro", "crypto"), "CRYPTO")
        self.assertEqual(self.universe_admin._normalize_category("etoro", "stock"), "STOCK")

    def test_etoro_provider_accepted(self):
        self.assertEqual(self.universe_admin._normalize_provider("etoro"), "etoro")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python3 -m unittest tests.test_etoro_universe.EtoroUniverseAdminTests -v`
Expected: FAIL — `_normalize_category("etoro", ...)` raises (eToro not in `VALID_CATEGORIES_BY_PROVIDER`).

- [ ] **Step 3: Register eToro categories**

In `services/universe_admin.py`, add `PROVIDER_ETORO` to the `from core.utils import (...)` block, and extend the categories map:

```python
VALID_CATEGORIES_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    PROVIDER_ALPACA: ("STOCK", "CRYPTO"),
    PROVIDER_ETORO: ("STOCK", "CRYPTO"),
}
```

- [ ] **Step 4: eToro-native crypto symbol normalization**

In `services/universe_admin.py`, change `_normalize_symbol` so eToro crypto keeps its native ticker (the Alpaca `BASE/QUOTE` rule only applies to Alpaca):

```python
def _normalize_symbol(symbol: str, provider: str, category: str, config: AppConfig) -> str:
    raw = (symbol or "").strip().upper()
    if not raw:
        raise UniverseValidationError("Symbol is required")
    if category == "CRYPTO":
        if provider == PROVIDER_ETORO:
            # eToro uses native crypto tickers (e.g. BTC), no quote suffix.
            if "/" in raw or " " in raw:
                raise UniverseValidationError("eToro crypto symbol must be a plain ticker (e.g. BTC)")
            return raw
        # Alpaca pair format BASE/QUOTE.
        if "/" not in raw:
            if len(raw) > 3:
                raw = f"{raw[:-3]}/{raw[-3:]}"
            else:
                raise UniverseValidationError(
                    "Crypto symbol must use BASE/QUOTE format (e.g. BTC/USD)"
                )
        return raw
    if "/" in raw or " " in raw:
        raise UniverseValidationError("Stock symbol cannot contain '/' or spaces")
    return raw
```

- [ ] **Step 5: eToro validation path**

In `services/universe_admin.py`, in `_validate_symbol_with_broker`, after the price check (the block that ends before `try:` with the catalogue scan), branch eToro to resolve the instrument instead of scanning. Replace the catalogue-scan `try/except` block (the one starting `try:` / `if category == "STOCK": assets = broker.list_assets("US_EQUITY")`) with a provider-aware version that short-circuits eToro:

```python
    if provider == PROVIDER_ETORO:
        try:
            asset = broker.resolve_instrument(symbol)
        except Exception:
            logger.exception("eToro instrument resolution failed for %s; trusting price quote", symbol)
            return
        if asset is None:
            raise UniverseValidationError(f"{symbol} is not an eToro instrument")
        if not asset.get("tradable", True):
            raise UniverseValidationError(f"{symbol} is listed on eToro but not currently tradable")
        return

    try:
        if category == "STOCK":
            assets = broker.list_assets("US_EQUITY")
            wanted = symbol.upper()
            for asset in assets:
                ticker = str(getattr(asset, "symbol", "") or "").upper()
                if ticker == wanted:
                    if not bool(getattr(asset, "tradable", True)):
                        raise UniverseValidationError(
                            f"{symbol} is listed but not currently tradable"
                        )
                    return
            raise UniverseValidationError(
                f"{symbol} is not in the Alpaca US_EQUITY catalogue"
            )
        # Alpaca CRYPTO
        assets = broker.list_assets("CRYPTO")
        wanted = symbol.upper()
        for asset in assets:
            ticker = str(getattr(asset, "symbol", "") or "").upper()
            if ticker == wanted:
                return
        raise UniverseValidationError(
            f"{symbol} is not in the Alpaca CRYPTO catalogue"
        )
    except UniverseValidationError:
        raise
    except Exception:
        logger.exception(
            "Asset catalogue check for %s/%s failed; trusting price quote", provider, symbol
        )
```

- [ ] **Step 6: Make `get_universe_with_metadata` cover all providers**

In `services/universe_admin.py`, change the `out` initializer in `get_universe_with_metadata` so the eToro bucket exists too:

```python
    out: dict[str, dict[str, list[dict[str, Any]]]] = {
        provider: {category: [] for category in categories}
        for provider, categories in VALID_CATEGORIES_BY_PROVIDER.items()
    }
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && python3 -m unittest tests.test_etoro_universe.EtoroUniverseAdminTests -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Commit**

```bash
git add backend/services/universe_admin.py backend/tests/test_etoro_universe.py
git commit -m "feat(etoro): eToro provider/category/symbol support in universe_admin"
```

---

## Final verification

- [ ] **Full suite in Docker — only the pre-existing trade_manager failures remain**

Run:
```bash
docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest discover -s tests 2>&1 | tail -12
```
Expected: failures/errors unchanged from the Plan 2 baseline (the 4 + 1 in `test_trade_manager_orders.py`); all eToro universe tests pass.

- [ ] **eToro suites clean**

Run:
```bash
docker run --rm -v "$PWD/backend":/app -w /app trading-backend:test python -m unittest tests.test_etoro_client tests.test_etoro_universe tests.test_etoro_equity_snapshots tests.test_etoro_config tests.test_etoro_instruments_db tests.test_etoro_rate_limiter
```
Expected: `OK`.

---

## Self-Review (completed during planning)

- **Spec coverage (Plan 3 scope):** universe discovery via eToro instruments (§5.7/build-seq step 4) — Task 1 (`list_assets`) ✓; provider tagging of universe symbols to `"etoro"` (§5.7) — Tasks 2–3 ✓; selection reuse of the dossier machinery — Task 3 ✓; operator add/remove + crypto-native symbols (§2 decision 6) — Task 4 ✓.
- **Deferred (by design):** order placement inside `_evaluate_provider_category` / `_open_trade_from_signal` stays Alpaca-specific → Plan 4 (trade lifecycle). Alpaca removal + fresh DB schema → Plan 5.
- **Consumption already generic (verified):** `trade_manager.symbols_to_monitor` threads `provider` per universe entry; `data_manager.update_symbols` dispatches by provider; `_evaluate_cycle` iterates `self._brokers`. No change needed there for data refresh of eToro symbols.
- **Placeholder scan:** none.
- **Type consistency:** `list_assets` returns `EToroAsset` objects exposing `.symbol/.name/.status/.tradable/.fractionable` — exactly the attributes `_asset_snapshot`/`_looks_like_*` read via `getattr`. `_select_category_universe(provider, …)` signature is used by both Alpaca and eToro callers. `EToroAsset.instrument_id` is extra (unused by universe code, used for cache seeding). The Alpaca `_sanitize_crypto_selection` tries the suffixed form first then the native ticker, so it correctly resolves eToro native crypto tickers against the `{BTC}` candidate set without modification.
