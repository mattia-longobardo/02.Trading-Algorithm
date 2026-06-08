import logging
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig, PROVIDER_ETORO


def _manager(cash=10_000.0, min_trade=50.0):
    """TradeManager with a mocked broker + gpt client, no DB/network."""
    from services.trade_manager import TradeManager
    cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                    max_open_trades_stock=3, max_open_trades_crypto=3,
                    etoro_min_trade_amount=min_trade)
    broker = Mock()
    broker.get_available_cash.return_value = cash
    broker.get_account_equity.return_value = 10_000.0
    data_manager = Mock()
    gpt = Mock()
    tm = TradeManager(cfg, logging.getLogger("t"), {PROVIDER_ETORO: broker}, data_manager, gpt)
    tm.get_open_or_pending_trades = Mock(return_value=[])
    return tm, broker, gpt


class LiquidityHelperTests(unittest.TestCase):
    def test_true_when_cash_at_or_above_minimum(self):
        tm, _, _ = _manager(cash=50.0, min_trade=50.0)
        self.assertTrue(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))

    def test_false_when_cash_below_minimum(self):
        tm, _, _ = _manager(cash=49.99, min_trade=50.0)
        self.assertFalse(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))

    def test_permissive_when_cash_lookup_raises(self):
        tm, broker, _ = _manager(min_trade=50.0)
        broker.get_available_cash.side_effect = Exception("api down")
        self.assertTrue(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))

    def test_true_when_no_minimum_configured(self):
        tm, broker, _ = _manager(cash=0.0, min_trade=0.0)
        self.assertTrue(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))

    def test_false_when_no_broker(self):
        tm, _, _ = _manager()
        tm.broker = Mock(return_value=None)
        self.assertFalse(tm._has_liquidity_for_new_trade(PROVIDER_ETORO))


if __name__ == "__main__":
    unittest.main()
