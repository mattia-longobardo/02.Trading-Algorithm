import logging
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

alpaca_client_stub = ModuleType("alpaca_client")
alpaca_client_stub.AlpacaClient = object
sys.modules.setdefault("alpaca_client", alpaca_client_stub)

gpt_client_stub = ModuleType("gpt_client")
gpt_client_stub.GPTClient = object
sys.modules.setdefault("gpt_client", gpt_client_stub)

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from universe_manager import UniverseManager
from utils import AppConfig


def make_config() -> AppConfig:
    return AppConfig(
        openai_api_key="test-openai-key",
        alpaca_api_key="test-alpaca-key",
        alpaca_secret_key="test-alpaca-secret",
        alpaca_base_url="https://paper-api.alpaca.markets",
        currency="EUR",
    )


class UniverseManagerCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.alpaca_client = Mock()
        self.gpt_client = Mock()
        self.manager = UniverseManager(
            config=make_config(),
            logger=logging.getLogger("test"),
            alpaca_client=self.alpaca_client,
            gpt_client=self.gpt_client,
        )
        self.manager.candidate_logger = Mock()

    def test_get_stock_candidates_filters_invalid_assets_sorts_and_deduplicates(self) -> None:
        self.alpaca_client.list_assets.return_value = [
            SimpleNamespace(symbol="MSFT", name="Microsoft Corporation", tradable=True, status="active"),
            SimpleNamespace(symbol="AAPL", name="Apple Inc.", tradable=True, status="ACTIVE"),
            SimpleNamespace(symbol="SPY", name="SPDR S&P 500 ETF Trust", tradable=True, status="active"),
            SimpleNamespace(symbol="WARR", name="Acme Warrant", tradable=True, status="active"),
            SimpleNamespace(symbol="PREF", name="Acme Preferred Shares", tradable=True, status="active"),
            SimpleNamespace(symbol="HALT", name="Trading Halt Corp", tradable=True, status="inactive"),
            SimpleNamespace(symbol="PRIVATE", name="Private Corp", tradable=False, status="active"),
            SimpleNamespace(symbol="MSFT", name="Microsoft Corporation", tradable=True, status="active"),
        ]

        candidates = self.manager._get_stock_candidates()

        self.alpaca_client.list_assets.assert_called_once_with("US_EQUITY")
        self.assertEqual(candidates, ["AAPL", "MSFT"])

    def test_get_crypto_candidates_keeps_only_active_tradable_symbols_with_quote_currency(self) -> None:
        self.alpaca_client.list_assets.return_value = [
            SimpleNamespace(symbol="BTC/EUR", tradable=True, status="active"),
            SimpleNamespace(symbol="eth/eur", tradable=True, status="ACTIVE"),
            SimpleNamespace(symbol="SOL/USD", tradable=True, status="active"),
            SimpleNamespace(symbol="DOGE/EUR", tradable=False, status="active"),
            SimpleNamespace(symbol="ADA/EUR", tradable=True, status="inactive"),
            SimpleNamespace(symbol="BTC/EUR", tradable=True, status="active"),
        ]

        candidates = self.manager._get_crypto_candidates()

        self.alpaca_client.list_assets.assert_called_once_with("CRYPTO")
        self.assertEqual(candidates, ["BTC/EUR", "eth/eur"])

    def test_select_weekly_universe_logs_all_stock_and_crypto_candidates_to_dedicated_logger(self) -> None:
        self.manager._get_stock_candidate_payload = Mock(
            return_value=[
                {"symbol": "AAPL", "name": "Apple Inc.", "status": "active", "tradable": True, "fractionable": True},
                {"symbol": "MSFT", "name": "Microsoft Corporation", "status": "active", "tradable": True, "fractionable": True},
            ]
        )
        self.manager._get_crypto_candidate_payload = Mock(
            return_value=[
                {"symbol": "BTC/EUR", "name": "Bitcoin", "status": "active", "tradable": True, "fractionable": True},
                {"symbol": "ETH/EUR", "name": "Ethereum", "status": "active", "tradable": True, "fractionable": True},
            ]
        )
        self.gpt_client.request_weekly_universe.return_value = {
            "stocks": ["MSFT"],
            "crypto": ["BTC/EUR"],
        }

        universe = self.manager.select_weekly_universe()

        self.assertEqual(universe, {"STOCK": ["MSFT"], "CRYPTO": ["BTC/EUR"]})
        self.manager.candidate_logger.info.assert_called_once()
        logged_message, *logged_args = self.manager.candidate_logger.info.call_args[0]
        self.assertIn("Weekly universe candidates", logged_message)
        self.assertEqual(logged_args[0], 2)
        self.assertEqual(logged_args[1], 2)
        self.assertIn('"symbol": "AAPL"', logged_args[2])
        self.assertIn('"symbol": "BTC/EUR"', logged_args[3])


if __name__ == "__main__":
    unittest.main()
