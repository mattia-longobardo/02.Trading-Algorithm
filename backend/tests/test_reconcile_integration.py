"""Phase 5: end-to-end check that reconciliation makes the dashboard metrics
reflect the broker's authoritative realized PnL."""

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

from core.app_db import initialize_app_database
from core.db import initialize_databases, upsert_instrument_mapping
from core.utils import AppConfig, PROVIDER_ETORO
from services.metrics_service import MetricsService
from services.trade_manager import TradeManager


class ReconcileToMetricsIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_db = str(Path(self.tmp.name) / "app.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        initialize_app_database(self.app_db)
        initialize_databases(self.market_db, self.trades_db)
        upsert_instrument_mapping(self.market_db, "BTC", 100000, "CRYPTO", "Bitcoin", True)
        self.config = AppConfig(
            openai_api_key="k", etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo",
            db_app=self.app_db, db_trades=self.trades_db, db_market_data=self.market_db,
        )
        self.config.currency = "USD"
        self.config.account_currency = "USD"
        # one locally-tracked closed trade with an ESTIMATED (wrong) PnL
        conn = sqlite3.connect(self.trades_db)
        conn.execute(
            """INSERT INTO trades (symbol,category,status,entry_price,quantity,allocated_capital,
                 close_price,close_timestamp,pnl,close_reason,position_id,instrument_id,account_currency,provider)
               VALUES ('BTC','CRYPTO','CLOSED',63444.08,0.182319,11567.06,63558.66,
                       '2026-06-08T23:16:00+00:00',20.89,'EXTERNAL_CLOSE','900',100000,'USD','etoro')""")
        conn.commit()
        conn.close()
        # broker history: real fill for #900 (+537.80) plus an UNTRACKED close #800 (+271.49)
        self.broker = Mock()
        self.broker.list_trade_history.return_value = [
            {"position_id": "900", "instrument_id": 100000, "net_profit": 537.80, "close_rate": 66393.87,
             "open_rate": 63444.08, "units": 0.182319, "investment": 11567.06,
             "open_timestamp": "2026-06-08T10:00:00Z", "close_timestamp": "2026-06-15T21:46:03Z", "is_buy": True},
            {"position_id": "800", "instrument_id": 100000, "net_profit": 271.49, "close_rate": 587.93,
             "open_rate": 574.76, "units": 20.614065, "investment": 11848.14,
             "open_timestamp": "2026-06-07T10:00:00Z", "close_timestamp": "2026-06-07T13:43:26Z", "is_buy": True},
        ]
        self.manager = TradeManager(
            self.config, logging.getLogger("t"), {PROVIDER_ETORO: self.broker}, Mock(), Mock()
        )
        self.metrics = MetricsService(self.config, logging.getLogger("t"), broker_clients={})

    def tearDown(self):
        self.tmp.cleanup()

    def test_metrics_realized_matches_broker_after_reconcile(self):
        before = self.metrics.compute_metrics(None, None)
        self.assertAlmostEqual(before["realized_pnl_abs"], 20.89, places=2)
        self.assertEqual(before["n_trades"], 1)

        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["corrected"], 1)
        self.assertEqual(summary["backfilled"], 1)

        after = self.metrics.compute_metrics(None, None)
        # realized now equals the broker's authoritative total: 537.80 + 271.49
        self.assertAlmostEqual(after["realized_pnl_abs"], 809.29, places=2)
        self.assertEqual(after["n_trades"], 2)


if __name__ == "__main__":
    unittest.main()
