import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases, upsert_instrument_mapping
from core.utils import AppConfig, PROVIDER_ETORO


def _tm(broker):
    from services.trade_manager import TradeManager
    cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                    etoro_account_type="demo", order_await_timeout_minutes=360)
    return TradeManager(cfg, logging.getLogger("t"), {PROVIDER_ETORO: broker}, Mock(), Mock())


class ResolveSubmittedOrderTests(unittest.TestCase):
    def _trade(self, **over):
        t = {"id": 1, "symbol": "AAPL", "category": "STOCK", "status": "PENDING",
             "provider": "etoro", "order_id": "555", "order_submitted_at": "2999-01-01T00:00:00+00:00",
             "instrument_id": 9422, "entry_price": 100.0, "target_entry_price": 100.0,
             "quantity": 1.0, "allocated_capital": 100.0, "position_confirmed": 0}
        t.update(over)
        return t

    def test_executed_activates_open(self):
        broker = Mock()
        broker.get_order_status.return_value = {"executed": True, "rejected": False, "waiting": False,
                                                "canceled": False, "position_id": "9001", "error_message": None}
        broker.get_open_position.return_value = {"position_id": "9001", "units": 2.0, "open_rate": 101.0}
        tm = _tm(broker)
        captured = {}
        tm._activate_trade_from_position = lambda trade, pos, res: captured.update(pos=pos, res=res)
        tm._resolve_submitted_order(self._trade())
        self.assertIsNotNone(captured["pos"])

    def test_rejected_cancels_with_reason(self):
        broker = Mock()
        broker.get_order_status.return_value = {"executed": False, "rejected": True, "waiting": False,
                                                "canceled": False, "position_id": None,
                                                "error_message": "manual Trading is disallowed"}
        tm = _tm(broker)
        seen = {}
        tm._cancel_pending_trade_record = lambda trade, reason: seen.update(reason=reason)
        tm._resolve_submitted_order(self._trade())
        self.assertEqual(seen["reason"], "ENTRY_REJECTED")

    def test_waiting_keeps_pending(self):
        broker = Mock()
        broker.get_order_status.return_value = {"executed": False, "rejected": False, "waiting": True,
                                                "canceled": False, "position_id": None, "error_message": None}
        tm = _tm(broker)
        tm._cancel_pending_trade_record = Mock()
        tm._activate_trade_from_position = Mock()
        tm._resolve_submitted_order(self._trade())
        tm._cancel_pending_trade_record.assert_not_called()
        tm._activate_trade_from_position.assert_not_called()

    def test_waiting_past_timeout_cancels_order(self):
        broker = Mock()
        broker.get_order_status.return_value = {"executed": False, "rejected": False, "waiting": True,
                                                "canceled": False, "position_id": None, "error_message": None}
        tm = _tm(broker)
        seen = {}
        tm._cancel_pending_trade_record = lambda trade, reason: seen.update(reason=reason)
        tm._resolve_submitted_order(self._trade(order_submitted_at="2000-01-01T00:00:00+00:00"))
        broker.cancel_order.assert_called_once_with("555")
        self.assertEqual(seen["reason"], "ORDER_AWAIT_TIMEOUT")

    def test_status_none_is_left_alone(self):
        broker = Mock()
        broker.get_order_status.return_value = None
        tm = _tm(broker)
        tm._cancel_pending_trade_record = Mock()
        tm._activate_trade_from_position = Mock()
        tm._resolve_submitted_order(self._trade())
        tm._cancel_pending_trade_record.assert_not_called()
        tm._activate_trade_from_position.assert_not_called()

    def test_status_none_past_timeout_cancels_order(self):
        broker = Mock()
        broker.get_order_status.return_value = None
        tm = _tm(broker)
        seen = {}
        tm._cancel_pending_trade_record = lambda trade, reason: seen.update(reason=reason)
        tm._resolve_submitted_order(self._trade(order_submitted_at="2000-01-01T00:00:00+00:00"))
        broker.cancel_order.assert_called_once_with("555")
        self.assertEqual(seen["reason"], "ORDER_AWAIT_TIMEOUT")


class PositionConfirmedTests(unittest.TestCase):
    def _open_trade(self, **over):
        t = {"id": 5, "symbol": "AAPL", "category": "STOCK", "status": "OPEN", "provider": "etoro",
             "instrument_id": 9422, "entry_price": 100.0, "quantity": 1.0, "allocated_capital": 100.0,
             "position_id": "9001", "position_confirmed": 0, "current_price": 100.0,
             "stop_loss": 90.0, "take_profit": 130.0}
        t.update(over)
        return t

    def test_unconfirmed_trade_not_externally_closed(self):
        broker = Mock()
        broker.get_open_position.return_value = None
        tm = _tm(broker)
        closed = {}
        tm._close_trade_without_position = lambda trade, *a, **k: closed.setdefault("hit", True)
        tm.sync_open_trade(self._open_trade(position_confirmed=0))
        self.assertNotIn("hit", closed)

    def test_confirmed_trade_is_externally_closed(self):
        broker = Mock()
        broker.get_open_position.return_value = None
        tm = _tm(broker)
        closed = {}
        tm._close_trade_without_position = lambda trade, *a, **k: closed.setdefault("hit", True)
        tm.sync_open_trade(self._open_trade(position_confirmed=1))
        self.assertTrue(closed.get("hit"))


class PlannedRMetricsTests(unittest.TestCase):
    """Integration tests: planned R fields persisted at trade open; realized R at close."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        initialize_databases(self.market_db, self.trades_db)
        upsert_instrument_mapping(self.market_db, "AAA", 1, "CRYPTO", "AAA coin", True)
        from services.trade_manager import TradeManager
        cfg = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
            etoro_account_type="demo",
            db_trades=self.trades_db, db_market_data=self.market_db,
        )
        broker = Mock()
        self.manager = TradeManager(cfg, logging.getLogger("t"), {PROVIDER_ETORO: broker}, Mock(), Mock())

    def tearDown(self):
        self.tmp.cleanup()

    def _signal(self, entry_price, stop_loss, take_profit):
        return {
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "reasoning": "test",
            "confidence": 0.8,
            "trade_score": 1.0,
        }

    def _row(self):
        conn = sqlite3.connect(self.trades_db)
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM trades WHERE symbol='AAA'").fetchone())
        conn.close()
        return row

    def test_open_persists_planned_r(self):
        # entry=100, stop=90, tp=130 → risk=10, RR=3.0
        self.manager._save_new_trade(
            "CRYPTO", "AAA",
            self._signal(entry_price=100.0, stop_loss=90.0, take_profit=130.0),
            instrument_id=1, allocated_capital=1000.0,
        )
        row = self._row()
        self.assertAlmostEqual(row["planned_risk_per_unit"], 10.0, places=6)
        self.assertAlmostEqual(row["planned_reward_risk"], 3.0, places=6)

    def test_close_persists_realized_r(self):
        # Open a trade directly in the DB with stop_loss, high/low water marks
        conn = sqlite3.connect(self.trades_db)
        conn.execute(
            """INSERT INTO trades (symbol, category, status, entry_price, quantity, allocated_capital,
                 current_price, stop_loss, high_water_mark, low_water_mark,
                 instrument_id, provider, position_confirmed)
               VALUES ('AAA','CRYPTO','OPEN', 100.0, 10.0, 1000.0,
                 110.0, 90.0, 115.0, 98.0,
                 1, 'etoro', 1)""",
        )
        conn.commit()
        conn.row_factory = sqlite3.Row
        trade = dict(conn.execute("SELECT * FROM trades WHERE symbol='AAA'").fetchone())
        conn.close()
        self.manager._mark_trade_closed(trade, "TAKE_PROFIT", 120.0)
        row = self._row()
        # realized_r = (120-100)/(100-90) = 2.0
        self.assertAlmostEqual(row["realized_r"], 2.0, places=6)
        # mfe = excursion_r(100, 90, 115) = (115-100)/10 = 1.5
        self.assertAlmostEqual(row["mfe"], 1.5, places=6)
        # mae = excursion_r(100, 90, 98) = (98-100)/10 = -0.2
        self.assertAlmostEqual(row["mae"], -0.2, places=6)


if __name__ == "__main__":
    unittest.main()
