"""Scheduler bootstrap and guarded job execution."""

from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from filelock import FileLock, Timeout

from report import ReportGenerator
from trade_manager import TradeManager
from universe_manager import UniverseManager
from utils import AppConfig


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

        if missing_universe:
            self.logger.info("Universe assente o vuoto: eseguo una bootstrap run prima dello scheduler")
            universe = self.universe_manager.select_weekly_universe()

        if self._missing_market_data(universe):
            self.logger.info("Storico mancante per il bootstrap iniziale: eseguo il primo ciclo schedulato una volta")
            self.job_download_market_data()
            self.job_sync_and_analyze()

    def guarded(self, job_name: str, func: Callable[[], None]) -> Callable[[], None]:
        def wrapped() -> None:
            try:
                with self.lock:
                    self.logger.info("Starting job: %s", job_name)
                    func()
                    self.logger.info("Completed job: %s", job_name)
            except Timeout:
                self.logger.warning("Skipped job %s because another execution is still running", job_name)
            except Exception:
                self.logger.exception("Job %s failed", job_name)

        return wrapped

    def job_download_market_data(self) -> None:
        universe = self.universe_manager.get_current_universe()
        monitored = self.trade_manager.symbols_to_monitor(universe)
        self.trade_manager.data_manager.update_symbols(monitored)

    def job_sync_and_analyze(self) -> None:
        self.trade_manager.sync_alpaca_state()
        universe = self.universe_manager.get_current_universe()
        self.trade_manager.evaluate_cycle(universe)

    def job_refresh_universe(self) -> None:
        self.universe_manager.select_weekly_universe()

    def job_weekly_report(self) -> None:
        self.report_generator.generate_weekly_report()

    def register_jobs(self) -> None:
        self.scheduler.add_job(
            self.guarded("download_market_data_0001", self.job_download_market_data),
            CronTrigger(hour=0, minute=1),
            id="download_market_data_0001",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("download_market_data_1201", self.job_download_market_data),
            CronTrigger(hour=12, minute=1),
            id="download_market_data_1201",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("sync_and_analyze_0010", self.job_sync_and_analyze),
            CronTrigger(hour=0, minute=10),
            id="sync_and_analyze_0010",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("sync_and_analyze_1210", self.job_sync_and_analyze),
            CronTrigger(hour=12, minute=10),
            id="sync_and_analyze_1210",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("weekly_universe", self.job_refresh_universe),
            CronTrigger(day_of_week="mon", hour=0, minute=0),
            id="weekly_universe",
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
