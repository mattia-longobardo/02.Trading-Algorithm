# backend/tests/test_order_exec.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.order_exec import is_marketable


class IsMarketableTests(unittest.TestCase):
    def test_fills_within_band(self):
        # target 100, 40 bps band -> ceiling 100.40; ask 100.3 fills
        self.assertTrue(is_marketable(100.3, 100.0, 40))

    def test_at_target_fills(self):
        self.assertTrue(is_marketable(100.0, 100.0, 40))

    def test_above_band_waits(self):
        # ask 100.5 > ceiling 100.40 -> not marketable
        self.assertFalse(is_marketable(100.5, 100.0, 40))

    def test_wider_band_fills_more(self):
        self.assertFalse(is_marketable(100.5, 100.0, 40))
        self.assertTrue(is_marketable(100.5, 100.0, 80))  # ceiling 100.80

    def test_invalid_inputs_not_marketable(self):
        self.assertFalse(is_marketable(0.0, 100.0, 40))
        self.assertFalse(is_marketable(100.0, 0.0, 40))


if __name__ == "__main__":
    unittest.main()
