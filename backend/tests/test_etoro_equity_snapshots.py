import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.app_db import initialize_app_database
from core.utils import AppConfig
from services.equity_snapshots import record_snapshots_all, latest_snapshot


class EquitySnapshotProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app_db = str(Path(self.tmp.name) / "app.sqlite")
        initialize_app_database(self.app_db)
        self.config = AppConfig(
            openai_api_key="k", 
            etoro_api_key="a", etoro_user_key="b", etoro_account_type="demo", db_app=self.app_db,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_etoro_when_active(self):
        broker = Mock()
        broker.get_account_equity.return_value = 1234.0
        out = record_snapshots_all(self.config, {"etoro": broker}, logging.getLogger("t"))
        self.assertIn("etoro", out)
        snap = latest_snapshot(self.app_db, provider="etoro")
        self.assertEqual(snap["equity"], 1234.0)
        self.assertEqual(snap["currency"], "USD")


if __name__ == "__main__":
    unittest.main()
