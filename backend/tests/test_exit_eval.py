# backend/tests/test_exit_eval.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.exit_eval import (
    compute_trailing_stop_price,
    compute_trailing_take_profit_price,
    downside_close_reason,
    trailing_take_profit_close_reason,
)


class ExitEvalTests(unittest.TestCase):
    def test_trailing_stop_price(self):
        self.assertEqual(compute_trailing_stop_price(100.0, 5.0), 95.0)
        self.assertIsNone(compute_trailing_stop_price(100.0, None))

    def test_trailing_tp_price_arms_above_activation(self):
        # entry 100, activation 5% -> arms at 105; hwm 110, distance 3 -> trigger 107
        self.assertAlmostEqual(compute_trailing_take_profit_price(110.0, 100.0, 3.0, 5.0), 107.0, places=6)
        # below activation -> None
        self.assertIsNone(compute_trailing_take_profit_price(104.0, 100.0, 3.0, 5.0))

    def test_downside_reason(self):
        self.assertEqual(downside_close_reason(89.0, 90.0, None), "STOP_LOSS")
        self.assertIsNone(downside_close_reason(95.0, 90.0, None))

    def test_trailing_tp_reason(self):
        self.assertEqual(trailing_take_profit_close_reason(106.0, 107.0), "TRAILING_TAKE_PROFIT")
        self.assertIsNone(trailing_take_profit_close_reason(108.0, 107.0))


if __name__ == "__main__":
    unittest.main()
