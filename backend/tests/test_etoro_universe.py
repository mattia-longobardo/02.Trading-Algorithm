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

from core.utils import (
    ALL_PROVIDERS,
    PROVIDER_ETORO,
    AppConfig,
    _empty_universe,
    _normalize_universe_payload,
)

PE = PROVIDER_ETORO


def _asset(symbol, name="X"):
    a = Mock()
    a.symbol = symbol
    a.name = name
    a.status = "active"
    a.tradable = True
    a.fractionable = True
    return a


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


class EtoroUniverseSelectionTests(unittest.TestCase):
    def setUp(self):
        from services.universe_manager import UniverseManager
        self.config = AppConfig(
            openai_api_key="k", 
            etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo",
            weekly_universe_stocks=1, weekly_universe_crypto=1,
        )
        self.broker = Mock()
        self.broker.list_assets.side_effect = lambda cls: (
            [_asset("AAPL", "Apple")] if cls in ("US_EQUITY", "STOCK") else [_asset("BTC", "Bitcoin")]
        )
        self.broker.get_multi_bars.return_value = {}
        self.broker.discover_instruments.side_effect = Exception("no discover")
        self.gpt = Mock()
        self.gpt.request_universe_symbol_dossier.side_effect = Exception("no gpt")
        self.manager = UniverseManager(self.config, logging.getLogger("t"), {PE: self.broker}, self.gpt)

    def test_etoro_candidate_payloads(self):
        stock = self.manager._get_etoro_stock_candidate_payload()
        crypto = self.manager._get_etoro_crypto_candidate_payload()
        self.assertEqual(stock[0]["symbol"], "AAPL")
        self.assertEqual(crypto[0]["symbol"], "BTC")

    def test_legacy_crypto_payload_excludes_dated_futures(self):
        self.broker.list_assets.side_effect = lambda cls: (
            [_asset("AAPL", "Apple")] if cls in ("US_EQUITY", "STOCK")
            else [_asset("BTC", "Bitcoin"), _asset("BTC.MAY26", "BTC May26 Future")]
        )
        payload = self.manager._get_etoro_crypto_candidate_payload()
        symbols = [a["symbol"] for a in payload]
        self.assertIn("BTC", symbols)
        self.assertNotIn("BTC.MAY26", symbols)

    def test_select_etoro_universe_tops_up_when_no_dossiers(self):
        result = self.manager._select_etoro_universe(self.manager.get_current_universe())
        self.assertEqual(result["STOCK"], ["AAPL"])
        self.assertEqual(result["CRYPTO"], ["BTC"])


class EtoroUniverseAdminTests(unittest.TestCase):
    def setUp(self):
        from services import universe_admin
        self.universe_admin = universe_admin
        self.config = AppConfig(
            openai_api_key="k", 
            etoro_api_key="a", etoro_user_key="b",
        )

    def test_etoro_crypto_symbol_keeps_native_form(self):
        sym = self.universe_admin._normalize_symbol("btc", "etoro", "CRYPTO", self.config)
        self.assertEqual(sym, "BTC")

    def test_etoro_category_accepts_stock_crypto(self):
        self.assertEqual(self.universe_admin._normalize_category("etoro", "crypto"), "CRYPTO")
        self.assertEqual(self.universe_admin._normalize_category("etoro", "stock"), "STOCK")

    def test_etoro_provider_accepted(self):
        self.assertEqual(self.universe_admin._normalize_provider("etoro"), "etoro")


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

    def test_cheap_score_rewards_liquidity_and_size(self):
        manager, _ = self._manager()
        big = manager._cheap_prefilter_score({"market_cap": 1e12, "dollar_volume": 1e9})
        small = manager._cheap_prefilter_score({"market_cap": 3e8, "dollar_volume": 1e5})
        self.assertGreater(big, small)

    def test_cheap_score_rewards_analyst_consensus(self):
        manager, _ = self._manager()
        base = {"market_cap": 5e9, "dollar_volume": 2e7, "analyst_count": 15, "analyst_upside": 20.0}
        buy = manager._cheap_prefilter_score({**base, "analyst_consensus": "StrongBuy"})
        sell = manager._cheap_prefilter_score({**base, "analyst_consensus": "Sell"})
        self.assertGreater(buy, sell)

    def test_cheap_score_penalizes_daily_spike(self):
        manager, _ = self._manager()
        base = {"market_cap": 5e9, "dollar_volume": 2e7}
        calm = manager._cheap_prefilter_score({**base, "price_change_1d": 0.0})
        spiky = manager._cheap_prefilter_score({**base, "price_change_1d": 50.0})
        self.assertGreater(calm, spiky)

    def test_dedupe_by_isin_merges_variants(self):
        manager, _ = self._manager()
        canonical = self._stock("NVDA", isin="US67", pop=2, consensus="StrongBuy", upside=50.0, analysts=30)
        rth = self._stock("NVDA.RTH", isin="US67", pop=1043, consensus=None, upside=None, analysts=0)
        out = manager._dedupe_by_isin([canonical, rth])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["symbol"], "NVDA.RTH")             # most popular variant kept
        self.assertEqual(out[0]["analyst_consensus"], "StrongBuy")  # back-filled from sibling
        self.assertEqual(out[0]["analyst_count"], 30)

    def test_dedupe_by_isin_passes_through_empty_isin(self):
        manager, _ = self._manager()
        out = manager._dedupe_by_isin([self._crypto("BTC"), self._crypto("ETH")])
        self.assertEqual({r["symbol"] for r in out}, {"BTC", "ETH"})

    def _stock(self, symbol, country="US", market_cap=5e9, dollar_volume=2e7, pop=1000,
               name="Co", tradable=True, delisted=False, consensus="Buy", upside=10.0,
               analysts=10, isin=None):
        return {
            "symbol": symbol, "name": name, "isin": isin if isin is not None else symbol,
            "tradable": tradable, "delisted": delisted, "country_code": country,
            "market_cap": market_cap, "dollar_volume": dollar_volume, "popularity": pop,
            "instrument_type": "Stocks", "analyst_consensus": consensus,
            "analyst_upside": upside, "analyst_count": analysts,
            "revenue_growth": 10.0, "net_margin": 15.0,
            "price_change_1d": 0.0, "price_change_1m": 0.0,
            "price_change_3m": 0.0, "price_change_6m": 0.0,
        }

    def _crypto(self, symbol, pop=1000, itype="Crypto", tradable=True, market_cap=5e8):
        return {
            "symbol": symbol, "name": symbol, "isin": "", "tradable": tradable, "delisted": False,
            "country_code": "", "market_cap": market_cap, "dollar_volume": 1e6, "popularity": pop,
            "instrument_type": itype, "analyst_consensus": None, "analyst_upside": None,
            "analyst_count": 0, "revenue_growth": None, "net_margin": None,
            "price_change_1d": 0.0, "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0,
        }

    def test_passes_cheap_filter_stock_rules(self):
        manager, _ = self._manager()
        self.assertTrue(manager._passes_cheap_filter("STOCK", self._stock("AAPL")))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", country="CN")))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", market_cap=1e8)))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", dollar_volume=1e3)))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", tradable=False)))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", name="Big Index Fund")))

    def test_passes_cheap_filter_crypto_rules(self):
        manager, _ = self._manager()
        self.assertTrue(manager._passes_cheap_filter("CRYPTO", self._crypto("ETH.SPOT")))
        self.assertTrue(manager._passes_cheap_filter("CRYPTO", self._crypto("HYPE")))
        self.assertFalse(manager._passes_cheap_filter("CRYPTO", self._crypto("BTC.MAY26")))
        self.assertFalse(manager._passes_cheap_filter("CRYPTO", self._crypto("X", itype="Crypto Futures")))
        self.assertFalse(manager._passes_cheap_filter("CRYPTO", self._crypto("TINY", market_cap=1e6)))

    def test_build_cheap_shortlist_stock_caps_and_filters(self):
        manager, broker = self._manager()
        manager.config.universe_stock_shortlist = 2
        broker.discover_instruments.return_value = [
            self._stock("AAA", dollar_volume=1e6),
            self._stock("BBB", dollar_volume=9e8),
            self._stock("CCC", dollar_volume=5e8),
            self._stock("FOREIGN", country="CN", dollar_volume=9e9),
        ]
        shortlist = manager._build_cheap_shortlist(broker, "STOCK", [])
        symbols = [a["symbol"] for a in shortlist]
        self.assertEqual(len(shortlist), 2)
        self.assertEqual(symbols, ["BBB", "CCC"])   # ranked by liquidity, capped
        self.assertNotIn("FOREIGN", symbols)         # wrong country filtered out

    def test_build_cheap_shortlist_pins_preferred(self):
        manager, broker = self._manager()
        manager.config.universe_stock_shortlist = 2
        broker.discover_instruments.return_value = [
            self._stock("AAA", dollar_volume=9e8),
            self._stock("BBB", dollar_volume=8e8),
            self._stock("KEEP", dollar_volume=1e6),
        ]
        shortlist = manager._build_cheap_shortlist(broker, "STOCK", ["KEEP"])
        symbols = [a["symbol"] for a in shortlist]
        self.assertEqual(len(shortlist), 2)        # limit=2: 1 pinned + 1 top-scored
        self.assertEqual(symbols[0], "KEEP")       # pinned symbol comes first
        self.assertIn("AAA", symbols)              # highest-liquidity pool survivor

    def test_build_cheap_shortlist_crypto_drops_futures(self):
        manager, broker = self._manager()
        manager.config.universe_crypto_shortlist = 10
        broker.discover_instruments.return_value = [
            self._crypto("ETH.SPOT", pop=100),
            self._crypto("BTC.MAY26", pop=99999),
            self._crypto("HYPE", pop=50),
        ]
        shortlist = manager._build_cheap_shortlist(broker, "CRYPTO", [])
        symbols = [a["symbol"] for a in shortlist]
        self.assertIn("ETH.SPOT", symbols)
        self.assertIn("HYPE", symbols)
        self.assertNotIn("BTC.MAY26", symbols)


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

    def _stock_row(self, symbol, **over):
        row = {
            "symbol": symbol, "name": symbol, "isin": symbol, "tradable": True, "delisted": False,
            "country_code": "US", "market_cap": 3e12, "dollar_volume": 1e9, "popularity": 9000,
            "instrument_type": "Stocks", "analyst_consensus": "Buy", "analyst_upside": 10.0,
            "analyst_count": 20, "revenue_growth": 10.0, "net_margin": 20.0,
            "price_change_1d": 0.0, "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0,
        }
        row.update(over)
        return row

    def _crypto_row(self, symbol, **over):
        row = {
            "symbol": symbol, "name": symbol, "isin": "", "tradable": True, "delisted": False,
            "country_code": "", "market_cap": 2e11, "dollar_volume": 1e8, "popularity": 9000,
            "instrument_type": "Crypto", "analyst_consensus": None, "analyst_upside": None,
            "analyst_count": 0, "revenue_growth": None, "net_margin": None,
            "price_change_1d": 0.0, "price_change_1m": 0.0, "price_change_3m": 0.0, "price_change_6m": 0.0,
        }
        row.update(over)
        return row

    def test_uses_discover_shortlist_when_available(self):
        broker = Mock()
        broker.discover_instruments.side_effect = lambda cat: (
            [self._stock_row("AAPL")] if cat == "STOCK" else [self._crypto_row("ETH.SPOT")]
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._empty_current())
        broker.list_assets.assert_not_called()
        self.assertEqual(result["STOCK"], ["AAPL"])
        self.assertEqual(result["CRYPTO"], ["ETH.SPOT"])

    def test_falls_back_to_list_assets_when_discover_raises(self):
        broker = Mock()
        broker.discover_instruments.side_effect = Exception("discover down")
        broker.list_assets.side_effect = lambda cls: (
            [_asset("AAPL", "Apple")] if cls in ("US_EQUITY", "STOCK") else [_asset("BTC", "Bitcoin")]
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._empty_current())
        broker.list_assets.assert_called()
        self.assertEqual(result["STOCK"], ["AAPL"])
        self.assertEqual(result["CRYPTO"], ["BTC"])

    def test_falls_back_when_discover_empty(self):
        broker = Mock()
        broker.discover_instruments.return_value = []
        broker.list_assets.side_effect = lambda cls: (
            [_asset("AAPL", "Apple")] if cls in ("US_EQUITY", "STOCK") else [_asset("BTC", "Bitcoin")]
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._empty_current())
        broker.list_assets.assert_called()
        self.assertEqual(result["STOCK"], ["AAPL"])
        self.assertEqual(result["CRYPTO"], ["BTC"])

    def test_partial_discover_falls_back_per_category(self):
        broker = Mock()
        def _discover(cat):
            if cat == "STOCK":
                return [self._stock_row("AAPL")]
            return []  # crypto discover empty → must fall back per-category
        broker.discover_instruments.side_effect = _discover
        broker.list_assets.side_effect = lambda cls: (
            [_asset("AAPL", "Apple")] if cls in ("US_EQUITY", "STOCK") else [_asset("BTC", "Bitcoin")]
        )
        broker.get_multi_bars.return_value = {}
        manager = self._manager(broker)
        result = manager._select_etoro_universe(self._empty_current())
        self.assertEqual(result["STOCK"], ["AAPL"])       # discover path
        self.assertEqual(result["CRYPTO"], ["BTC"])        # legacy fallback
        broker.list_assets.assert_any_call("CRYPTO")       # crypto fell back
        # stock did NOT fall back to legacy
        stock_legacy_calls = [c for c in broker.list_assets.call_args_list
                              if c.args and c.args[0] in ("STOCK", "US_EQUITY")]
        self.assertEqual(stock_legacy_calls, [])


class EtfAllowlistTests(unittest.TestCase):
    def _manager(self, etfs):
        from services.universe_manager import UniverseManager
        config = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
            etoro_account_type="demo", universe_etf_symbols=tuple(etfs),
        )
        broker = Mock()
        broker.instrument_id_for_symbol.return_value = 3000
        return UniverseManager(config, logging.getLogger("t"), {PE: broker}, Mock()), broker

    def test_injects_allowlist_etfs_as_stock(self):
        m, _ = self._manager(["SPY", "QQQ"])
        self.assertEqual(m._inject_etf_allowlist(["AAPL"]), ["AAPL", "SPY", "QQQ"])

    def test_dedupes_already_present(self):
        m, _ = self._manager(["SPY", "QQQ"])
        self.assertEqual(m._inject_etf_allowlist(["SPY"]), ["SPY", "QQQ"])

    def test_skips_unresolvable_etf(self):
        m, broker = self._manager(["SPY", "NOPE"])
        broker.instrument_id_for_symbol.side_effect = lambda s: None if s == "NOPE" else 3000
        self.assertEqual(m._inject_etf_allowlist([]), ["SPY"])

    def test_empty_allowlist_is_noop(self):
        m, _ = self._manager([])
        self.assertEqual(m._inject_etf_allowlist(["AAPL"]), ["AAPL"])


if __name__ == "__main__":
    unittest.main()
