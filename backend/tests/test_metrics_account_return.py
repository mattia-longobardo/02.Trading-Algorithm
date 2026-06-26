import logging
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

for name, attr in (("clients.alpaca_client", "AlpacaClient"), ("clients.gpt_client", "GPTClient")):
    stub = ModuleType(name)
    setattr(stub, attr, object)
    if name == "clients.gpt_client":
        stub.get_default_prompts = lambda: {}
    sys.modules.setdefault(name, stub)
dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.app_db import initialize_app_database
from core.db import initialize_databases
from core.utils import AppConfig
from services.equity_snapshots import account_return
from services.metrics_service import MetricsService


class AccountReturnHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_db = str(Path(self.tmp.name) / "app.sqlite")
        initialize_app_database(self.app_db)

    def tearDown(self):
        self.tmp.cleanup()

    def _snap(self, recorded_at, equity, currency="USD", provider="etoro"):
        conn = sqlite3.connect(self.app_db)
        conn.execute(
            "INSERT INTO account_equity_snapshots (recorded_at, equity, currency, provider) VALUES (?, ?, ?, ?)",
            (recorded_at, equity, currency, provider),
        )
        conn.commit()
        conn.close()

    def test_returns_base_latest_abs_pct(self):
        self._snap("2026-06-08T10:00:00+00:00", 150000.0)
        self._snap("2026-06-12T10:00:00+00:00", 160000.0)
        self._snap("2026-06-16T10:00:00+00:00", 168000.0)
        out = account_return(self.app_db, target_currency="USD")
        self.assertAlmostEqual(out["base"], 150000.0)
        self.assertAlmostEqual(out["latest"], 168000.0)
        self.assertAlmostEqual(out["abs"], 18000.0)
        self.assertAlmostEqual(out["pct"], 12.0)

    def test_none_when_no_snapshots(self):
        self.assertIsNone(account_return(self.app_db, target_currency="USD"))

    def test_scoped_to_window(self):
        from datetime import datetime, UTC
        self._snap("2026-06-08T10:00:00+00:00", 150000.0)
        self._snap("2026-06-12T10:00:00+00:00", 160000.0)
        self._snap("2026-06-16T10:00:00+00:00", 168000.0)
        # window [06-12, 06-16] -> base 160000, latest 168000, +5%
        out = account_return(
            self.app_db,
            target_currency="USD",
            from_dt=datetime(2026, 6, 12, tzinfo=UTC),
            to_dt=datetime(2026, 6, 16, 23, tzinfo=UTC),
        )
        self.assertAlmostEqual(out["base"], 160000.0)
        self.assertAlmostEqual(out["latest"], 168000.0)
        self.assertAlmostEqual(out["abs"], 8000.0)
        self.assertAlmostEqual(out["pct"], 5.0)

    def test_none_when_window_has_no_snapshots(self):
        from datetime import datetime, UTC
        self._snap("2026-06-08T10:00:00+00:00", 150000.0)
        out = account_return(
            self.app_db, target_currency="USD",
            from_dt=datetime(2026, 1, 1, tzinfo=UTC), to_dt=datetime(2026, 1, 2, tzinfo=UTC),
        )
        self.assertIsNone(out)


class MetricsPayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_db = str(Path(self.tmp.name) / "app.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        initialize_app_database(self.app_db)
        initialize_databases(self.market_db, self.trades_db)
        self.config = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo",
            db_app=self.app_db, db_trades=self.trades_db, db_market_data=self.market_db,
        )
        self.config.currency = "USD"
        self.config.account_currency = "USD"
        # snapshots: 150k base -> 168k latest (real account performance)
        conn = sqlite3.connect(self.app_db)
        conn.execute("INSERT INTO account_equity_snapshots (recorded_at, equity, currency, provider) VALUES (?,?,?,?)",
                     ("2026-06-08T10:00:00+00:00", 150000.0, "USD", "etoro"))
        conn.execute("INSERT INTO account_equity_snapshots (recorded_at, equity, currency, provider) VALUES (?,?,?,?)",
                     ("2026-06-16T10:00:00+00:00", 168000.0, "USD", "etoro"))
        conn.commit()
        conn.close()
        # one closed (realized 918.58) and one open (unrealized 200)
        conn = sqlite3.connect(self.trades_db)
        conn.execute(
            """INSERT INTO trades (symbol,category,status,entry_price,quantity,allocated_capital,
                 close_price,close_timestamp,pnl,account_currency,provider)
               VALUES ('BTC','CRYPTO','CLOSED',100.0,10.0,1000.0,191.858,'2026-06-10T10:00:00+00:00',918.58,'USD','etoro')""")
        conn.execute(
            """INSERT INTO trades (symbol,category,status,entry_price,quantity,allocated_capital,
                 current_price,account_currency,provider,position_confirmed)
               VALUES ('ETH','CRYPTO','OPEN',100.0,10.0,1000.0,120.0,'USD','etoro',1)""")
        conn.commit()
        conn.close()
        self.metrics = MetricsService(self.config, logging.getLogger("t"), broker_clients={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_splits_realized_and_unrealized(self):
        out = self.metrics.compute_metrics(None, None)
        self.assertAlmostEqual(out["realized_pnl_abs"], 918.58, places=2)
        self.assertAlmostEqual(out["unrealized_pnl_abs"], 200.0, places=2)

    def test_account_return_from_snapshots(self):
        out = self.metrics.compute_metrics(None, None)
        self.assertAlmostEqual(out["account_equity_base"], 150000.0, places=2)
        self.assertAlmostEqual(out["account_return_abs"], 18000.0, places=2)
        self.assertAlmostEqual(out["account_return_pct"], 12.0, places=2)

    def test_total_pnl_pct_uses_account_base_not_allocated(self):
        out = self.metrics.compute_metrics(None, None)
        # realized 918.58 / base 150000 * 100 = 0.61 (NOT 918.58/1000*100 = 91.86)
        self.assertAlmostEqual(out["total_pnl_pct"], 0.61, places=2)

    def _insert_closed(self, symbol, close_ts, pnl):
        conn = sqlite3.connect(self.trades_db)
        conn.execute(
            """INSERT INTO trades (symbol,category,status,entry_price,quantity,allocated_capital,
                 close_price,close_timestamp,pnl,account_currency,provider)
               VALUES (?,'CRYPTO','CLOSED',100.0,1.0,100.0,100.0,?,?,'USD','etoro')""",
            (symbol, close_ts, pnl),
        )
        conn.commit()
        conn.close()

    def test_avg_loss_only_counts_in_window_losses(self):
        from datetime import datetime, UTC
        # a loss closed 06-09, before the window we'll select
        self._insert_closed("OLD", "2026-06-09T10:00:00+00:00", -500.0)
        # full history: one loss (-500) -> avg_loss -500
        full = self.metrics.compute_metrics(None, None)
        self.assertAlmostEqual(full["avg_loss"], -500.0, places=2)
        # window from 06-10 excludes the 06-09 loss -> no losses
        scoped = self.metrics.compute_metrics(datetime(2026, 6, 10, tzinfo=UTC), None)
        self.assertEqual(scoped["avg_loss"], 0.0)

    def test_account_return_scoped_to_selected_window(self):
        from datetime import datetime, UTC
        conn = sqlite3.connect(self.app_db)
        conn.execute("INSERT INTO account_equity_snapshots (recorded_at, equity, currency, provider) VALUES (?,?,?,?)",
                     ("2026-06-12T10:00:00+00:00", 160000.0, "USD", "etoro"))
        conn.commit()
        conn.close()
        out = self.metrics.compute_metrics(datetime(2026, 6, 12, tzinfo=UTC), datetime(2026, 6, 16, 23, tzinfo=UTC))
        self.assertAlmostEqual(out["account_equity_base"], 160000.0, places=2)
        self.assertAlmostEqual(out["account_return_abs"], 8000.0, places=2)

    def _insert_closed_r(self, symbol, close_ts, pnl, realized_r=None, planned_rr=None):
        conn = sqlite3.connect(self.trades_db)
        conn.execute(
            """INSERT INTO trades (symbol,category,status,entry_price,quantity,allocated_capital,
                 close_price,close_timestamp,pnl,account_currency,provider,realized_r,planned_reward_risk)
               VALUES (?,'CRYPTO','CLOSED',100.0,1.0,100.0,100.0,?,?,'USD','etoro',?,?)""",
            (symbol, close_ts, pnl, realized_r, planned_rr),
        )
        conn.commit()
        conn.close()

    def test_avg_captured_r(self):
        self._insert_closed_r("X1", "2026-06-11T10:00:00+00:00", 100.0, realized_r=1.0)
        self._insert_closed_r("X2", "2026-06-12T10:00:00+00:00", 200.0, realized_r=2.0)
        m = self.metrics.compute_metrics(None, None)
        self.assertAlmostEqual(m["avg_captured_r"], 1.5, places=6)

    def test_avg_captured_r_skips_null(self):
        # trade with no realized_r should not count toward average
        self._insert_closed_r("X3", "2026-06-11T10:00:00+00:00", 100.0, realized_r=3.0)
        self._insert_closed_r("X4", "2026-06-12T10:00:00+00:00", 50.0, realized_r=None)
        m = self.metrics.compute_metrics(None, None)
        self.assertAlmostEqual(m["avg_captured_r"], 3.0, places=6)

    def test_avg_captured_r_empty(self):
        # existing setUp trade has no realized_r -> should default to 0.0
        m = self.metrics.compute_metrics(None, None)
        self.assertEqual(m["avg_captured_r"], 0.0)

    def test_avg_planned_rr(self):
        self._insert_closed_r("Y1", "2026-06-11T10:00:00+00:00", 100.0, planned_rr=2.0)
        self._insert_closed_r("Y2", "2026-06-12T10:00:00+00:00", 200.0, planned_rr=4.0)
        m = self.metrics.compute_metrics(None, None)
        self.assertAlmostEqual(m["avg_planned_rr"], 3.0, places=6)

    def test_avg_planned_rr_empty(self):
        m = self.metrics.compute_metrics(None, None)
        self.assertEqual(m["avg_planned_rr"], 0.0)


if __name__ == "__main__":
    unittest.main()
