# backend/tests/test_backtest_simulator.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from backtest.simulator import simulate_trade

EXIT_CFG = {"min_reward_risk": 1.5, "arm_r": 1.5, "trail_r": 1.0, "min_profit_buffer_pct": 0.5}
REGIME_OFF = {"enabled": False, "sma_period": 200}


def _bar(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": 1.0}


def _trade(**kw):
    base = dict(entry_price=100.0, stop_loss=90.0, take_profit=130.0,
                trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
                trailing_stop_distance=None)
    base.update(kw)
    return base


class SimulateTradeTests(unittest.TestCase):
    def test_stop_hit_realizes_minus_one_r(self):
        fwd = [_bar("d1", 100, 101, 88, 95)]  # low 88 < stop 90
        out = simulate_trade(_trade(), [], fwd, mode="old", exit_cfg=EXIT_CFG, regime_cfg=REGIME_OFF)
        self.assertTrue(out["taken"])
        self.assertEqual(out["exit_reason"], "STOP_LOSS")
        self.assertAlmostEqual(out["close_price"], 90.0, places=6)
        self.assertAlmostEqual(out["realized_r"], -1.0, places=6)

    def test_tp_hit_realizes_positive(self):
        fwd = [_bar("d1", 100, 131, 99, 130)]  # high 131 > tp 130
        out = simulate_trade(_trade(), [], fwd, mode="old", exit_cfg=EXIT_CFG, regime_cfg=REGIME_OFF)
        self.assertEqual(out["exit_reason"], "TAKE_PROFIT")
        self.assertTrue(out["reached_tp"])
        self.assertAlmostEqual(out["realized_r"], 3.0, places=6)  # (130-100)/10

    def test_intraday_ambiguity_picks_adverse(self):
        fwd = [_bar("d1", 100, 131, 88, 100)]  # both tp(130) and stop(90) inside [88,131]
        out = simulate_trade(_trade(), [], fwd, mode="old", exit_cfg=EXIT_CFG, regime_cfg=REGIME_OFF)
        self.assertEqual(out["exit_reason"], "STOP_LOSS")  # adverse first

    def test_regime_gate_excludes_below_sma(self):
        # entry_bars: 200 closes all at 200, entry price 100 below SMA -> not taken
        entry_bars = [_bar(f"e{i}", 200, 200, 200, 200) for i in range(200)]
        fwd = [_bar("d1", 100, 101, 99, 100)]
        out = simulate_trade(_trade(), entry_bars, fwd, mode="new",
                             exit_cfg=EXIT_CFG, regime_cfg={"enabled": True, "sma_period": 200})
        self.assertFalse(out["taken"])

    def test_open_at_end_marks_unclosed(self):
        fwd = [_bar("d1", 100, 105, 99, 104)]  # never hits stop or tp
        out = simulate_trade(_trade(), [], fwd, mode="old", exit_cfg=EXIT_CFG, regime_cfg=REGIME_OFF)
        self.assertIsNone(out["exit_reason"])  # still open at data end


if __name__ == "__main__":
    unittest.main()
