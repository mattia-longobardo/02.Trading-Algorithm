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
            openai_api_key="k", alpaca_api_key="", alpaca_secret_key="", alpaca_base_url="x",
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


if __name__ == "__main__":
    unittest.main()
