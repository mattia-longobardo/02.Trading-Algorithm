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

    def test_job_reconcile_closed_trades_delegates_to_trade_manager(self) -> None:
        self.scheduler.job_reconcile_closed_trades()

        self.trade_manager.reconcile_closed_trades.assert_called_once_with()

    def test_register_jobs_includes_closed_trade_reconciliation(self) -> None:
        self.scheduler.register_jobs()

        job_ids = {job_id for _, _, job_id, _, _ in self.scheduler.scheduler.jobs}

        self.assertIn("reconcile_closed_trades", job_ids)

    def test_run_manual_reconcile_reconciles_each_provider(self) -> None:
        self.trade_manager.brokers = {"etoro": Mock()}
        self.trade_manager.reconcile_closed_trades.return_value = {"corrected": 2, "backfilled": 3}

        result = self.scheduler.run_manual_reconcile_closed_trades()

        self.trade_manager.reconcile_closed_trades.assert_called_once()
        _, kwargs = self.trade_manager.reconcile_closed_trades.call_args
        self.assertEqual(kwargs["provider"], "etoro")
        self.assertIn("min_date", kwargs)
        self.assertEqual(result["reconciled"]["etoro"], {"corrected": 2, "backfilled": 3})


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

    def test_restart_required_set_on_change_and_cleared_after_restart(self) -> None:
        """Changing a restart-only setting flags a restart, and a real restart
        (a fresh app re-snapshotting the overlay) clears the flag — the bug was
        that the banner stayed on forever because it only checked whether the
        overlay contained any restart-required key."""
        from api.api_server import create_app
        from fastapi.testclient import TestClient

        self._login_admin()

        # Change a restart-only setting (log_level) to a value different from
        # what this process booted with (the class app booted with no overlay).
        patched = self._client.patch("/api/settings", json={"log_level": "DEBUG"})
        self.assertEqual(patched.status_code, 200, patched.text)
        self.assertTrue(patched.json()["restart_required"])

        # The flag persists across GETs until a restart actually happens.
        got = self._client.get("/api/settings")
        self.assertEqual(got.status_code, 200, got.text)
        self.assertTrue(got.json()["restart_required"])

        # Simulate `docker down && docker up`: a fresh app instance against the
        # same DB re-snapshots the now-updated overlay as its boot baseline.
        restarted_app = create_app(self._scheduler, logging.getLogger("test"))
        with TestClient(restarted_app) as restarted:
            login = restarted.post(
                "/api/auth/login",
                json={
                    "username": self._config.admin_username,
                    "password": self._config.admin_password,
                },
            )
            self.assertEqual(login.status_code, 200, login.text)
            got_after = restarted.get("/api/settings")
            self.assertEqual(got_after.status_code, 200, got_after.text)
            self.assertFalse(got_after.json()["restart_required"])

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

    def test_live_stream_requires_auth(self) -> None:
        # No login cookie — must be rejected with 401.
        response = self._client.get("/api/live/stream")
        self.assertEqual(response.status_code, 401)

    def test_candles_endpoint_requires_auth(self) -> None:
        # No auth cookie — must be rejected with 401.
        response = self._client.get("/api/candles?symbol=BTC")
        self.assertEqual(response.status_code, 401)

    def test_candles_with_stubbed_broker_returns_ohlc_shape(self) -> None:
        """Authenticated request with a stubbed eToro broker returns mapped candle shape."""
        from unittest.mock import Mock

        fake_bars = [
            {
                "symbol": "BTC",
                "timestamp": "2024-01-01T00:00:00+00:00",
                "open": 40000.0,
                "high": 41000.0,
                "low": 39000.0,
                "close": 40500.0,
                "volume": 100.0,
            },
            {
                "symbol": "BTC",
                "timestamp": "2024-01-02T00:00:00+00:00",
                "open": 40500.0,
                "high": 42000.0,
                "low": 40000.0,
                "close": 41500.0,
                "volume": 200.0,
            },
        ]
        broker_stub = Mock()
        broker_stub.instrument_id_for_symbol.return_value = 12345
        broker_stub.get_candles_by_instrument.return_value = fake_bars

        # Temporarily wire the stub broker into the scheduler's trade_manager.
        original_brokers = self._scheduler.trade_manager.brokers
        self._scheduler.trade_manager.brokers = {"etoro": broker_stub}
        try:
            self._login_admin()
            response = self._client.get("/api/candles?symbol=BTC&count=2")
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["symbol"], "BTC")
            self.assertEqual(body["category"], "CRYPTO")
            self.assertEqual(body["granularity"], "OneDay")
            candles = body["candles"]
            self.assertEqual(len(candles), 2)
            # Verify the mapped compact shape for the first candle.
            c = candles[0]
            self.assertIn("t", c)
            self.assertAlmostEqual(c["o"], 40000.0)
            self.assertAlmostEqual(c["h"], 41000.0)
            self.assertAlmostEqual(c["l"], 39000.0)
            self.assertAlmostEqual(c["c"], 40500.0)
            self.assertAlmostEqual(c["v"], 100.0)
            # broker was called with the right args
            broker_stub.instrument_id_for_symbol.assert_called_once_with("BTC")
            broker_stub.get_candles_by_instrument.assert_called_once_with(
                12345, "BTC", count=2, interval="OneDay"
            )
        finally:
            self._scheduler.trade_manager.brokers = original_brokers
            self._client.cookies.clear()

    def test_candles_returns_503_when_no_broker_configured(self) -> None:
        """When no eToro broker is registered, the endpoint returns 503."""
        original_brokers = self._scheduler.trade_manager.brokers
        self._scheduler.trade_manager.brokers = {}
        try:
            self._login_admin()
            response = self._client.get("/api/candles?symbol=BTC")
            self.assertEqual(response.status_code, 503)
            detail = response.json()["detail"]
            self.assertEqual(detail["error"]["code"], "no_broker_configured")
        finally:
            self._scheduler.trade_manager.brokers = original_brokers
            self._client.cookies.clear()


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed in this test env")
class CandleToDictTests(unittest.TestCase):
    """Unit tests for the module-level _candle_to_dict helper.

    These are pure-Python tests: no broker, no network, no DB.
    They run wherever FastAPI is importable (i.e. in Docker).
    """

    def _fn(self):
        from api.api_server import _candle_to_dict
        return _candle_to_dict

    def test_maps_all_standard_bar_fields(self) -> None:
        fn = self._fn()
        bar = {
            "symbol": "ETH",
            "timestamp": "2024-03-15T00:00:00+00:00",
            "open": 3000.0,
            "high": 3100.0,
            "low": 2900.0,
            "close": 3050.0,
            "volume": 500.0,
        }
        result = fn(bar)
        self.assertIn("t", result)
        self.assertIn("2024-03-15", result["t"])
        self.assertAlmostEqual(result["o"], 3000.0)
        self.assertAlmostEqual(result["h"], 3100.0)
        self.assertAlmostEqual(result["l"], 2900.0)
        self.assertAlmostEqual(result["c"], 3050.0)
        self.assertAlmostEqual(result["v"], 500.0)

    def test_volume_none_when_missing(self) -> None:
        fn = self._fn()
        bar = {
            "symbol": "BTC",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "open": 40000.0,
            "high": 41000.0,
            "low": 39000.0,
            "close": 40500.0,
            "volume": None,
        }
        result = fn(bar)
        self.assertIsNone(result["v"])

    def test_zero_volume_treated_as_zero_not_none(self) -> None:
        fn = self._fn()
        bar = {
            "symbol": "BTC",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "open": 40000.0,
            "high": 41000.0,
            "low": 39000.0,
            "close": 40500.0,
            "volume": 0.0,
        }
        result = fn(bar)
        self.assertIsNotNone(result["v"])
        self.assertAlmostEqual(result["v"], 0.0)

    def test_timestamp_normalised_to_utc_iso(self) -> None:
        fn = self._fn()
        bar = {
            "symbol": "BTC",
            "timestamp": "2024-06-01T12:00:00+00:00",
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 10.0,
        }
        result = fn(bar)
        # Must be a non-empty string containing the date
        self.assertIsInstance(result["t"], str)
        self.assertIn("2024-06-01", result["t"])

    def test_output_has_exactly_six_keys(self) -> None:
        fn = self._fn()
        bar = {
            "symbol": "X",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "open": 1.0,
            "high": 2.0,
            "low": 0.5,
            "close": 1.5,
            "volume": 5.0,
        }
        result = fn(bar)
        self.assertEqual(set(result.keys()), {"t", "o", "h", "l", "c", "v"})


@unittest.skipUnless(_FASTAPI_AVAILABLE, "fastapi not installed in this test env")
class FormatEventTests(unittest.TestCase):
    """Unit tests for the module-level _format_event SSE helper.

    Requires FastAPI to be importable (needed to import api_server).
    Run in Docker where all deps are available.
    """

    def test_simple_single_line_event(self) -> None:
        from api.api_server import _format_event

        result = _format_event("snapshot", json.dumps({"a": 1}))
        self.assertIsInstance(result, bytes)
        text = result.decode("utf-8")
        self.assertIn("event: snapshot", text)
        self.assertIn('data: {"a": 1}', text)
        # SSE event terminated by a blank line.
        self.assertTrue(text.endswith("\n\n"))

    def test_empty_data_uses_empty_data_line(self) -> None:
        from api.api_server import _format_event

        result = _format_event("heartbeat", "")
        text = result.decode("utf-8")
        self.assertIn("event: heartbeat", text)
        self.assertIn("data: ", text)

    def test_multiline_data_each_line_prefixed(self) -> None:
        from api.api_server import _format_event

        result = _format_event("append", "line1\nline2")
        text = result.decode("utf-8")
        self.assertIn("data: line1", text)
        self.assertIn("data: line2", text)


if __name__ == "__main__":
    unittest.main()
