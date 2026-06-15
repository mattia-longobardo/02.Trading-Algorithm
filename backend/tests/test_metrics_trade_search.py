import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases, upsert_instrument_mapping  # noqa: E402
from core.utils import AppConfig  # noqa: E402
from services.metrics_service import MetricsService  # noqa: E402


def _make_config(market_db: str, trades_db: str) -> AppConfig:
    return AppConfig(
        openai_api_key="k",
        db_market_data=market_db,
        db_trades=trades_db,
        etoro_api_key="a",
        etoro_user_key="b",
        etoro_account_type="demo",
    )


class TradeSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "trades.sqlite")
        initialize_databases(self.market_db, self.trades_db)
        self.metrics = MetricsService(
            _make_config(self.market_db, self.trades_db),
            logging.getLogger("test"),
        )
        self._insert_trade("AAPL", "STOCK")
        self._insert_trade("BTC/USD", "CRYPTO")
        self._insert_trade("MSFT", "STOCK")
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple Inc", True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _insert_trade(self, symbol: str, category: str) -> None:
        with sqlite3.connect(self.trades_db) as conn:
            conn.execute(
                """
                INSERT INTO trades
                    (symbol, category, status, entry_price, quantity, allocated_capital)
                VALUES (?, ?, 'OPEN', 100, 1, 100)
                """,
                (symbol, category),
            )

    def _symbols_for(self, query: str) -> list[str]:
        payload = self.metrics.list_trades(symbol=query, page_size=500)
        return [row["symbol"] for row in payload["items"]]

    def test_symbol_search_matches_partial_and_separator_insensitive_text(self) -> None:
        self.assertEqual(self._symbols_for("btc"), ["BTC/USD"])
        self.assertEqual(self._symbols_for("btcusd"), ["BTC/USD"])

    def test_symbol_search_matches_close_typos(self) -> None:
        self.assertEqual(self._symbols_for("APPL"), ["AAPL"])

    def test_symbol_search_matches_instrument_display_name(self) -> None:
        self.assertEqual(self._symbols_for("apple"), ["AAPL"])


if __name__ == "__main__":
    unittest.main()
