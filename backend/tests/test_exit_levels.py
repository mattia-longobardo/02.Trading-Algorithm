# backend/tests/test_exit_levels.py
import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from services.exit_levels import normalize_exit_levels


class NormalizeExitLevelsTests(unittest.TestCase):
    def test_take_profit_raised_to_min_reward_risk(self):
        # entry 100, stop 90 -> R = 10. GPT proposed TP only 105 (0.5R).
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=90.0, take_profit=105.0,
            trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        # TP must be at least entry + 1.5R = 100 + 15 = 115
        self.assertAlmostEqual(out["take_profit"], 115.0, places=6)

    def test_take_profit_kept_when_already_generous(self):
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=90.0, take_profit=130.0,
            trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        self.assertAlmostEqual(out["take_profit"], 130.0, places=6)

    def test_trailing_arms_at_arm_r_and_trails_at_trail_r(self):
        # R = 10. arm at +1.5R = +15% -> activation_pct 15. trail distance = 1.0R = 10.
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=90.0, take_profit=130.0,
            trailing_take_profit_distance=2.0, trailing_take_profit_activation_pct=3.0,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        self.assertAlmostEqual(out["trailing_take_profit_activation_pct"], 15.0, places=6)
        self.assertAlmostEqual(out["trailing_take_profit_distance"], 10.0, places=6)

    def test_trailing_invariant_holds(self):
        # activation_pct must exceed distance/entry*100 (so trigger > entry at arming)
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=80.0, take_profit=200.0,
            trailing_take_profit_distance=5.0, trailing_take_profit_activation_pct=1.0,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        distance_pct = out["trailing_take_profit_distance"] / 100.0 * 100.0
        self.assertGreater(out["trailing_take_profit_activation_pct"], distance_pct)

    def test_no_trailing_when_input_none(self):
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=90.0, take_profit=130.0,
            trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        self.assertIsNone(out["trailing_take_profit_distance"])
        self.assertIsNone(out["trailing_take_profit_activation_pct"])

    def test_invalid_long_returns_inputs_unchanged(self):
        # entry <= stop is not a valid long; do not fabricate levels.
        out = normalize_exit_levels(
            entry_price=100.0, stop_loss=100.0, take_profit=130.0,
            trailing_take_profit_distance=None, trailing_take_profit_activation_pct=None,
            min_reward_risk=1.5, arm_r=1.5, trail_r=1.0,
        )
        self.assertEqual(out["take_profit"], 130.0)


if __name__ == "__main__":
    unittest.main()
