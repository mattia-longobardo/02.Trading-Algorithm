import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db import initialize_databases


def _insert(db, **over):
    cols = {
        "symbol": "BTC", "category": "CRYPTO", "status": "CLOSED",
        "entry_price": 1.0, "quantity": 1.0, "allocated_capital": 1.0,
        "position_id": "1", "provider": "etoro",
    }
    cols.update(over)
    keys = ",".join(cols)
    marks = ",".join("?" for _ in cols)
    conn = sqlite3.connect(db)
    conn.execute(f"INSERT INTO trades ({keys}) VALUES ({marks})", tuple(cols.values()))
    conn.commit()
    conn.close()


def _position_ids(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [r["position_id"] for r in conn.execute("SELECT position_id FROM trades")]
    conn.close()
    return set(rows)


class PurgeBackfilledTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        initialize_databases(self.market_db, self.trades_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_purges_only_backfilled_rows_on_init(self):
        _insert(self.trades_db, position_id="algo", reasoning="LLM signal")
        _insert(self.trades_db, position_id="algo_ext", reasoning=None,
                close_reason="EXTERNAL_CLOSE")
        _insert(self.trades_db, position_id="bf",
                reasoning="Backfilled from eToro trade history")

        # Re-run init (idempotent migration) — should purge the backfilled row only.
        initialize_databases(self.market_db, self.trades_db)

        self.assertEqual(_position_ids(self.trades_db), {"algo", "algo_ext"})

    def test_purge_is_idempotent(self):
        _insert(self.trades_db, position_id="bf",
                reasoning="Backfilled from eToro trade history")
        initialize_databases(self.market_db, self.trades_db)
        initialize_databases(self.market_db, self.trades_db)
        self.assertEqual(_position_ids(self.trades_db), set())
