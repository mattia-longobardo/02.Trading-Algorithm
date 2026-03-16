import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
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

from db import initialize_databases
from trade_manager import TradeManager
from utils import AppConfig


def make_config(db_path: str) -> AppConfig:
    return AppConfig(
        openai_api_key="test-openai-key",
        alpaca_api_key="test-alpaca-key",
        alpaca_secret_key="test-alpaca-secret",
        alpaca_base_url="https://paper-api.alpaca.markets",
        db_trades=db_path,
    )


class TradeManagerOrderUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.market_db_path = str(Path(self.temp_dir.name) / "market.sqlite3")
        self.db_path = str(Path(self.temp_dir.name) / "trades.sqlite3")
        initialize_databases(self.market_db_path, self.db_path)
        self.config = make_config(self.db_path)
        self.alpaca_client = Mock()
        self.data_manager = Mock()
        self.gpt_client = Mock()
        self.manager = TradeManager(
            config=self.config,
            logger=logging.getLogger("test"),
            alpaca_client=self.alpaca_client,
            data_manager=self.data_manager,
            gpt_client=self.gpt_client,
        )

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except PermissionError:
            pass

    def _insert_trade(
        self,
        status: str,
        broker_protection_type: str = "BRACKET",
        protection_order_id: str | None = None,
    ) -> int:
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            """
            INSERT INTO trades (
                symbol, category, direction, status, entry_price, quantity, allocated_capital,
                take_profit, stop_loss, trailing_stop_distance, alpaca_order_id, client_order_id, broker_protection_type,
                protection_order_id, reasoning
            ) VALUES (?, ?, 'LONG', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "AAPL",
                "STOCK",
                status,
                100.0,
                2.0,
                200.0,
                120.0,
                95.0,
                3.0,
                "parent-order",
                "client-order",
                broker_protection_type,
                protection_order_id,
                "initial",
            ),
        )
        trade_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.commit()
        connection.close()
        return int(trade_id)

    def test_update_open_trade_replaces_existing_exit_legs_without_creating_new_entry(self) -> None:
        trade_id = self._insert_trade("OPEN")
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        decision = {
            "new_take_profit": 125.0,
            "new_stop_loss": 97.5,
            "new_trailing_stop_distance": 4.0,
            "reasoning": "raise protection",
        }

        self.alpaca_client.supports_advanced_orders.return_value = True

        self.manager._recreate_updated_order(trade, decision)

        self.alpaca_client.replace_bracket_exit_orders.assert_called_once_with(
            "parent-order",
            take_profit=125.0,
            stop_loss=97.5,
        )
        self.alpaca_client.place_limit_bracket_order.assert_not_called()
        self.alpaca_client.cancel_order_chain.assert_not_called()

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["take_profit"], 125.0)
        self.assertEqual(updated_trade["stop_loss"], 97.5)
        self.assertEqual(updated_trade["trailing_stop_distance"], 4.0)
        self.assertEqual(updated_trade["alpaca_order_id"], "parent-order")

    def test_update_pending_trade_cancels_and_recreates_parent_bracket(self) -> None:
        trade_id = self._insert_trade("PENDING")
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        decision = {
            "new_take_profit": 126.0,
            "new_stop_loss": 96.5,
            "new_trailing_stop_distance": 5.0,
            "reasoning": "refresh pending setup",
        }

        self.alpaca_client.supports_advanced_orders.return_value = True
        self.alpaca_client.place_limit_bracket_order.return_value = {
            "order": type("Order", (), {"id": "replacement-parent"})(),
            "client_order_id": "replacement-client",
            "quantity": 2.0,
        }

        self.manager._recreate_updated_order(trade, decision)

        self.alpaca_client.cancel_order_chain.assert_called_once_with("parent-order")
        self.alpaca_client.place_limit_bracket_order.assert_called_once()
        self.alpaca_client.replace_bracket_exit_orders.assert_not_called()

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["alpaca_order_id"], "replacement-parent")
        self.assertEqual(updated_trade["client_order_id"], "replacement-client")
        self.assertEqual(updated_trade["take_profit"], 126.0)
        self.assertEqual(updated_trade["stop_loss"], 96.5)
        self.assertEqual(updated_trade["trailing_stop_distance"], 5.0)

    def test_sync_pending_trailing_stop_trade_places_broker_side_protection_after_fill(self) -> None:
        trade_id = self._insert_trade("PENDING", broker_protection_type="TRAILING_STOP")
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.alpaca_client.get_order.return_value = type(
            "Order",
            (),
            {"status": "filled", "filled_at": None, "filled_avg_price": 101.5},
        )()
        self.alpaca_client.place_trailing_stop_order.return_value = {
            "order": type("Order", (), {"id": "trail-order"})(),
            "client_order_id": "trail-client",
        }

        self.manager.sync_pending_trade(trade)

        self.alpaca_client.place_trailing_stop_order.assert_called_once_with(
            symbol="AAPL",
            quantity=2.0,
            category="STOCK",
            trail_price=3.0,
        )
        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "OPEN")
        self.assertEqual(updated_trade["entry_price"], 101.5)
        self.assertEqual(updated_trade["protection_order_id"], "trail-order")
        self.assertEqual(updated_trade["protection_client_order_id"], "trail-client")

    def test_update_open_trailing_stop_trade_replaces_trailing_order(self) -> None:
        trade_id = self._insert_trade(
            "OPEN",
            broker_protection_type="TRAILING_STOP",
            protection_order_id="trail-order",
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        decision = {
            "new_take_profit": 130.0,
            "new_stop_loss": 99.0,
            "new_trailing_stop_distance": 4.5,
            "reasoning": "widen trail",
        }

        self.manager._recreate_updated_order(trade, decision)

        self.alpaca_client.replace_trailing_stop_order.assert_called_once_with("trail-order", 4.5)
        self.alpaca_client.replace_bracket_exit_orders.assert_not_called()
        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["take_profit"], 130.0)
        self.assertEqual(updated_trade["stop_loss"], 99.0)
        self.assertEqual(updated_trade["trailing_stop_distance"], 4.5)

    def test_maybe_open_trade_uses_simple_entry_for_broker_side_trailing_stop_strategy(self) -> None:
        self.data_manager.get_symbol_history.return_value = [{"close": 100.0}]
        self.gpt_client.request_new_signal.return_value = {
            "action": "OPEN",
            "symbol": "AAPL",
            "entry_price": 100.0,
            "take_profit": 120.0,
            "stop_loss": 95.0,
            "trailing_stop_distance": 3.0,
            "confidence": 0.8,
            "reasoning": "trend setup",
        }
        self.alpaca_client.get_available_cash.return_value = 1000.0
        self.alpaca_client.supports_broker_side_trailing_stop.return_value = True
        self.alpaca_client.place_limit_entry_order.return_value = {
            "order": type("Order", (), {"id": "entry-order"})(),
            "client_order_id": "entry-client",
            "quantity": 10.0,
        }

        self.manager.maybe_open_trade("STOCK", "AAPL")

        self.alpaca_client.place_limit_entry_order.assert_called_once()
        self.alpaca_client.place_limit_bracket_order.assert_not_called()
        trade = self.manager.get_open_or_pending_trades()[0]
        self.assertEqual(trade["broker_protection_type"], "TRAILING_STOP")
        self.assertEqual(trade["alpaca_order_id"], "entry-order")


if __name__ == "__main__":
    unittest.main()
