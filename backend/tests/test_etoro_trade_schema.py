import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db import initialize_databases


class TradeSchemaTests(unittest.TestCase):
    def test_etoro_columns_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            market = str(Path(tmp) / "m.sqlite")
            trades = str(Path(tmp) / "t.sqlite")
            initialize_databases(market, trades)
            conn = sqlite3.connect(trades)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(trades)")}
            conn.close()
            self.assertIn("instrument_id", cols)
            self.assertIn("position_id", cols)
            self.assertIn("order_reference_id", cols)
            for legacy in ("alpaca_order_id", "client_order_id", "exit_client_order_id",
                           "broker_protection_type", "protection_order_id", "protection_client_order_id"):
                self.assertNotIn(legacy, cols)
            conn = sqlite3.connect(trades)
            conn.execute("INSERT INTO trades (symbol, category, status, entry_price, quantity, allocated_capital) "
                         "VALUES ('AAPL','STOCK','PENDING',1,1,1)")
            provider = conn.execute("SELECT provider FROM trades").fetchone()[0]
            conn.close()
            self.assertEqual(provider, "etoro")


if __name__ == "__main__":
    unittest.main()
