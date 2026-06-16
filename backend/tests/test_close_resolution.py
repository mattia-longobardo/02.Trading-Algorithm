import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

for name, attr in (("clients.alpaca_client", "AlpacaClient"), ("clients.gpt_client", "GPTClient")):
    stub = ModuleType(name)
    setattr(stub, attr, object)
    if name == "clients.gpt_client":
        stub.get_default_prompts = lambda: {}
    sys.modules.setdefault(name, stub)
dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases, upsert_instrument_mapping
from core.utils import AppConfig, PROVIDER_ETORO
from services.trade_manager import TradeManager


def make_config(trades_db, market_db):
    return AppConfig(
        openai_api_key="k",
        etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo",
        db_trades=trades_db, db_market_data=market_db,
    )


class CloseResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        initialize_databases(self.market_db, self.trades_db)
        upsert_instrument_mapping(self.market_db, "BTC", 100000, "CRYPTO", "Bitcoin", True)
        self.config = make_config(self.trades_db, self.market_db)
        self.broker = Mock()
        self.broker.get_open_position.return_value = None  # position vanished -> external close
        self.manager = TradeManager(
            self.config, logging.getLogger("t"), {PROVIDER_ETORO: self.broker}, Mock(), Mock()
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _insert_open(self, position_id="900", entry=100.0, qty=10.0, current=105.0):
        conn = sqlite3.connect(self.trades_db)
        conn.execute(
            """INSERT INTO trades (symbol, category, status, entry_price, quantity, allocated_capital,
                 current_price, position_id, instrument_id, provider, position_confirmed)
               VALUES ('BTC','CRYPTO','OPEN', ?, ?, ?, ?, ?, 100000, 'etoro', 1)""",
            (entry, qty, entry * qty, current, position_id),
        )
        conn.commit()
        conn.close()
        conn = sqlite3.connect(self.trades_db)
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM trades WHERE position_id = ?", (position_id,)).fetchone())
        conn.close()
        return row

    def _row(self, position_id="900"):
        conn = sqlite3.connect(self.trades_db)
        conn.row_factory = sqlite3.Row
        row = dict(conn.execute("SELECT * FROM trades WHERE position_id = ?", (position_id,)).fetchone())
        conn.close()
        return row

    def test_external_close_uses_real_fill_from_history(self):
        trade = self._insert_open(current=105.0)  # estimate would be close=105, pnl=50
        self.broker.list_trade_history.return_value = [
            {"position_id": "900", "instrument_id": 100000, "close_rate": 120.0,
             "net_profit": 200.0, "close_timestamp": "2026-06-15T21:46:03Z"}
        ]
        self.manager.sync_open_trade(trade)
        row = self._row()
        self.assertEqual(row["status"], "CLOSED")
        self.assertAlmostEqual(row["close_price"], 120.0)
        self.assertAlmostEqual(row["pnl"], 200.0)
        self.assertEqual(row["close_timestamp"], "2026-06-15T21:46:03Z")

    def test_falls_back_to_estimate_when_position_not_in_history(self):
        trade = self._insert_open(current=105.0)
        self.broker.list_trade_history.return_value = []
        self.manager.sync_open_trade(trade)
        row = self._row()
        self.assertEqual(row["status"], "CLOSED")
        self.assertAlmostEqual(row["close_price"], 105.0)
        self.assertAlmostEqual(row["pnl"], 50.0)  # (105-100)*10

    def test_falls_back_when_history_call_fails(self):
        trade = self._insert_open(current=105.0)
        self.broker.list_trade_history.side_effect = RuntimeError("boom")
        self.manager.sync_open_trade(trade)
        row = self._row()
        self.assertEqual(row["status"], "CLOSED")
        self.assertAlmostEqual(row["close_price"], 105.0)
        self.assertAlmostEqual(row["pnl"], 50.0)

    def test_falls_back_when_broker_lacks_history_support(self):
        broker = Mock(spec=["get_open_position"])
        broker.get_open_position.return_value = None
        mgr = TradeManager(self.config, logging.getLogger("t"), {PROVIDER_ETORO: broker}, Mock(), Mock())
        trade = self._insert_open(current=105.0)
        mgr.sync_open_trade(trade)
        row = self._row()
        self.assertEqual(row["status"], "CLOSED")
        self.assertAlmostEqual(row["close_price"], 105.0)
        self.assertAlmostEqual(row["pnl"], 50.0)


if __name__ == "__main__":
    unittest.main()
