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


def hist(position_id, *, net_profit, close_rate, instrument_id=100000, open_rate=63444.08,
         units=0.182319, close_timestamp="2026-06-15T21:46:03Z", is_buy=True, investment=11567.06):
    return {
        "position_id": str(position_id), "instrument_id": instrument_id,
        "net_profit": net_profit, "open_rate": open_rate, "close_rate": close_rate,
        "units": units, "investment": investment, "fees": 0.0, "is_buy": is_buy,
        "open_timestamp": "2026-06-08T10:00:00Z", "close_timestamp": close_timestamp,
    }


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        initialize_databases(self.market_db, self.trades_db)
        upsert_instrument_mapping(self.market_db, "BTC", 100000, "CRYPTO", "Bitcoin", True)
        self.config = make_config(self.trades_db, self.market_db)
        self.broker = Mock()
        self.data_manager = Mock()
        self.gpt = Mock()
        self.manager = TradeManager(
            self.config, logging.getLogger("t"), {PROVIDER_ETORO: self.broker}, self.data_manager, self.gpt
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _insert(self, **over):
        cols = {
            "symbol": "BTC", "category": "CRYPTO", "status": "CLOSED",
            "entry_price": 63444.08, "quantity": 0.182319, "allocated_capital": 11567.06,
            "close_price": 63558.66, "pnl": 20.89, "close_reason": "EXTERNAL_CLOSE",
            "position_id": "900", "instrument_id": 100000, "provider": "etoro",
        }
        cols.update(over)
        keys = ",".join(cols)
        marks = ",".join("?" for _ in cols)
        conn = sqlite3.connect(self.trades_db)
        conn.execute(f"INSERT INTO trades ({keys}) VALUES ({marks})", tuple(cols.values()))
        conn.commit()
        conn.close()

    def _rows(self, **where):
        conn = sqlite3.connect(self.trades_db)
        conn.row_factory = sqlite3.Row
        q = "SELECT * FROM trades"
        if where:
            q += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
        rows = [dict(r) for r in conn.execute(q, tuple(where.values()))]
        conn.close()
        return rows

    def test_corrects_tracked_closed_trade_to_etoro_values(self):
        self._insert(position_id="900", pnl=20.89, close_price=63558.66)
        self.broker.list_trade_history.return_value = [
            hist("900", net_profit=537.80, close_rate=66393.87, close_timestamp="2026-06-15T21:46:03Z")
        ]
        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["corrected"], 1)
        row = self._rows(position_id="900")[0]
        self.assertAlmostEqual(row["pnl"], 537.80, places=2)
        self.assertAlmostEqual(row["close_price"], 66393.87, places=2)
        self.assertEqual(row["close_timestamp"], "2026-06-15T21:46:03Z")

    def test_leaves_already_correct_trade_unchanged(self):
        self._insert(position_id="900", pnl=537.80, close_price=66393.87)
        self.broker.list_trade_history.return_value = [
            hist("900", net_profit=537.80, close_rate=66393.87)
        ]
        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["corrected"], 0)
        self.assertEqual(summary["unchanged"], 1)

    def test_backfills_missing_closed_position(self):
        self.broker.list_trade_history.return_value = [
            hist("800", net_profit=271.49, close_rate=587.93, instrument_id=100000)
        ]
        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["backfilled"], 1)
        rows = self._rows(position_id="800")
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["status"], "CLOSED")
        self.assertEqual(r["symbol"], "BTC")
        self.assertEqual(r["category"], "CRYPTO")
        self.assertAlmostEqual(r["pnl"], 271.49, places=2)
        self.assertAlmostEqual(r["close_price"], 587.93, places=2)
        self.assertTrue(r["close_reason"])

    def test_idempotent_no_duplicate_on_rerun(self):
        self._insert(position_id="900", pnl=20.89, close_price=63558.66)
        self.broker.list_trade_history.return_value = [
            hist("900", net_profit=537.80, close_rate=66393.87),
            hist("800", net_profit=271.49, close_rate=587.93),
        ]
        first = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        second = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(first["corrected"], 1)
        self.assertEqual(first["backfilled"], 1)
        self.assertEqual(second["corrected"], 0)
        self.assertEqual(second["backfilled"], 0)
        self.assertEqual(len(self._rows()), 2)

    def test_skips_open_trade_present_in_history(self):
        self._insert(position_id="700", status="OPEN", pnl=10.0, close_price=None, close_reason=None)
        self.broker.list_trade_history.return_value = [
            hist("700", net_profit=99.0, close_rate=70000.0)
        ]
        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["skipped_open"], 1)
        self.assertEqual(summary["corrected"], 0)
        row = self._rows(position_id="700")[0]
        self.assertEqual(row["status"], "OPEN")

    def test_unmapped_instrument_is_not_backfilled(self):
        self.broker.list_trade_history.return_value = [
            hist("801", net_profit=10.0, close_rate=5.0, instrument_id=999999)
        ]
        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["backfilled"], 0)
        self.assertEqual(self._rows(position_id="801"), [])

    def test_no_broker_history_support_returns_empty_summary(self):
        broker = Mock(spec=[])  # no list_trade_history attribute
        mgr = TradeManager(self.config, logging.getLogger("t"), {PROVIDER_ETORO: broker}, self.data_manager, self.gpt)
        summary = mgr.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["corrected"], 0)
        self.assertEqual(summary["backfilled"], 0)


if __name__ == "__main__":
    unittest.main()
