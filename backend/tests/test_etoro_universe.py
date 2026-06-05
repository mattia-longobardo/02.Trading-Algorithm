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
        self.gpt = Mock()
        self.gpt.request_universe_symbol_dossier.side_effect = Exception("no gpt")
        self.manager = UniverseManager(self.config, logging.getLogger("t"), {PE: self.broker}, self.gpt)

    def test_etoro_candidate_payloads(self):
        stock = self.manager._get_etoro_stock_candidate_payload()
        crypto = self.manager._get_etoro_crypto_candidate_payload()
        self.assertEqual(stock[0]["symbol"], "AAPL")
        self.assertEqual(crypto[0]["symbol"], "BTC")

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

    def test_resolve_exchange_whitelist_none_when_no_match(self):
        manager, broker = self._manager()
        broker.list_exchanges.return_value = {99: "Tokyo Stock Exchange"}
        self.assertIsNone(manager._resolve_exchange_whitelist(broker))

    def test_resolve_exchange_whitelist_skips_broker_when_no_patterns(self):
        manager, broker = self._manager()
        manager.config.universe_stock_exchanges = ()
        self.assertIsNone(manager._resolve_exchange_whitelist(broker))
        broker.list_exchanges.assert_not_called()

    def test_cheap_score_penalizes_daily_spike(self):
        manager, _ = self._manager()
        calm = manager._cheap_prefilter_score({"popularity": 1000, "price_change_1d": 0.0})
        spiky = manager._cheap_prefilter_score({"popularity": 1000, "price_change_1d": 50.0})
        self.assertGreater(calm, spiky)

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
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", exch=99), wl))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", rate=1.0), wl))
        self.assertFalse(manager._passes_cheap_filter("STOCK", self._stock("X", tradable=False), wl))
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
            self._stock("BBB", exch=4, pop=9000),
            self._stock("CCC", exch=4, pop=5000),
            self._stock("TKO", exch=99, pop=99999),
        ]
        wl = manager._resolve_exchange_whitelist(broker)
        shortlist = manager._build_cheap_shortlist(broker, "STOCK", [], wl)
        symbols = [a["symbol"] for a in shortlist]
        self.assertEqual(len(shortlist), 2)
        self.assertEqual(symbols, ["BBB", "CCC"])
        self.assertNotIn("TKO", symbols)

    def test_build_cheap_shortlist_pins_preferred(self):
        manager, broker = self._manager()
        manager.config.universe_stock_shortlist = 2
        broker.list_exchanges.return_value = {4: "NASDAQ"}
        broker.discover_instruments.return_value = [
            self._stock("AAA", exch=4, pop=9000),
            self._stock("BBB", exch=4, pop=8000),
            self._stock("KEEP", exch=4, pop=1),
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


if __name__ == "__main__":
    unittest.main()
