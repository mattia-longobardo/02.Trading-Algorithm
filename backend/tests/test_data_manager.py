import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

alpaca_client_stub = ModuleType("clients.alpaca_client")
alpaca_client_stub.AlpacaClient = object
sys.modules.setdefault("clients.alpaca_client", alpaca_client_stub)

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import get_market_symbol_table, initialize_databases
from core.utils import AppConfig
from services.data_manager import DataManager


def make_config(market_db_path: str, trades_db_path: str) -> AppConfig:
    return AppConfig(
        openai_api_key="test-openai-key",
        alpaca_api_key="test-alpaca-key",
        alpaca_secret_key="test-alpaca-secret",
        alpaca_base_url="https://paper-api.alpaca.markets",
        db_market_data=market_db_path,
        db_trades=trades_db_path,
    )


class DataManagerStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.market_db_path = str(Path(self.temp_dir.name) / "market.sqlite3")
        self.trades_db_path = str(Path(self.temp_dir.name) / "trades.sqlite3")
        self.config = make_config(self.market_db_path, self.trades_db_path)
        self.alpaca_client = Mock()
        self.manager = DataManager(self.config, logging.getLogger("test"), self.alpaca_client)

    def tearDown(self) -> None:
        try:
            self.temp_dir.cleanup()
        except PermissionError:
            pass

    def test_initialize_databases_migrates_legacy_ohlcv_into_symbol_tables(self) -> None:
        connection = sqlite3.connect(self.market_db_path)
        connection.execute(
            """
            CREATE TABLE ohlcv (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                UNIQUE(symbol, timestamp)
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO ohlcv(symbol, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("AAPL", "2026-03-18T00:00:00+00:00", 1.0, 2.0, 0.5, 1.5, 100.0),
                ("AAPL", "2026-03-19T00:00:00+00:00", 2.0, 3.0, 1.5, 2.5, 200.0),
                ("BTC/USD", "2026-03-19T00:00:00+00:00", 10.0, 11.0, 9.0, 10.5, 300.0),
            ],
        )
        connection.commit()
        connection.close()

        initialize_databases(self.market_db_path, self.trades_db_path)

        connection = sqlite3.connect(self.market_db_path)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        self.assertNotIn("ohlcv", tables)
        self.assertIn("market_symbols", tables)
        aapl_table = get_market_symbol_table(self.market_db_path, "AAPL")
        btc_table = get_market_symbol_table(self.market_db_path, "BTC/USD")
        self.assertIsNotNone(aapl_table)
        self.assertIsNotNone(btc_table)
        self.assertNotEqual(aapl_table, btc_table)
        aapl_count = connection.execute(f'SELECT COUNT(*) FROM "{aapl_table}"').fetchone()[0]
        btc_count = connection.execute(f'SELECT COUNT(*) FROM "{btc_table}"').fetchone()[0]
        connection.close()

        self.assertEqual(aapl_count, 2)
        self.assertEqual(btc_count, 1)

    def test_update_symbol_stores_rows_in_dedicated_symbol_table(self) -> None:
        initialize_databases(self.market_db_path, self.trades_db_path)
        self.alpaca_client.get_bars.return_value = [
            {
                "symbol": "AAPL",
                "timestamp": "2026-03-18T00:00:00+00:00",
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 100.0,
            },
            {
                "symbol": "AAPL",
                "timestamp": "2026-03-19T00:00:00+00:00",
                "open": 2.0,
                "high": 3.0,
                "low": 1.5,
                "close": 2.5,
                "volume": 200.0,
            },
        ]

        inserted = self.manager.update_symbol("AAPL", "STOCK")

        self.assertEqual(inserted, 2)
        self.assertEqual(self.manager.get_known_symbols(), ["AAPL"])
        history = self.manager.get_symbol_history("AAPL")
        self.assertEqual(len(history), 2)
        self.assertEqual([row["symbol"] for row in history], ["AAPL", "AAPL"])
        self.assertEqual(self.manager.get_symbol_history("AAPL", limit=1)[0]["timestamp"], "2026-03-19T00:00:00+00:00")

        connection = sqlite3.connect(self.market_db_path)
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        symbol_table = get_market_symbol_table(self.market_db_path, "AAPL")
        self.assertIsNotNone(symbol_table)
        self.assertIn(symbol_table, tables)
        self.assertNotIn("ohlcv", tables)
        count = connection.execute(f'SELECT COUNT(*) FROM "{symbol_table}"').fetchone()[0]
        connection.close()

        self.assertEqual(count, 2)
