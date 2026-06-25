# backend/tests/test_regime.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.regime import passes_regime_gate


def _bars(closes):
    return [{"timestamp": f"{i:04d}", "close": c} for i, c in enumerate(closes)]


class RegimeGateTests(unittest.TestCase):
    def test_price_above_sma_passes(self):
        bars = _bars([10.0] * 50)
        self.assertTrue(passes_regime_gate(bars, sma_period=50, current_price=11.0))

    def test_price_below_sma_blocks(self):
        bars = _bars([10.0] * 50)
        self.assertFalse(passes_regime_gate(bars, sma_period=50, current_price=9.0))

    def test_uses_last_close_when_no_current_price(self):
        bars = _bars([10.0] * 49 + [8.0])
        # mean of 49*10 + 8 = 9.96; last close 8 < sma -> blocks
        self.assertFalse(passes_regime_gate(bars, sma_period=50))

    def test_insufficient_history_fails_open(self):
        bars = _bars([10.0] * 5)
        self.assertTrue(passes_regime_gate(bars, sma_period=200, current_price=1.0))
