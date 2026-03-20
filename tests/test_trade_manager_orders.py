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


class TradeManagerScriptManagedTests(unittest.TestCase):
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
        *,
        symbol: str = "AAPL",
        entry_price: float = 100.0,
        target_entry_price: float | None = None,
        quantity: float = 2.0,
        take_profit: float = 120.0,
        stop_loss: float = 95.0,
        trailing_stop_distance: float | None = 3.0,
        high_water_mark: float | None = None,
        trailing_stop_price: float | None = None,
        alpaca_order_id: str = "entry-order",
        exit_order_id: str | None = None,
        pending_close_reason: str | None = None,
    ) -> int:
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            """
            INSERT INTO trades (
                symbol, category, direction, status, entry_price, target_entry_price, quantity, allocated_capital,
                take_profit, stop_loss, trailing_stop_distance, high_water_mark, trailing_stop_price,
                alpaca_order_id, client_order_id, exit_order_id, pending_close_reason, reasoning
            ) VALUES (?, ?, 'LONG', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                "STOCK",
                status,
                entry_price,
                target_entry_price if target_entry_price is not None else entry_price,
                quantity,
                200.0,
                take_profit,
                stop_loss,
                trailing_stop_distance,
                high_water_mark,
                trailing_stop_price,
                alpaca_order_id,
                "client-order",
                exit_order_id,
                pending_close_reason,
                "initial",
            ),
        )
        trade_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        connection.commit()
        connection.close()
        return int(trade_id)

    def test_maybe_open_trade_stores_script_managed_pending_trade(self) -> None:
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
        self.alpaca_client.get_open_position.return_value = None
        self.alpaca_client.get_available_cash.return_value = 1000.0
        self.alpaca_client.place_limit_entry_order.return_value = {
            "order": type("Order", (), {"id": "entry-order"})(),
            "client_order_id": "entry-client",
            "quantity": 10.0,
        }

        self.manager.maybe_open_trade("STOCK", "AAPL")

        self.alpaca_client.place_limit_entry_order.assert_called_once()
        trade = self.manager.get_open_or_pending_trades()[0]
        self.assertEqual(trade["status"], "PENDING")
        self.assertEqual(trade["target_entry_price"], 100.0)
        self.assertEqual(trade["trailing_stop_distance"], 3.0)
        self.assertEqual(trade["exit_order_id"], None)
        self.assertEqual(trade["trade_score"], None)

    def test_maybe_open_trade_skips_symbol_with_existing_active_trade(self) -> None:
        self._insert_trade("OPEN")

        self.manager.maybe_open_trade("STOCK", "AAPL")

        self.alpaca_client.place_limit_entry_order.assert_not_called()
        self.assertEqual(len(self.manager.get_open_or_pending_trades()), 1)

    def test_maybe_open_trade_skips_when_alpaca_rejects_for_insufficient_balance(self) -> None:
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
        self.alpaca_client.get_open_position.return_value = None
        self.alpaca_client.get_available_cash.return_value = 1000.0
        self.alpaca_client.is_insufficient_balance_error.return_value = True
        self.alpaca_client.place_limit_entry_order.side_effect = RuntimeError("insufficient balance")

        self.manager.maybe_open_trade("STOCK", "AAPL")

        self.assertEqual(self.manager.get_open_or_pending_trades(), [])

    def test_evaluate_cycle_opens_highest_scored_batch_signals_first(self) -> None:
        self.config.max_open_trades_stock = 2
        self.data_manager.get_symbol_history.side_effect = [
            [{"close": 100.0}],
            [{"close": 200.0}],
            [{"close": 300.0}],
        ]
        self.alpaca_client.get_open_position.return_value = None
        self.alpaca_client.get_available_cash.return_value = 1000.0
        self.alpaca_client.place_limit_entry_order.side_effect = [
            {
                "order": type("Order", (), {"id": "entry-1"})(),
                "client_order_id": "entry-client-1",
                "quantity": 2.0,
            },
            {
                "order": type("Order", (), {"id": "entry-2"})(),
                "client_order_id": "entry-client-2",
                "quantity": 1.0,
            },
        ]
        self.gpt_client.build_symbol_payload.side_effect = lambda symbol, category, candles, existing: {
            "symbol": symbol,
            "category": category,
            "ohlcv_daily": candles,
        }
        self.gpt_client.request_batch_trade_signals.return_value = {
            "signals": [
                {
                    "action": "OPEN",
                    "symbol": "MSFT",
                    "entry_price": 200.0,
                    "take_profit": 240.0,
                    "stop_loss": 180.0,
                    "trailing_stop_distance": 5.0,
                    "trade_score": 91.0,
                    "confidence": 0.7,
                    "reasoning": "best",
                },
                {
                    "action": "OPEN",
                    "symbol": "AAPL",
                    "entry_price": 100.0,
                    "take_profit": 115.0,
                    "stop_loss": 92.0,
                    "trailing_stop_distance": 4.0,
                    "trade_score": 88.0,
                    "confidence": 0.8,
                    "reasoning": "second",
                },
                {
                    "action": "OPEN",
                    "symbol": "NVDA",
                    "entry_price": 300.0,
                    "take_profit": 360.0,
                    "stop_loss": 270.0,
                    "trailing_stop_distance": 8.0,
                    "trade_score": 72.0,
                    "confidence": 0.9,
                    "reasoning": "third",
                },
            ],
            "reasoning": "ranked batch",
        }

        self.manager.evaluate_cycle({"STOCK": ["AAPL", "MSFT", "NVDA"]})

        trades = self.manager.get_open_or_pending_trades()
        self.assertEqual([trade["symbol"] for trade in trades], ["MSFT", "AAPL"])
        self.assertEqual([trade["trade_score"] for trade in trades], [91.0, 88.0])

    def test_sync_pending_trade_promotes_filled_entry_to_open_and_initializes_trailing_state(self) -> None:
        trade_id = self._insert_trade("PENDING")
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.alpaca_client.get_order.return_value = type(
            "Order",
            (),
            {"status": "filled", "filled_at": None, "filled_avg_price": 101.5, "filled_qty": 2.0},
        )()
        self.alpaca_client.get_open_position.return_value = type(
            "Position",
            (),
            {"qty": "2", "avg_entry_price": "101.5", "current_price": "103.0"},
        )()
        self.alpaca_client.get_latest_price.return_value = 103.0

        self.manager.sync_pending_trade(trade)

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "OPEN")
        self.assertEqual(updated_trade["entry_price"], 101.5)
        self.assertEqual(updated_trade["quantity"], 2.0)
        self.assertEqual(updated_trade["high_water_mark"], 103.0)
        self.assertEqual(updated_trade["trailing_stop_price"], 100.0)
        self.assertIsNotNone(updated_trade["open_timestamp"])

    def test_sync_pending_trade_promotes_when_position_exists_even_if_order_is_not_filled(self) -> None:
        trade_id = self._insert_trade("PENDING", symbol="AAVE/USD", entry_price=111.87, quantity=27.560293)
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.alpaca_client.get_order.return_value = type(
            "Order",
            (),
            {"status": "new", "filled_at": None, "filled_avg_price": None, "filled_qty": None},
        )()
        self.alpaca_client.get_open_position.return_value = type(
            "Position",
            (),
            {"qty": "27.560293", "avg_entry_price": "111.87", "current_price": "112.4"},
        )()
        self.alpaca_client.get_latest_price.return_value = 112.4

        self.manager.sync_pending_trade(trade)

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "OPEN")
        self.assertEqual(updated_trade["entry_price"], 111.87)
        self.assertEqual(updated_trade["quantity"], 27.560293)
        self.assertEqual(updated_trade["current_price"], 112.4)
        self.assertIsNotNone(updated_trade["open_timestamp"])

    def test_sync_open_trade_requests_market_close_when_take_profit_is_hit(self) -> None:
        trade_id = self._insert_trade("OPEN", take_profit=105.0, stop_loss=95.0, high_water_mark=104.0)
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.alpaca_client.get_open_position.return_value = type(
            "Position",
            (),
            {"qty": "2", "current_price": "106.0"},
        )()
        self.alpaca_client.get_latest_price.return_value = 106.0
        self.alpaca_client.close_position_market.return_value = type(
            "Order",
            (),
            {"id": "exit-order", "client_order_id": "exit-client"},
        )()
        self.alpaca_client.get_order.return_value = type(
            "Order",
            (),
            {"status": "filled", "filled_avg_price": 106.2, "filled_at": None},
        )()

        self.manager.sync_open_trade(trade)

        self.alpaca_client.close_position_market.assert_called_once_with("AAPL")
        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "CLOSED")
        self.assertEqual(updated_trade["close_reason"], "TAKE_PROFIT")
        self.assertEqual(updated_trade["close_price"], 106.2)

    def test_sync_open_trade_uses_trailing_stop_when_it_is_tighter_than_stop_loss(self) -> None:
        trade_id = self._insert_trade(
            "OPEN",
            take_profit=130.0,
            stop_loss=95.0,
            high_water_mark=110.0,
            trailing_stop_distance=3.0,
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.alpaca_client.get_open_position.return_value = type(
            "Position",
            (),
            {"qty": "2", "current_price": "106.0"},
        )()
        self.alpaca_client.get_latest_price.return_value = 106.0
        self.alpaca_client.close_position_market.return_value = type(
            "Order",
            (),
            {"id": "exit-order", "client_order_id": "exit-client"},
        )()
        self.alpaca_client.get_order.return_value = type(
            "Order",
            (),
            {"status": "filled", "filled_avg_price": 105.5, "filled_at": None},
        )()

        self.manager.sync_open_trade(trade)

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "CLOSED")
        self.assertEqual(updated_trade["close_reason"], "TRAILING_STOP")
        self.assertEqual(updated_trade["close_price"], 105.5)


if __name__ == "__main__":
    unittest.main()
