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
        tm_above, _, _ = _manager(cash=100.0, min_trade=50.0)
        self.assertTrue(tm_above._has_liquidity_for_new_trade(PROVIDER_ETORO))

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


class BatchGateTests(unittest.TestCase):
    def _ready_manager(self, cash):
        """Manager wired so only the liquidity gate can stop the GPT call:
        slots always free, payloads always non-empty, GPT returns no signals."""
        tm, broker, gpt = _manager(cash=cash, min_trade=50.0)
        tm._available_trade_slots = Mock(return_value=3)
        tm._build_batch_payloads = Mock(return_value=[{"symbol": "AAA"}])
        gpt.request_batch_trade_signals.return_value = {"signals": []}
        return tm, broker, gpt

    def test_skips_gpt_for_stock_when_cash_below_min(self):
        tm, _, gpt = self._ready_manager(cash=10.0)
        tm._evaluate_provider_category(PROVIDER_ETORO, "STOCK", ["AAA"])
        gpt.request_batch_trade_signals.assert_not_called()

    def test_skips_gpt_for_crypto_when_cash_below_min(self):
        tm, _, gpt = self._ready_manager(cash=10.0)
        tm._evaluate_provider_category(PROVIDER_ETORO, "CRYPTO", ["BTC"])
        gpt.request_batch_trade_signals.assert_not_called()

    def test_calls_gpt_when_cash_sufficient(self):
        tm, _, gpt = self._ready_manager(cash=10_000.0)
        tm._evaluate_provider_category(PROVIDER_ETORO, "STOCK", ["AAA"])
        gpt.request_batch_trade_signals.assert_called_once()

    def test_calls_gpt_when_cash_lookup_raises(self):
        tm, broker, gpt = self._ready_manager(cash=10_000.0)
        broker.get_available_cash.side_effect = Exception("api down")
        tm._evaluate_provider_category(PROVIDER_ETORO, "STOCK", ["AAA"])
        gpt.request_batch_trade_signals.assert_called_once()

    def test_categories_evaluated_independently(self):
        # STOCK slots exhausted, CRYPTO funded with free slots: STOCK must skip,
        # CRYPTO must call GPT — verified through the per-category loop.
        tm, _, gpt = self._ready_manager(cash=10_000.0)
        tm._available_trade_slots = Mock(
            side_effect=lambda category, provider=PROVIDER_ETORO: 0 if category == "STOCK" else 3
        )
        tm.evaluate_cycle({PROVIDER_ETORO: {"STOCK": ["AAA"], "CRYPTO": ["BTC"]}})
        self.assertEqual(gpt.request_batch_trade_signals.call_count, 1)
        called_category = gpt.request_batch_trade_signals.call_args.kwargs["category"]
        self.assertEqual(called_category, "CRYPTO")


class SingleSymbolGateTests(unittest.TestCase):
    def _ready_manager(self, cash):
        tm, broker, gpt = _manager(cash=cash, min_trade=50.0)
        # Clear the earlier guards so only the liquidity gate can block GPT.
        tm.get_symbol_trades = Mock(return_value=[])
        broker.get_open_position.return_value = None
        tm._available_trade_slots = Mock(return_value=3)
        return tm, broker, gpt

    def test_skips_gpt_when_cash_below_min(self):
        tm, _, gpt = self._ready_manager(cash=10.0)
        tm.maybe_open_trade("STOCK", "AAA", provider=PROVIDER_ETORO)
        gpt.request_new_signal.assert_not_called()

    def test_calls_gpt_when_cash_sufficient(self):
        tm, _, gpt = self._ready_manager(cash=10_000.0)
        tm.data_manager.get_symbol_history.return_value = [{"timestamp": "0001", "close": 10.0}]
        gpt.request_new_signal.return_value = {"action": "HOLD"}
        tm.maybe_open_trade("STOCK", "AAA", provider=PROVIDER_ETORO)
        gpt.request_new_signal.assert_called_once()


if __name__ == "__main__":
    unittest.main()
