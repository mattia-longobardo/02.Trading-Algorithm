import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from backtest.prices import load_daily_bars


def _make_market_db(path, symbol, table, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE market_symbols (symbol TEXT, table_name TEXT, created_at TEXT)")
    conn.execute("INSERT INTO market_symbols (symbol, table_name) VALUES (?, ?)", (symbol, table))
    conn.execute(f"CREATE TABLE {table} (timestamp TEXT PRIMARY KEY, open REAL, high REAL, low REAL, close REAL, volume REAL)")
    conn.executemany(f"INSERT INTO {table} VALUES (?,?,?,?,?,?)", rows)
    conn.commit()


class LoadDailyBarsTests(unittest.TestCase):
    def test_loads_ascending(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "m.sqlite")
            _make_market_db(p, "AAA", "ohlcv_AAA", [
                ("2026-01-02", 10, 11, 9, 10.5, 100),
                ("2026-01-01", 10, 10.5, 9.5, 10, 100),
            ])
            bars = load_daily_bars(p, "AAA")
            self.assertEqual([b["timestamp"] for b in bars], ["2026-01-01", "2026-01-02"])
            self.assertEqual(bars[1]["high"], 11.0)

    def test_unknown_symbol_empty(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "m.sqlite")
            _make_market_db(p, "AAA", "ohlcv_AAA", [("2026-01-01", 10, 10, 10, 10, 1)])
            self.assertEqual(load_daily_bars(p, "ZZZ"), [])


if __name__ == "__main__":
    unittest.main()
