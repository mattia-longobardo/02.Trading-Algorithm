import json
import logging
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

apscheduler_module = ModuleType("apscheduler")
apscheduler_schedulers = ModuleType("apscheduler.schedulers")
apscheduler_blocking = ModuleType("apscheduler.schedulers.blocking")
apscheduler_triggers = ModuleType("apscheduler.triggers")
apscheduler_cron = ModuleType("apscheduler.triggers.cron")


class BlockingScheduler:
    def __init__(self, timezone: str | None = None) -> None:
        self.timezone = timezone
        self.running = False
        self.jobs = []

    def add_job(self, func, trigger, id: str, replace_existing: bool = False, **kwargs) -> None:
        self.jobs.append((func, trigger, id, replace_existing, kwargs))

    def start(self) -> None:
        self.running = True

    def shutdown(self, wait: bool = True) -> None:
        self.running = False


class CronTrigger:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


apscheduler_blocking.BlockingScheduler = BlockingScheduler
apscheduler_cron.CronTrigger = CronTrigger
sys.modules.setdefault("apscheduler", apscheduler_module)
sys.modules.setdefault("apscheduler.schedulers", apscheduler_schedulers)
sys.modules.setdefault("apscheduler.schedulers.blocking", apscheduler_blocking)
sys.modules.setdefault("apscheduler.triggers", apscheduler_triggers)
sys.modules.setdefault("apscheduler.triggers.cron", apscheduler_cron)

filelock_module = ModuleType("filelock")


class Timeout(Exception):
    pass


class FileLock:
    def __init__(self, _path: str, timeout: int = 1) -> None:
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


filelock_module.FileLock = FileLock
filelock_module.Timeout = Timeout
sys.modules.setdefault("filelock", filelock_module)

alpaca_client_stub = ModuleType("clients.alpaca_client")
alpaca_client_stub.AlpacaClient = object
sys.modules.setdefault("clients.alpaca_client", alpaca_client_stub)

gpt_client_stub = ModuleType("clients.gpt_client")
gpt_client_stub.GPTClient = object
gpt_client_stub.get_default_prompts = lambda: {}
sys.modules.setdefault("clients.gpt_client", gpt_client_stub)

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

reportlab_module = ModuleType("reportlab")
reportlab_lib = ModuleType("reportlab.lib")
reportlab_colors = ModuleType("reportlab.lib.colors")
reportlab_colors.HexColor = lambda value: value
reportlab_colors.white = "white"
reportlab_enums = ModuleType("reportlab.lib.enums")
reportlab_enums.TA_LEFT = 0
reportlab_enums.TA_RIGHT = 2
reportlab_pagesizes = ModuleType("reportlab.lib.pagesizes")
reportlab_pagesizes.A4 = (595, 842)
reportlab_styles = ModuleType("reportlab.lib.styles")
reportlab_styles.ParagraphStyle = lambda *args, **kwargs: object()
reportlab_styles.getSampleStyleSheet = lambda: {"Title": object(), "Normal": object(), "Heading2": object(), "BodyText": object()}
reportlab_units = ModuleType("reportlab.lib.units")
reportlab_units.mm = 1
reportlab_platypus = ModuleType("reportlab.platypus")
reportlab_platypus.Paragraph = lambda *args, **kwargs: object()
reportlab_platypus.SimpleDocTemplate = object
reportlab_platypus.Spacer = lambda *args, **kwargs: object()
reportlab_platypus.Table = lambda *args, **kwargs: object()
reportlab_platypus.TableStyle = lambda *args, **kwargs: object()
sys.modules.setdefault("reportlab", reportlab_module)
sys.modules.setdefault("reportlab.lib", reportlab_lib)
sys.modules.setdefault("reportlab.lib.colors", reportlab_colors)
sys.modules.setdefault("reportlab.lib.enums", reportlab_enums)
sys.modules.setdefault("reportlab.lib.pagesizes", reportlab_pagesizes)
sys.modules.setdefault("reportlab.lib.styles", reportlab_styles)
sys.modules.setdefault("reportlab.lib.units", reportlab_units)
sys.modules.setdefault("reportlab.platypus", reportlab_platypus)

from api.api_server import create_api_server
from core.utils import AppConfig
from services.scheduler import TradingScheduler


def make_config() -> AppConfig:
    return AppConfig(
        openai_api_key="test-openai-key",
        
        
        
        lock_file="/tmp/test-trading.lock",
    )


class TradingSchedulerManualApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trade_manager = Mock()
        self.trade_manager.data_manager = Mock()
        self.universe_manager = Mock()
        self.report_generator = Mock()
        self.scheduler = TradingScheduler(
            config=make_config(),
            logger=logging.getLogger("test"),
            trade_manager=self.trade_manager,
            universe_manager=self.universe_manager,
            report_generator=self.report_generator,
        )

    def test_run_manual_generate_new_orders_returns_only_new_trades(self) -> None:
        self.universe_manager.get_current_universe.return_value = {"STOCK": [], "CRYPTO": []}
        self.universe_manager.select_trading_universe.return_value = {"STOCK": ["AAPL"], "CRYPTO": []}
        self.trade_manager.symbols_to_monitor.return_value = {"AAPL": "STOCK"}
        self.trade_manager.get_open_or_pending_trades.side_effect = [
            [{"id": 10, "symbol": "MSFT", "status": "OPEN"}],
            [
                {"id": 10, "symbol": "MSFT", "status": "OPEN"},
                {"id": 11, "symbol": "AAPL", "status": "PENDING"},
            ],
        ]

        payload = self.scheduler.run_manual_generate_new_orders()

        self.trade_manager.sync_broker_state.assert_called_once()
        self.universe_manager.select_trading_universe.assert_called_once()
        self.trade_manager.data_manager.update_symbols.assert_called_once_with({"AAPL": "STOCK"})
        self.trade_manager.evaluate_cycle.assert_called_once_with({"STOCK": ["AAPL"], "CRYPTO": []})
        self.assertEqual(payload["new_orders_count"], 1)
        self.assertEqual(payload["active_trades_count"], 2)
        self.assertEqual(payload["new_orders"], [{"id": 11, "symbol": "AAPL", "status": "PENDING"}])

    def test_job_review_stale_pending_orders_delegates_to_trade_manager(self) -> None:
        self.scheduler.job_review_stale_pending_orders()

        self.trade_manager.review_stale_pending_trades.assert_called_once_with(min_age_days=7)

    def test_job_evaluate_signals_refreshes_open_trade_protections_before_new_entries(self) -> None:
        self.universe_manager.get_current_universe.return_value = {"STOCK": ["AAPL"], "CRYPTO": []}
        self.trade_manager.symbols_to_monitor.return_value = {"AAPL": "STOCK"}

        self.scheduler.job_evaluate_signals()

        self.trade_manager.sync_broker_state.assert_called_once()
        self.trade_manager.data_manager.update_symbols.assert_called_once_with({"AAPL": "STOCK"})
        self.trade_manager.refresh_open_trade_protections.assert_called_once()
        self.trade_manager.evaluate_cycle.assert_called_once_with({"STOCK": ["AAPL"], "CRYPTO": []})

    def test_guarded_job_is_deferred_once_when_execution_is_busy(self) -> None:
        deferred_job = Mock()
        wrapped = self.scheduler.guarded("monitor_trades", deferred_job)

        self.scheduler._execution_lock.acquire()
        try:
            wrapped()
            wrapped()
        finally:
            self.scheduler._execution_lock.release()

        deferred_job.assert_not_called()
        self.assertEqual(list(self.scheduler._pending_jobs.keys()), ["monitor_trades"])

        self.scheduler._drain_pending_jobs()

        deferred_job.assert_called_once()
        self.assertEqual(list(self.scheduler._pending_jobs.keys()), [])

    def test_register_jobs_allows_a_second_monitor_trades_instance_for_coalescing(self) -> None:
        self.scheduler.register_jobs()

        jobs_by_id = {job_id: kwargs for _, _, job_id, _, kwargs in self.scheduler.scheduler.jobs}

        self.assertIn("monitor_trades", jobs_by_id)
        self.assertEqual(jobs_by_id["monitor_trades"]["max_instances"], 2)


try:
    from fastapi.testclient import TestClient

    _FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only without fastapi installed
    _FASTAPI_AVAILABLE = False


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed in this test env")
class TradingApiServerTests(unittest.TestCase):
    """Smoke tests for the FastAPI server through `fastapi.testclient`.

    The legacy stdlib `urllib`-based tests no longer apply since the API
    moved to FastAPI + uvicorn. We bring up an in-process app, bootstrap
    the application database with a temporary admin, log in, then exercise
    a representative slice of the new contract.
    """

    @classmethod
    def setUpClass(cls) -> None:  # noqa: D401
        from api.api_server import create_app
        from clients.gpt_client import get_default_prompts
        from core import app_db
        from services.scheduler import TradingScheduler

        cls._tempdir = tempfile.TemporaryDirectory()
        base = Path(cls._tempdir.name)
        cls._log_file = base / "trading.log"
        cls._log_file.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        cls._app_db_path = str(base / "app.sqlite")
        cls._reports_dir = base / "reports"
        cls._reports_dir.mkdir(exist_ok=True)

        config = make_config()
        config.db_app = cls._app_db_path
        config.log_file = str(cls._log_file)
        config.report_dir = str(cls._reports_dir)
        config.admin_username = "tester"
        config.admin_password = "test-pw-123"

        # Mocked scheduler with the manual-job stubs the legacy tests covered.
        scheduler = Mock(spec=TradingScheduler)
        scheduler.config = config
        scheduler.trade_manager = Mock()
        scheduler.trade_manager.brokers = {}
        scheduler.run_manual_refresh_universe.return_value = {"STOCK": ["AAPL"], "CRYPTO": []}
        scheduler.run_manual_generate_new_orders.return_value = {"new_orders": [], "new_orders_count": 0}
        scheduler.run_manual_weekly_report.return_value = {"pnl_total": 42.0}

        # Initialize the app DB and seed admin/prompts so login works.
        app_db.initialize_app_database(config.db_app)
        app_db.seed_admin_user_if_missing(
            config.db_app, config.admin_username, config.admin_password, config.admin_username
        )
        app_db.seed_initial_prompt_versions(config.db_app, get_default_prompts())

        cls._scheduler = scheduler
        cls._config = config
        cls._app = create_app(scheduler, logging.getLogger("test"))
        cls._client = TestClient(cls._app)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls._client.close()
        finally:
            cls._tempdir.cleanup()

    def setUp(self) -> None:
        self._scheduler.run_manual_refresh_universe.reset_mock()
        self._scheduler.run_manual_generate_new_orders.reset_mock()
        self._scheduler.run_manual_weekly_report.reset_mock()
        self._client.cookies.clear()

    def _login_admin(self) -> None:
        response = self._client.post(
            "/api/auth/login",
            json={"username": self._config.admin_username, "password": self._config.admin_password},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_health_endpoint_is_public(self) -> None:
        response = self._client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "trading-backend"})

    def test_authenticated_endpoint_requires_login(self) -> None:
        response = self._client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_login_then_me_returns_admin_user(self) -> None:
        self._login_admin()
        response = self._client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user"]["username"], self._config.admin_username)
        self.assertEqual(body["user"]["role"], "admin")

    def test_manual_universe_endpoint_runs_after_login(self) -> None:
        self._login_admin()
        response = self._client.get("/api/universe/generate")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["action"], "universe")
        self._scheduler.run_manual_refresh_universe.assert_called_once()

    def test_logs_endpoint_returns_log_tail(self) -> None:
        self._login_admin()
        response = self._client.get("/api/logs?lines=2")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["line_count"], 2)
        self.assertEqual(body["log_file"], str(self._log_file))
        self.assertEqual(body["logs"], "line 2\nline 3\n")


if __name__ == "__main__":
    unittest.main()
