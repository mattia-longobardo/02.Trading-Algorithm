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


if __name__ == "__main__":
    unittest.main()
