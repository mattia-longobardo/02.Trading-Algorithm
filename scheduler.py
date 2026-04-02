"""Scheduler bootstrap and guarded job execution."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from filelock import FileLock, Timeout

from report import ReportGenerator
from trade_manager import TradeManager
from universe_manager import UniverseManager
from utils import AppConfig


class JobExecutionLockedError(RuntimeError):
    """Raised when a manual or scheduled job cannot acquire the shared lock."""


class TradingScheduler:
    """Run scheduled jobs with a lock to prevent overlapping execution."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        trade_manager: TradeManager,
        universe_manager: UniverseManager,
        report_generator: ReportGenerator,
    ) -> None:
        self.config = config
        self.logger = logger.getChild("scheduler")
        self.trade_manager = trade_manager
        self.universe_manager = universe_manager
        self.report_generator = report_generator
        self.scheduler = BlockingScheduler(timezone="UTC")
        self.lock = FileLock(config.lock_file, timeout=1)

    @staticmethod
    def _universe_is_empty(universe: dict[str, list[str]]) -> bool:
        return not universe.get("STOCK") and not universe.get("CRYPTO")

    def _missing_market_data(self, universe: dict[str, list[str]]) -> bool:
        monitored = self.trade_manager.symbols_to_monitor(universe)
        if not monitored:
            return True
        known_symbols = set(self.trade_manager.data_manager.get_known_symbols())
        return any(symbol not in known_symbols for symbol in monitored)

    def bootstrap_initial_run_if_needed(self) -> None:
        universe = self.universe_manager.get_current_universe()
        missing_universe = self._universe_is_empty(universe)
        self.job_monitor_trades()

        if missing_universe:
            self.logger.info("Universe assente o vuoto: eseguo una bootstrap run prima dello scheduler")
            self.job_refresh_universe()
            self.job_evaluate_signals()
            return

        if self._missing_market_data(universe):
            self.logger.info("Storico mancante per il bootstrap iniziale: eseguo il primo ciclo schedulato una volta")
            self.job_download_market_data()
            self.trade_manager.sync_alpaca_state()

    def guarded(self, job_name: str, func: Callable[[], None]) -> Callable[[], None]:
        def wrapped() -> None:
            try:
                with self.lock:
                    if self.config.debug_logging or job_name != "monitor_trades":
                        self.logger.info("Starting job: %s", job_name)
                    func()
                    if self.config.debug_logging or job_name != "monitor_trades":
                        self.logger.info("Completed job: %s", job_name)
            except Timeout:
                self.logger.warning("Skipped job %s because another execution is still running", job_name)
            except Exception:
                self.logger.exception("Job %s failed", job_name)

        return wrapped

    def run_with_lock(self, job_name: str, func: Callable[[], Any]) -> Any:
        try:
            with self.lock:
                self.logger.info("Starting manual job: %s", job_name)
                result = func()
                self.logger.info("Completed manual job: %s", job_name)
                return result
        except Timeout as exc:
            raise JobExecutionLockedError(f"Job {job_name} is already running") from exc

    def job_download_market_data(self) -> None:
        universe = self.universe_manager.get_current_universe()
        monitored = self.trade_manager.symbols_to_monitor(universe)
        self.trade_manager.data_manager.update_symbols(monitored)

    def job_monitor_trades(self) -> None:
        self.trade_manager.sync_alpaca_state()

    def job_evaluate_signals(self) -> None:
        self.trade_manager.sync_alpaca_state()
        universe = self.universe_manager.get_current_universe()
        if self._universe_is_empty(universe):
            universe = self.universe_manager.select_trading_universe()
        monitored = self.trade_manager.symbols_to_monitor(universe)
        self.trade_manager.data_manager.update_symbols(monitored)
        self.trade_manager.refresh_open_trade_protections()
        self.trade_manager.evaluate_cycle(universe)

    def job_refresh_universe_and_signals(self) -> None:
        self.job_refresh_universe()
        self.job_evaluate_signals()

    def job_refresh_universe(self) -> None:
        universe = self.universe_manager.select_trading_universe()
        monitored = self.trade_manager.symbols_to_monitor(universe)
        self.trade_manager.data_manager.update_symbols(monitored)

    def job_weekly_report(self) -> None:
        self.report_generator.generate_weekly_report()

    def job_review_stale_pending_orders(self) -> None:
        self.trade_manager.review_stale_pending_trades(min_age_days=7)

    def run_manual_refresh_universe(self) -> dict[str, list[str]]:
        def execute() -> dict[str, list[str]]:
            universe = self.universe_manager.select_trading_universe()
            monitored = self.trade_manager.symbols_to_monitor(universe)
            self.trade_manager.data_manager.update_symbols(monitored)
            return universe

        return self.run_with_lock("manual_refresh_universe", execute)

    def run_manual_generate_new_orders(self) -> dict[str, object]:
        def execute() -> dict[str, object]:
            before_trades = self.trade_manager.get_open_or_pending_trades()
            before_ids = {int(trade["id"]) for trade in before_trades}
            self.job_evaluate_signals()
            universe = self.universe_manager.get_current_universe()
            after_trades = self.trade_manager.get_open_or_pending_trades()
            new_trades = [trade for trade in after_trades if int(trade["id"]) not in before_ids]
            return {
                "universe": universe,
                "new_orders": new_trades,
                "new_orders_count": len(new_trades),
                "active_trades_count": len(after_trades),
            }

        return self.run_with_lock("manual_generate_new_orders", execute)

    def run_manual_weekly_report(self) -> dict:
        return self.run_with_lock("manual_weekly_report", self.report_generator.generate_weekly_report)

    def register_jobs(self) -> None:
        self.scheduler.add_job(
            self.guarded("monitor_trades", self.job_monitor_trades),
            CronTrigger(minute="*"),
            id="monitor_trades",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("evaluate_signals_0010", self.job_evaluate_signals),
            CronTrigger(hour=0, minute=10),
            id="evaluate_signals_0010",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("review_stale_pending_orders_1200", self.job_review_stale_pending_orders),
            CronTrigger(hour=12, minute=0),
            id="review_stale_pending_orders_1200",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("evaluate_signals_1210", self.job_evaluate_signals),
            CronTrigger(hour=12, minute=10),
            id="evaluate_signals_1210",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("refresh_universe_weekly", self.job_refresh_universe),
            CronTrigger(day_of_week="sun", hour=22, minute=0),
            id="refresh_universe_weekly",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("weekly_report", self.job_weekly_report),
            CronTrigger(day_of_week="sun", hour=23, minute=0),
            id="weekly_report",
            replace_existing=True,
        )

    def start(self) -> None:
        self.bootstrap_initial_run_if_needed()
        self.register_jobs()
        self.logger.info("Scheduler started with UTC cron triggers")
        self.scheduler.start()

    def shutdown(self, wait: bool = True) -> None:
        """Stop the scheduler gracefully when the process receives a shutdown signal."""

        if not self.scheduler.running:
            return
        self.logger.info("Shutting down scheduler")
        self.scheduler.shutdown(wait=wait)
