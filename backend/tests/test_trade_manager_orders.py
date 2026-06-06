import logging
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

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


if __name__ == "__main__":
    unittest.main()
