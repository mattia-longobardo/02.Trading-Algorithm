import tempfile
import unittest
from pathlib import Path

from core.db import (
    initialize_databases,
    upsert_instrument_mapping,
    get_instrument_mapping,
)


class InstrumentMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "trades.sqlite")
        initialize_databases(self.market_db, self.trades_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_then_get(self):
        upsert_instrument_mapping(
            self.market_db, "AAPL", 101, "STOCK", "Apple Inc", True
        )
        row = get_instrument_mapping(self.market_db, "aapl")
        self.assertIsNotNone(row)
        self.assertEqual(row["instrument_id"], 101)
        self.assertEqual(row["category"], "STOCK")
        self.assertEqual(row["symbol"], "AAPL")

    def test_upsert_is_idempotent_and_updates(self):
        upsert_instrument_mapping(self.market_db, "BTC", 100000, "CRYPTO", "Bitcoin", True)
        upsert_instrument_mapping(self.market_db, "BTC", 100000, "CRYPTO", "Bitcoin", False)
        row = get_instrument_mapping(self.market_db, "BTC")
        self.assertEqual(row["tradable"], 0)

    def test_get_missing_returns_none(self):
        self.assertIsNone(get_instrument_mapping(self.market_db, "NOPE"))


if __name__ == "__main__":
    unittest.main()
