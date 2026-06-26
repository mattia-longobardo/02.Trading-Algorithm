import sys
import unittest
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from backtest.run import aggregate


class AggregateTests(unittest.TestCase):
    def test_aggregate_basic(self):
        results = [
            {"taken": True, "exit_reason": "STOP_LOSS", "realized_r": -1.0, "reached_tp": False},
            {"taken": True, "exit_reason": "TAKE_PROFIT", "realized_r": 3.0, "reached_tp": True},
            {"taken": False, "exit_reason": None, "realized_r": None, "reached_tp": False},
        ]
        agg = aggregate(results)
        self.assertEqual(agg["n_taken"], 2)
        self.assertEqual(agg["n_closed"], 2)
        self.assertAlmostEqual(agg["avg_realized_r"], 1.0, places=6)
        self.assertAlmostEqual(agg["win_rate"], 0.5, places=6)
        self.assertAlmostEqual(agg["pct_reached_tp"], 0.5, places=6)
        self.assertAlmostEqual(agg["total_r"], 2.0, places=6)


if __name__ == "__main__":
    unittest.main()
