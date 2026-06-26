# backend/tests/test_trade_analytics.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.trade_analytics import planned_metrics, realized_r


class TradeAnalyticsTests(unittest.TestCase):
    def test_planned_metrics(self):
        m = planned_metrics(entry_price=100.0, stop_loss=90.0, take_profit=130.0)
        self.assertAlmostEqual(m["risk_per_unit"], 10.0, places=6)
        self.assertAlmostEqual(m["reward_risk"], 3.0, places=6)

    def test_planned_metrics_no_tp(self):
        m = planned_metrics(entry_price=100.0, stop_loss=90.0, take_profit=None)
        self.assertIsNone(m["reward_risk"])

    def test_planned_metrics_invalid_long(self):
        m = planned_metrics(entry_price=100.0, stop_loss=100.0, take_profit=130.0)
        self.assertIsNone(m["reward_risk"])
        self.assertEqual(m["risk_per_unit"], 0.0)

    def test_realized_r(self):
        self.assertAlmostEqual(realized_r(100.0, 90.0, 115.0), 1.5, places=6)
        self.assertAlmostEqual(realized_r(100.0, 90.0, 90.0), -1.0, places=6)
        self.assertIsNone(realized_r(100.0, 100.0, 120.0))


class ExcursionRTests(unittest.TestCase):
    def test_favorable_excursion_positive_r(self):
        from services.trade_analytics import excursion_r
        # entry 100, stop 90 -> R=10. high water 115 -> +1.5R
        self.assertAlmostEqual(excursion_r(100.0, 90.0, 115.0), 1.5, places=6)

    def test_adverse_excursion_negative_r(self):
        from services.trade_analytics import excursion_r
        # low water 95 -> -0.5R
        self.assertAlmostEqual(excursion_r(100.0, 90.0, 95.0), -0.5, places=6)

    def test_invalid_long_none(self):
        from services.trade_analytics import excursion_r
        self.assertIsNone(excursion_r(100.0, 100.0, 110.0))
