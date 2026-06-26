# backend/tests/test_db_migration.py
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases


class RColumnsMigrationTests(unittest.TestCase):
    def test_r_columns_exist_after_init(self):
        with tempfile.TemporaryDirectory() as d:
            market = str(Path(d) / "m.sqlite")
            trades = str(Path(d) / "t.sqlite")
            initialize_databases(market, trades)
            cols = {r[1] for r in sqlite3.connect(trades).execute("PRAGMA table_info(trades)")}
            for c in ("planned_risk_per_unit", "planned_reward_risk", "realized_r",
                      "low_water_mark", "mae", "mfe"):
                self.assertIn(c, cols)


if __name__ == "__main__":
    unittest.main()
