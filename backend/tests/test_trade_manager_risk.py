import logging
import sys
import unittest
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig, PROVIDER_ETORO


def _bars(closes):
    return [{"timestamp": f"{i:04d}", "close": c} for i, c in enumerate(closes)]


def _manager(history=None, open_trades=None, equity=10_000.0, cash=10_000.0):
    from services.trade_manager import TradeManager
    cfg = AppConfig(openai_api_key="k", etoro_api_key="a", etoro_user_key="b",
                    max_open_trades_stock=3, max_open_trades_crypto=3, etoro_min_trade_amount=50.0)
    broker = Mock()
    broker.get_account_equity.return_value = equity
    broker.get_available_cash.return_value = cash
    data_manager = Mock()
    history = history or {}
    data_manager.get_symbol_history.side_effect = lambda s, l=None: history.get(str(s).upper(), [])
    gpt = Mock()
    tm = TradeManager(cfg, logging.getLogger("t"), {PROVIDER_ETORO: broker}, data_manager, gpt)
    tm.get_open_or_pending_trades = Mock(return_value=open_trades or [])
    return tm, broker


class RiskAllocationTests(unittest.TestCase):
    def test_risk_based_allocation_returns_positive(self):
        tm, _ = _manager(history={"CALM": _bars([10, 10.05, 9.97, 10.03, 10.0, 10.04, 10.01])})
        alloc = tm._risk_based_allocation("STOCK", "CALM", provider=PROVIDER_ETORO)
        self.assertGreater(alloc, 0.0)

    def test_falls_back_to_equal_slot_without_equity(self):
        tm, broker = _manager(equity=0.0)
        alloc = tm._risk_based_allocation("STOCK", "AAA", provider=PROVIDER_ETORO)
        self.assertAlmostEqual(alloc, round(10_000.0 / 6, 2), places=2)

    def test_entry_gate_skips_when_over_hard_threshold(self):
        tm, _ = _manager(history={"WILD": _bars([10, 13, 8, 14, 7, 15, 6])})
        tm.config.risk_hard_threshold = 1.0  # everything is "over hard"
        alloc = tm._risk_based_allocation("STOCK", "WILD", provider=PROVIDER_ETORO)
        self.assertEqual(alloc, 0.0)

    def test_falls_back_when_equity_fetch_raises(self):
        tm, broker = _manager()
        broker.get_account_equity.side_effect = Exception("api down")
        alloc = tm._risk_based_allocation("STOCK", "AAA", provider=PROVIDER_ETORO)
        self.assertAlmostEqual(alloc, round(10_000.0 / 6, 2), places=2)

    def test_falls_back_when_cash_fetch_raises(self):
        tm, broker = _manager()
        broker.get_available_cash.side_effect = [Exception("api down"), 10_000.0, 10_000.0, 10_000.0]
        alloc = tm._risk_based_allocation("STOCK", "AAA", provider=PROVIDER_ETORO)
        self.assertAlmostEqual(alloc, round(10_000.0 / 6, 2), places=2)


class RiskContextTests(unittest.TestCase):
    def test_build_risk_context_shape(self):
        tm, _ = _manager(history={"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3])},
                         open_trades=[{"symbol": "AAA", "category": "STOCK", "status": "OPEN",
                                       "quantity": 10, "current_price": 100.0,
                                       "allocated_capital": 1000.0, "provider": "etoro"}])
        ctx = tm._risk_context(provider=PROVIDER_ETORO)
        self.assertEqual(
            set(ctx.keys()),
            {"score", "portfolio_vol", "budget_vol", "avg_correlation", "n_eff",
             "exposure", "remaining_budget", "alert_threshold", "hard_threshold"},
        )

    def test_risk_context_none_without_equity(self):
        tm, _ = _manager(equity=0.0)
        self.assertIsNone(tm._risk_context(provider=PROVIDER_ETORO))


class RiskSnapshotTests(unittest.TestCase):
    def test_snapshot_dict_shape(self):
        tm, _ = _manager(history={"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3])},
                         open_trades=[{"symbol": "AAA", "category": "STOCK", "status": "OPEN",
                                       "quantity": 10, "current_price": 100.0,
                                       "allocated_capital": 1000.0, "provider": "etoro"}])
        snap = tm.portfolio_risk_snapshot(provider=PROVIDER_ETORO)
        self.assertIn("score", snap)
        self.assertIn("components", snap)
        self.assertIn("per_position_risk_contribution", snap)
        self.assertIn("equity", snap)
        self.assertIn("positions", snap)
        self.assertEqual(snap["positions"], 1)

    def test_snapshot_low_confidence_without_equity(self):
        tm, _ = _manager(equity=0.0)
        snap = tm.portfolio_risk_snapshot(provider=PROVIDER_ETORO)
        self.assertTrue(snap["low_confidence"])


if __name__ == "__main__":
    unittest.main()
