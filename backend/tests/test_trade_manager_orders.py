import logging
import sqlite3
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from enum import Enum
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
        self.alpaca_client.is_insufficient_balance_error.return_value = False

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
        category: str = "STOCK",
        entry_price: float = 100.0,
        target_entry_price: float | None = None,
        quantity: float = 2.0,
        take_profit: float = 120.0,
        trailing_take_profit_distance: float | None = None,
        trailing_take_profit_activation_pct: float | None = None,
        stop_loss: float = 95.0,
        trailing_stop_distance: float | None = 3.0,
        high_water_mark: float | None = None,
        trailing_take_profit_price: float | None = None,
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
                take_profit, trailing_take_profit_distance, trailing_take_profit_activation_pct,
                stop_loss, trailing_stop_distance,
                high_water_mark, trailing_take_profit_price, trailing_stop_price,
                alpaca_order_id, client_order_id, exit_order_id, pending_close_reason, reasoning
            ) VALUES (?, ?, 'LONG', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                category,
                status,
                entry_price,
                target_entry_price if target_entry_price is not None else entry_price,
                quantity,
                200.0,
                take_profit,
                trailing_take_profit_distance,
                trailing_take_profit_activation_pct,
                stop_loss,
                trailing_stop_distance,
                high_water_mark,
                trailing_take_profit_price,
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
            "trailing_take_profit_distance": 6.0,
            "trailing_take_profit_activation_pct": 5.0,
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
        self.assertEqual(trade["trailing_take_profit_distance"], 6.0)
        self.assertEqual(trade["trailing_take_profit_activation_pct"], 5.0)
        self.assertEqual(trade["trailing_stop_distance"], 3.0)
        self.assertEqual(trade["exit_order_id"], None)
        self.assertEqual(trade["trade_score"], None)

    def test_maybe_open_trade_stores_submitted_crypto_limit_separately_from_target_entry(self) -> None:
        self.data_manager.get_symbol_history.return_value = [{"close": 1.78}]
        self.gpt_client.request_new_signal.return_value = {
            "action": "OPEN",
            "symbol": "RENDER/USD",
            "entry_price": 1.78,
            "take_profit": 2.1,
            "stop_loss": 1.62,
            "confidence": 0.74,
            "reasoning": "crypto breakout",
        }
        self.alpaca_client.get_open_position.return_value = None
        self.alpaca_client.get_available_cash.return_value = 1000.0
        self.alpaca_client.place_limit_entry_order.return_value = {
            "order": type("Order", (), {"id": "entry-order"})(),
            "client_order_id": "entry-client",
            "quantity": 560.0,
            "submitted_entry_price": 1.7831,
        }

        self.manager.maybe_open_trade("CRYPTO", "RENDER/USD")

        trade = self.manager.get_open_or_pending_trades()[0]
        self.assertEqual(trade["symbol"], "RENDER/USD")
        self.assertEqual(trade["category"], "CRYPTO")
        self.assertEqual(trade["entry_price"], 1.7831)
        self.assertEqual(trade["target_entry_price"], 1.78)

    def test_maybe_open_trade_skips_crypto_when_live_price_moved_too_far(self) -> None:
        self.data_manager.get_symbol_history.return_value = [{"close": 1.78}]
        self.gpt_client.request_new_signal.return_value = {
            "action": "OPEN",
            "symbol": "RENDER/USD",
            "entry_price": 1.78,
            "take_profit": 2.1,
            "stop_loss": 1.62,
            "confidence": 0.74,
            "reasoning": "crypto breakout",
        }
        self.alpaca_client.get_open_position.return_value = None
        self.alpaca_client.get_available_cash.return_value = 1000.0
        self.alpaca_client.place_limit_entry_order.side_effect = ValueError(
            "Live ask 1.79000000 is too far above target 1.78000000 for RENDER/USD"
        )

        self.manager.maybe_open_trade("CRYPTO", "RENDER/USD")

        self.assertEqual(self.manager.get_open_or_pending_trades(), [])

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
            "trailing_take_profit_distance": 6.0,
            "trailing_take_profit_activation_pct": 5.0,
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
        self.assertEqual(updated_trade["trailing_take_profit_price"], None)
        self.assertEqual(updated_trade["trailing_stop_price"], 100.0)
        self.assertIsNotNone(updated_trade["open_timestamp"])

    def test_sync_pending_trade_closes_canceled_entry_when_status_is_enum_value(self) -> None:
        class FakeOrderStatus(Enum):
            CANCELED = "canceled"

        trade_id = self._insert_trade("PENDING", symbol="RENDER/USD")
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.alpaca_client.get_order.return_value = type(
            "Order",
            (),
            {
                "status": FakeOrderStatus.CANCELED,
                "canceled_at": "2026-03-24T18:38:32+00:00",
                "updated_at": "2026-03-24T18:38:32+00:00",
            },
        )()
        self.alpaca_client.get_open_position.return_value = None

        self.manager.sync_pending_trade(trade)

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "CANCELLED")
        self.assertEqual(updated_trade["close_reason"], "CANCELED")

    def test_review_stale_pending_trade_cancels_order_when_gpt_says_cancel(self) -> None:
        trade_id = self._insert_trade("PENDING", symbol="HYPE/USD", entry_price=20.0, target_entry_price=19.5, alpaca_order_id="stale-order")
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.data_manager.get_symbol_history.return_value = [{"close": 20.0}, {"close": 21.0}]
        self.gpt_client.request_pending_trade_review.return_value = {
            "action": "CANCEL",
            "confidence": 0.91,
            "reasoning": "Momentum and catalysts have weakened materially.",
        }

        self.manager._review_single_stale_pending_trade(trade)

        self.alpaca_client.cancel_order.assert_called_once_with("stale-order")
        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "CANCELLED")
        self.assertEqual(updated_trade["close_reason"], "STALE_PENDING_CANCELED")
        self.assertEqual(updated_trade["reasoning"], "Momentum and catalysts have weakened materially.")

    def test_sync_pending_trade_promotes_when_position_exists_even_if_order_is_not_filled(self) -> None:
        trade_id = self._insert_trade("PENDING", symbol="AAVE/USD", category="CRYPTO", entry_price=111.87, quantity=27.560293)
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

    def test_sync_pending_trade_resubmits_live_crypto_entry_with_new_order(self) -> None:
        trade_id = self._insert_trade(
            "PENDING",
            symbol="RENDER/USD",
            category="CRYPTO",
            entry_price=1.78,
            target_entry_price=1.78,
            quantity=56179.780898,
            alpaca_order_id="old-entry-order",
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        stale_timestamp = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        self.alpaca_client.get_order.return_value = type(
            "Order",
            (),
            {
                "status": "new",
                "submitted_at": stale_timestamp,
                "updated_at": stale_timestamp,
                "limit_price": 1.78,
            },
        )()
        self.alpaca_client.get_open_position.return_value = None
        self.alpaca_client.get_latest_quote.return_value = {"ask_price": 1.7807, "bid_price": 1.7802}
        self.alpaca_client.place_limit_entry_order.return_value = {
            "order": type("Order", (), {"id": "new-entry-order"})(),
            "client_order_id": "entry-client-2",
            "quantity": 56090.0,
            "submitted_entry_price": 1.78337,
        }

        self.manager.sync_pending_trade(trade)

        self.alpaca_client.cancel_order.assert_called_once_with("old-entry-order")
        self.alpaca_client.place_limit_entry_order.assert_called_once_with(
            symbol="RENDER/USD",
            category="CRYPTO",
            entry_price=1.78,
            allocated_capital=200.0,
        )
        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "PENDING")
        self.assertEqual(updated_trade["alpaca_order_id"], "new-entry-order")
        self.assertEqual(updated_trade["client_order_id"], "entry-client-2")
        self.assertEqual(updated_trade["entry_price"], 1.78337)
        self.assertEqual(updated_trade["target_entry_price"], 1.78)

    def test_sync_pending_trade_cancels_crypto_entry_when_price_moves_away(self) -> None:
        trade_id = self._insert_trade(
            "PENDING",
            symbol="RENDER/USD",
            category="CRYPTO",
            entry_price=1.78,
            target_entry_price=1.78,
            quantity=56179.780898,
            alpaca_order_id="old-entry-order",
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        stale_timestamp = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        self.alpaca_client.get_order.return_value = type(
            "Order",
            (),
            {
                "status": "new",
                "submitted_at": stale_timestamp,
                "updated_at": stale_timestamp,
                "limit_price": 1.78,
            },
        )()
        self.alpaca_client.get_open_position.return_value = None
        self.alpaca_client.get_latest_quote.return_value = {"ask_price": 1.81, "bid_price": 1.8095}

        self.manager.sync_pending_trade(trade)

        self.alpaca_client.cancel_order.assert_called_once_with("old-entry-order")
        self.alpaca_client.place_limit_entry_order.assert_not_called()
        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "CANCELLED")
        self.assertEqual(updated_trade["close_reason"], "ENTRY_PRICE_MOVED")

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

    def test_sync_open_trade_arms_trailing_take_profit_after_activation_threshold(self) -> None:
        trade_id = self._insert_trade(
            "OPEN",
            entry_price=100.0,
            take_profit=120.0,
            trailing_take_profit_distance=2.0,
            trailing_take_profit_activation_pct=5.0,
            stop_loss=95.0,
            high_water_mark=104.0,
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.alpaca_client.get_open_position.return_value = type(
            "Position",
            (),
            {"qty": "2", "current_price": "106.0"},
        )()
        self.alpaca_client.get_latest_price.return_value = 106.0

        self.manager.sync_open_trade(trade)

        self.alpaca_client.close_position_market.assert_not_called()
        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "OPEN")
        self.assertEqual(updated_trade["high_water_mark"], 106.0)
        self.assertEqual(updated_trade["trailing_take_profit_price"], 104.0)

    def test_sync_open_trade_does_not_arm_trailing_take_profit_below_activation_threshold(self) -> None:
        trade_id = self._insert_trade(
            "OPEN",
            entry_price=100.0,
            take_profit=120.0,
            trailing_take_profit_distance=2.0,
            trailing_take_profit_activation_pct=5.0,
            stop_loss=95.0,
            high_water_mark=103.0,
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.alpaca_client.get_open_position.return_value = type(
            "Position",
            (),
            {"qty": "2", "current_price": "104.0"},
        )()
        self.alpaca_client.get_latest_price.return_value = 104.0

        self.manager.sync_open_trade(trade)

        self.alpaca_client.close_position_market.assert_not_called()
        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "OPEN")
        self.assertEqual(updated_trade["high_water_mark"], 104.0)
        self.assertIsNone(updated_trade["trailing_take_profit_price"])

    def test_sync_open_trade_closes_when_trailing_take_profit_is_hit_after_activation(self) -> None:
        trade_id = self._insert_trade(
            "OPEN",
            entry_price=100.0,
            take_profit=120.0,
            trailing_take_profit_distance=2.0,
            trailing_take_profit_activation_pct=5.0,
            stop_loss=95.0,
            high_water_mark=108.0,
            trailing_take_profit_price=106.0,
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
            {"status": "filled", "filled_avg_price": 105.8, "filled_at": None},
        )()

        self.manager.sync_open_trade(trade)

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["status"], "CLOSED")
        self.assertEqual(updated_trade["close_reason"], "TRAILING_TAKE_PROFIT")
        self.assertEqual(updated_trade["close_price"], 105.8)

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

    def test_refresh_single_open_trade_protection_updates_trailing_take_profit_fields(self) -> None:
        trade_id = self._insert_trade(
            "OPEN",
            entry_price=100.0,
            take_profit=120.0,
            trailing_take_profit_distance=2.0,
            trailing_take_profit_activation_pct=5.0,
            high_water_mark=108.0,
            trailing_take_profit_price=106.0,
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.data_manager.get_symbol_history.return_value = [{"close": 104.0}, {"close": 108.0}]
        self.gpt_client.request_open_trade_protection_review.return_value = {
            "trailing_take_profit_distance": 3.5,
            "trailing_take_profit_activation_pct": 3.0,
            "reasoning": "Profit cushion is solid, lower activation and tighten the trail.",
        }

        self.manager._refresh_single_open_trade_protection(trade)

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["trailing_take_profit_distance"], 3.5)
        self.assertEqual(updated_trade["trailing_take_profit_activation_pct"], 3.0)
        self.assertEqual(updated_trade["trailing_take_profit_price"], 104.5)

    def test_refresh_single_open_trade_protection_disables_trailing_when_both_fields_null(self) -> None:
        trade_id = self._insert_trade(
            "OPEN",
            entry_price=100.0,
            take_profit=120.0,
            trailing_take_profit_distance=2.0,
            trailing_take_profit_activation_pct=5.0,
            high_water_mark=108.0,
            trailing_take_profit_price=106.0,
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.data_manager.get_symbol_history.return_value = [{"close": 104.0}, {"close": 108.0}]
        self.gpt_client.request_open_trade_protection_review.return_value = {
            "trailing_take_profit_distance": None,
            "trailing_take_profit_activation_pct": None,
            "reasoning": "Disable trailing for now.",
        }

        self.manager._refresh_single_open_trade_protection(trade)

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertIsNone(updated_trade["trailing_take_profit_distance"])
        self.assertIsNone(updated_trade["trailing_take_profit_activation_pct"])
        self.assertIsNone(updated_trade["trailing_take_profit_price"])

    def test_refresh_single_open_trade_protection_keeps_previous_when_fields_mismatched(self) -> None:
        trade_id = self._insert_trade(
            "OPEN",
            entry_price=100.0,
            take_profit=120.0,
            trailing_take_profit_distance=2.0,
            trailing_take_profit_activation_pct=5.0,
            high_water_mark=108.0,
            trailing_take_profit_price=106.0,
        )
        trade = self.manager.get_trade(trade_id)
        assert trade is not None

        self.data_manager.get_symbol_history.return_value = [{"close": 104.0}, {"close": 108.0}]
        self.gpt_client.request_open_trade_protection_review.return_value = {
            "trailing_take_profit_distance": 3.0,
            "trailing_take_profit_activation_pct": None,
            "reasoning": "Mismatched response should be rejected.",
        }

        self.manager._refresh_single_open_trade_protection(trade)

        updated_trade = self.manager.get_trade(trade_id)
        assert updated_trade is not None
        self.assertEqual(updated_trade["trailing_take_profit_distance"], 2.0)
        self.assertEqual(updated_trade["trailing_take_profit_activation_pct"], 5.0)


if __name__ == "__main__":
    unittest.main()
