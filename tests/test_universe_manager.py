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
        risk_tolerance=3,
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

    def test_select_trading_universe_uses_gpt_output_and_sanitizes_symbols(self) -> None:
        self.manager._write_candidate_lists = Mock()
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
        self.gpt_client.request_universe_batch_shortlist.side_effect = [
            {"symbols": ["msft", "INVALID"], "reasoning": "stock batch"},
            {"symbols": ["btc", "INVALID"], "reasoning": "crypto batch"},
        ]
        self.gpt_client.request_universe_final_selection.side_effect = [
            {"symbols": ["MSFT"], "reasoning": "stock final"},
            {"symbols": ["BTC"], "reasoning": "crypto final"},
        ]

        universe = self.manager.select_trading_universe()

        self.assertEqual(universe, {"STOCK": ["MSFT"], "CRYPTO": ["BTC/EUR"]})
        self.assertEqual(self.gpt_client.request_universe_batch_shortlist.call_count, 2)
        self.assertEqual(self.gpt_client.request_universe_final_selection.call_count, 2)

    def test_select_category_universe_batches_all_candidates_and_consolidates(self) -> None:
        payload = [{"symbol": f"S{index:03d}", "name": f"Stock {index}", "status": "active", "tradable": True, "fractionable": True} for index in range(7)]
        self.gpt_client.request_universe_batch_shortlist.side_effect = [
            {"symbols": ["S000", "S002"], "reasoning": "batch 1"},
            {"symbols": ["S003", "S005"], "reasoning": "batch 2"},
            {"symbols": ["S006"], "reasoning": "batch 3"},
        ]
        self.gpt_client.request_universe_final_selection.return_value = {
            "symbols": ["S005", "S002"],
            "reasoning": "final",
        }

        selected = self.manager._select_category_universe(
            category="STOCK",
            payload=payload,
            required_count=2,
            batch_size=3,
        )

        self.assertEqual(selected, ["S005", "S002"])
        self.assertEqual(self.gpt_client.request_universe_batch_shortlist.call_count, 3)
        self.gpt_client.request_universe_final_selection.assert_called_once()


if __name__ == "__main__":
    unittest.main()
