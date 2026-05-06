import json
import logging
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import urlopen

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

alpaca_client_stub = ModuleType("alpaca_client")
alpaca_client_stub.AlpacaClient = object
sys.modules.setdefault("alpaca_client", alpaca_client_stub)

gpt_client_stub = ModuleType("gpt_client")
gpt_client_stub.GPTClient = object
sys.modules.setdefault("gpt_client", gpt_client_stub)

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

from api_server import create_api_server
from scheduler import TradingScheduler
from utils import AppConfig


def make_config() -> AppConfig:
    return AppConfig(
        openai_api_key="test-openai-key",
        alpaca_api_key="test-alpaca-key",
        alpaca_secret_key="test-alpaca-secret",
        alpaca_base_url="https://paper-api.alpaca.markets",
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

        self.trade_manager.sync_alpaca_state.assert_called_once()
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

        self.trade_manager.sync_alpaca_state.assert_called_once()
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


class TradingApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = Path(self.temp_dir.name) / "trading.log"
        self.log_file.write_text("line 1\nline 2\nline 3\n", encoding="utf-8")
        self.scheduler = Mock()
        self.scheduler.config = Mock()
        self.scheduler.config.log_file = str(self.log_file)
        self.scheduler.run_manual_refresh_universe.return_value = {"STOCK": ["AAPL"], "CRYPTO": []}
        self.scheduler.run_manual_generate_new_orders.return_value = {"new_orders": [], "new_orders_count": 0}
        self.scheduler.run_manual_weekly_report.return_value = {"pnl_total": 42.0}
        self.server = create_api_server("127.0.0.1", 0, self.scheduler, logging.getLogger("test"))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def test_root_returns_health_check_json(self) -> None:
        with urlopen(f"{self.base_url}/") as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "application/json")
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload, {"status": "ok", "service": "trading-backend"})

    def test_logs_endpoint_returns_log_tail(self) -> None:
        with urlopen(f"{self.base_url}/api/logs?lines=2") as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["line_count"], 2)
        self.assertEqual(payload["log_file"], str(self.log_file))
        self.assertEqual(payload["logs"], "line 2\nline 3\n")
        self.assertNotEqual(payload["updated_at"], "N/A")

    def test_log_stream_endpoint_emits_sse_events(self) -> None:
        with urlopen(f"{self.base_url}/api/logs/stream", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get_content_type(), "text/event-stream")
            self.assertEqual(response.headers.get_content_charset(), "utf-8")

    def test_get_endpoints_trigger_expected_scheduler_methods(self) -> None:
        response_payloads = {}
        for path in ("/api/universe/generate", "/api/orders/generate", "/api/report/generate"):
            with urlopen(f"{self.base_url}{path}") as response:
                self.assertEqual(response.status, 200)
                response_payloads[path] = json.loads(response.read().decode("utf-8"))

        self.scheduler.run_manual_refresh_universe.assert_called_once()
        self.scheduler.run_manual_generate_new_orders.assert_called_once()
        self.scheduler.run_manual_weekly_report.assert_called_once()
        self.assertEqual(response_payloads["/api/universe/generate"]["action"], "universe")
        self.assertEqual(response_payloads["/api/orders/generate"]["action"], "new_orders")
        self.assertEqual(response_payloads["/api/report/generate"]["action"], "report")
        self.assertEqual(response_payloads["/api/universe/generate"]["status"], "ok")
        self.assertEqual(response_payloads["/api/orders/generate"]["message"], "new_orders job completed successfully")
        self.assertEqual(response_payloads["/api/report/generate"]["message"], "report job completed successfully")

    def test_unknown_path_returns_404(self) -> None:
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/api/unknown")

        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
