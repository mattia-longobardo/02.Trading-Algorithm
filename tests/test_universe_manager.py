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


if __name__ == "__main__":
    unittest.main()
