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
        self.alpaca_client.get_multi_bars.return_value = {}
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
            SimpleNamespace(symbol="SPAC", name="Acme Acquisition Corp. Class A", tradable=True, status="active"),
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
        self.assertEqual(candidates, ["BTC/EUR", "ETH/EUR"])

    def test_looks_like_etf_does_not_reject_common_stocks_ending_in_x(self) -> None:
        self.assertFalse(self.manager._looks_like_etf(SimpleNamespace(symbol="NFLX", name="Netflix, Inc.")))
        self.assertFalse(self.manager._looks_like_etf(SimpleNamespace(symbol="CVX", name="Chevron Corporation")))
        self.assertTrue(self.manager._looks_like_etf(SimpleNamespace(symbol="SPY", name="SPDR S&P 500 ETF Trust")))

    def test_select_trading_universe_uses_gpt_output_and_sanitizes_symbols(self) -> None:
        self.manager.get_current_universe = Mock(return_value={"STOCK": [], "CRYPTO": []})
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
        self.manager._generate_parallel_symbol_dossiers = Mock(
            side_effect=[
                [
                    {"symbol": "MSFT", "summary": "Strong dossier", "conviction_score": 88},
                    {"symbol": "AAPL", "summary": "Also solid", "conviction_score": 80},
                ],
                [
                    {"symbol": "BTC/EUR", "summary": "Strong dossier", "conviction_score": 91},
                    {"symbol": "ETH/EUR", "summary": "Also solid", "conviction_score": 84},
                ],
            ]
        )
        self.gpt_client.request_universe_final_selection_from_dossiers.side_effect = [
            {"symbols": ["MSFT"], "reasoning": "stock final"},
            {"symbols": ["BTC"], "reasoning": "crypto final"},
        ]

        universe = self.manager.select_trading_universe()

        self.assertEqual(universe, {"STOCK": ["MSFT", "AAPL"], "CRYPTO": ["BTC/EUR", "ETH/EUR"]})
        self.assertEqual(self.manager._generate_parallel_symbol_dossiers.call_count, 2)
        self.assertEqual(self.gpt_client.request_universe_final_selection_from_dossiers.call_count, 2)

    def test_select_category_universe_uses_dossiers_and_final_consolidation(self) -> None:
        payload = [{"symbol": f"S{index:03d}", "name": f"Stock {index}", "status": "active", "tradable": True, "fractionable": True} for index in range(7)]
        self.manager._build_prefiltered_payload = Mock(return_value=payload)
        self.manager._generate_parallel_symbol_dossiers = Mock(
            return_value=[
                {"symbol": "S000", "summary": "good", "conviction_score": 70},
                {"symbol": "S002", "summary": "good", "conviction_score": 76},
                {"symbol": "S005", "summary": "best", "conviction_score": 83},
                {"symbol": "S006", "summary": "good", "conviction_score": 79},
            ]
        )
        self.gpt_client.request_universe_final_selection_from_dossiers.return_value = {
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
        self.manager._generate_parallel_symbol_dossiers.assert_called_once()
        self.gpt_client.request_universe_final_selection_from_dossiers.assert_called_once()

    def test_generate_parallel_symbol_dossiers_preserves_candidate_order(self) -> None:
        candidates = [
            {"symbol": "S001", "name": "Stock 1", "fractionable": True, "prefilter_score": 10},
            {"symbol": "S002", "name": "Stock 2", "fractionable": True, "prefilter_score": 11},
        ]

        def dossier_side_effect(category, candidate, peer_context):
            symbol = candidate["symbol"]
            return {
                "symbol": symbol,
                "category": category,
                "summary": f"{symbol} summary",
                "bull_case": [f"{symbol} bull"],
                "bear_case": [f"{symbol} bear"],
                "recent_catalysts": [f"{symbol} catalyst"],
                "key_risks": [f"{symbol} risk"],
                "theme_tags": [f"{symbol} theme"],
                "news_sentiment": "positive",
                "quality_score": 80,
                "liquidity_score": 81,
                "momentum_score": 82,
                "downside_control_score": 83,
                "fit_score": 84,
                "conviction_score": 85,
                "reasoning": f"{symbol} reasoning",
            }

        self.gpt_client.request_universe_symbol_dossier.side_effect = dossier_side_effect

        dossiers = self.manager._generate_parallel_symbol_dossiers(
            category="STOCK",
            candidates=candidates,
            required_count=1,
            preferred_symbols=[],
        )

        self.assertEqual([dossier["symbol"] for dossier in dossiers], ["S001", "S002"])

    def test_select_category_universe_tops_up_when_final_gpt_selection_is_incomplete(self) -> None:
        payload = [
            {"symbol": "S001", "name": "Stock 1", "status": "active", "tradable": True, "fractionable": True},
            {"symbol": "S002", "name": "Stock 2", "status": "active", "tradable": True, "fractionable": True},
            {"symbol": "S003", "name": "Stock 3", "status": "active", "tradable": True, "fractionable": True},
        ]
        self.manager._build_prefiltered_payload = Mock(return_value=payload)
        self.manager._generate_parallel_symbol_dossiers = Mock(
            return_value=[
                {"symbol": "S001", "summary": "good", "conviction_score": 75},
                {"symbol": "S002", "summary": "better", "conviction_score": 80},
            ]
        )
        self.gpt_client.request_universe_final_selection_from_dossiers.return_value = {
            "symbols": ["S002"],
            "reasoning": "final",
        }

        selected = self.manager._select_category_universe(
            category="STOCK",
            payload=payload,
            required_count=2,
            batch_size=10,
        )

        self.assertEqual(selected, ["S002", "S001"])

    def test_select_category_universe_falls_back_to_prefilter_when_no_dossiers_are_available(self) -> None:
        payload = [
            {"symbol": "S001", "name": "Stock 1", "status": "active", "tradable": True, "fractionable": True},
            {"symbol": "S002", "name": "Stock 2", "status": "active", "tradable": True, "fractionable": True},
            {"symbol": "S003", "name": "Stock 3", "status": "active", "tradable": True, "fractionable": True},
        ]
        self.manager._build_prefiltered_payload = Mock(return_value=payload)
        self.manager._generate_parallel_symbol_dossiers = Mock(return_value=[])

        selected = self.manager._select_category_universe(
            category="STOCK",
            payload=payload,
            required_count=2,
            batch_size=10,
        )

        self.assertEqual(selected, ["S001", "S002"])

    def test_select_trading_universe_keeps_previous_universe_if_candidate_loading_fails(self) -> None:
        self.manager.get_current_universe = Mock(return_value={"STOCK": ["MSFT"], "CRYPTO": ["BTC/EUR"]})
        self.manager._get_stock_candidate_payload = Mock(side_effect=RuntimeError("boom"))

        universe = self.manager.select_trading_universe()

        self.assertEqual(universe, {"STOCK": ["MSFT"], "CRYPTO": ["BTC/EUR"]})


if __name__ == "__main__":
    unittest.main()
