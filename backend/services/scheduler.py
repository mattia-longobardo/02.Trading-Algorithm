"""Scheduler bootstrap and guarded job execution."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from filelock import FileLock, Timeout

from core.utils import AppConfig, merge_universe_categories, utc_now
from services.report import ReportGenerator
from services.trade_manager import TradeManager
from services.universe_manager import UniverseManager


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
        self._execution_lock = threading.Lock()
        self._pending_jobs: OrderedDict[str, Callable[[], None]] = OrderedDict()
        self._pending_jobs_lock = threading.Lock()
        self._pending_jobs_drain_lock = threading.Lock()

    @staticmethod
    def _universe_is_empty(universe: Any) -> bool:
        if not isinstance(universe, dict):
            return True
        for provider_universe in universe.values():
            if isinstance(provider_universe, dict):
                if any(provider_universe.get(category) for category in ("STOCK", "CRYPTO")):
                    return False
            elif isinstance(provider_universe, list) and provider_universe:
                # Legacy flat shape — count any non-empty list as non-empty.
                return False
        return True

    def _missing_market_data(self, universe: Any) -> bool:
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
            self.trade_manager.sync_broker_state()

    @contextmanager
    def _process_lock(self, timeout: float) -> Any:
        with FileLock(self.config.lock_file, timeout=timeout):
            yield

    def _should_log_monitor_job(self, job_name: str) -> bool:
        return self.config.debug_logging or job_name != "monitor_trades"

    def _defer_job(self, job_name: str, func: Callable[[], None], *, log_if_new: bool) -> None:
        with self._pending_jobs_lock:
            already_pending = job_name in self._pending_jobs
            if not already_pending:
                self._pending_jobs[job_name] = func

        if already_pending or not log_if_new:
            return

        if self._should_log_monitor_job(job_name):
            self.logger.info("Deferred job %s because another execution is still running", job_name)

    def _pop_pending_job(self) -> tuple[str, Callable[[], None]] | None:
        with self._pending_jobs_lock:
            if not self._pending_jobs:
                return None
            return self._pending_jobs.popitem(last=False)

    def _run_scheduled_job(
        self,
        job_name: str,
        func: Callable[[], None],
        *,
        deferred: bool = False,
        drain_after: bool = True,
    ) -> bool:
        acquired_execution_lock = self._execution_lock.acquire(blocking=False)
        if not acquired_execution_lock:
            self._defer_job(job_name, func, log_if_new=not deferred)
            return False

        try:
            try:
                with self._process_lock(timeout=0):
                    start_message = "Starting deferred job: %s" if deferred else "Starting job: %s"
                    complete_message = "Completed deferred job: %s" if deferred else "Completed job: %s"
                    if self._should_log_monitor_job(job_name):
                        self.logger.info(start_message, job_name)
                    func()
                    if self._should_log_monitor_job(job_name):
                        self.logger.info(complete_message, job_name)
                    return True
            except Timeout:
                self._defer_job(job_name, func, log_if_new=not deferred)
                return False
            except Exception:
                self.logger.exception("Job %s failed", job_name)
                return True
        finally:
            self._execution_lock.release()
            if drain_after:
                self._drain_pending_jobs()

    def _drain_pending_jobs(self) -> None:
        if not self._pending_jobs_drain_lock.acquire(blocking=False):
            return

        try:
            while True:
                pending_job = self._pop_pending_job()
                if pending_job is None:
                    return

                job_name, func = pending_job
                executed = self._run_scheduled_job(
                    job_name,
                    func,
                    deferred=True,
                    drain_after=False,
                )
                if not executed:
                    return
        finally:
            self._pending_jobs_drain_lock.release()

    def guarded(self, job_name: str, func: Callable[[], None]) -> Callable[[], None]:
        def wrapped() -> None:
            self._run_scheduled_job(job_name, func)

        return wrapped

    def run_with_lock(self, job_name: str, func: Callable[[], Any]) -> Any:
        acquired_execution_lock = self._execution_lock.acquire(timeout=1)
        if not acquired_execution_lock:
            raise JobExecutionLockedError(f"Job {job_name} is already running")

        try:
            with self._process_lock(timeout=1):
                self.logger.info("Starting manual job: %s", job_name)
                result = func()
                self.logger.info("Completed manual job: %s", job_name)
                return result
        except Timeout as exc:
            raise JobExecutionLockedError(f"Job {job_name} is already running") from exc
        finally:
            self._execution_lock.release()
            self._drain_pending_jobs()

    def job_download_market_data(self) -> None:
        universe = self.universe_manager.get_current_universe()
        monitored = self.trade_manager.symbols_to_monitor(universe)
        self.trade_manager.data_manager.update_symbols(monitored)

    def job_monitor_trades(self) -> None:
        self.trade_manager.sync_broker_state()

    def job_evaluate_signals(self) -> None:
        self.trade_manager.sync_broker_state()
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

    def job_quarterly_report(self) -> None:
        self.report_generator.generate_quarterly_report()

    def job_biannual_report(self) -> None:
        self.report_generator.generate_biannual_report()

    def job_annual_report(self) -> None:
        self.report_generator.generate_annual_report()

    def job_review_stale_pending_orders(self) -> None:
        self.trade_manager.review_stale_pending_trades(min_age_days=7)

    def job_record_equity_snapshot(self) -> None:
        # Local import to avoid pulling app_db at scheduler import time
        # (keeps the test stubs that mock out scheduler imports working).
        from services.equity_snapshots import record_snapshots_all

        record_snapshots_all(self.config, self.trade_manager.brokers, self.logger)

    def job_reconcile_closed_trades(self) -> None:
        # Realign locally-stored closed trades with the broker's authoritative
        # realized history (fixes estimated close prices and backfills positions
        # the bot never tracked). Read-mostly; safe to run alongside trading.
        self.trade_manager.reconcile_closed_trades()

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

    def run_manual_quarterly_report(self) -> dict:
        return self.run_with_lock("manual_quarterly_report", self.report_generator.generate_quarterly_report)

    def run_manual_biannual_report(self) -> dict:
        return self.run_with_lock("manual_biannual_report", self.report_generator.generate_biannual_report)

    def run_manual_annual_report(self) -> dict:
        return self.run_with_lock("manual_annual_report", self.report_generator.generate_annual_report)

    def run_manual_reconcile_closed_trades(self, lookback_days: int = 365) -> dict[str, Any]:
        """One-time full-history reconciliation across all brokers.

        Unlike the 30-minute recurring job (short lookback), this scans a wide
        window so the trades DB is fully realigned with the broker's realized
        history — used to backfill historical closes after first deploy.
        """

        def execute() -> dict[str, Any]:
            min_date = (utc_now() - timedelta(days=lookback_days)).date()
            results = {
                provider: self.trade_manager.reconcile_closed_trades(min_date=min_date, provider=provider)
                for provider in self.trade_manager.brokers
            }
            return {"reconciled": results, "lookback_days": lookback_days}

        return self.run_with_lock("manual_reconcile_closed_trades", execute)

    def reset_locks(self) -> dict[str, Any]:
        """Force-reset stuck execution locks and the pending jobs queue.

        Replaces the in-process execution lock with a fresh one, removes the
        on-disk lock file if present, and clears any queued pending jobs.
        Call this only when the scheduler is demonstrably stuck — a job that is
        still running legitimately will keep running, but the lock gate will be
        open again for subsequent jobs.
        """
        import os

        cleared_pending: list[str] = []
        lock_file_removed = False

        # Swap in a fresh threading lock so the gate opens immediately.
        self._execution_lock = threading.Lock()

        # Clear pending jobs queue.
        with self._pending_jobs_lock:
            cleared_pending = list(self._pending_jobs.keys())
            self._pending_jobs.clear()

        # Remove the on-disk lock file so FileLock can be re-acquired.
        lock_path = self.config.lock_file
        try:
            os.remove(lock_path)
            lock_file_removed = True
        except FileNotFoundError:
            pass

        self.logger.warning(
            "Scheduler locks reset: lock_file_removed=%s, pending_jobs_cleared=%s",
            lock_file_removed,
            cleared_pending,
        )
        return {
            "lock_file_removed": lock_file_removed,
            "pending_jobs_cleared": cleared_pending,
        }

    def register_jobs(self) -> None:
        self.scheduler.add_job(
            self.guarded("monitor_trades", self.job_monitor_trades),
            CronTrigger(minute="*"),
            id="monitor_trades",
            max_instances=2,
            replace_existing=True,
        )
        # --- Milan schedule (UTC, based on CET=UTC+1): 30 min before open, midday, 30 min before close ---
        # Milan opens 09:00 CET → 08:00 UTC, closes 17:30 CET → 16:30 UTC
        self.scheduler.add_job(
            self.guarded("evaluate_signals_milan_preopen", self.job_evaluate_signals),
            CronTrigger(hour=7, minute=30),
            id="evaluate_signals_milan_preopen",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("evaluate_signals_milan_midday", self.job_evaluate_signals),
            CronTrigger(hour=12, minute=15),
            id="evaluate_signals_milan_midday",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("evaluate_signals_milan_preclose", self.job_evaluate_signals),
            CronTrigger(hour=16, minute=0),
            id="evaluate_signals_milan_preclose",
            replace_existing=True,
        )
        # --- New York schedule (UTC, based on EST=UTC-5): 30 min before open, midday, 30 min before close ---
        # NYSE/NASDAQ opens 09:30 EST → 14:30 UTC, closes 16:00 EST → 21:00 UTC
        self.scheduler.add_job(
            self.guarded("evaluate_signals_ny_preopen", self.job_evaluate_signals),
            CronTrigger(hour=14, minute=0),
            id="evaluate_signals_ny_preopen",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("evaluate_signals_ny_midday", self.job_evaluate_signals),
            CronTrigger(hour=17, minute=45),
            id="evaluate_signals_ny_midday",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("evaluate_signals_ny_preclose", self.job_evaluate_signals),
            CronTrigger(hour=20, minute=30),
            id="evaluate_signals_ny_preclose",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self.guarded("review_stale_pending_orders_1200", self.job_review_stale_pending_orders),
            CronTrigger(hour=12, minute=0),
            id="review_stale_pending_orders_1200",
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
        # Quarterly report: fires on the 1st of Jan/Apr/Jul/Oct at 00:00 UTC.
        self.scheduler.add_job(
            self.guarded("quarterly_report", self.job_quarterly_report),
            CronTrigger(month="1,4,7,10", day=1, hour=0, minute=0),
            id="quarterly_report",
            replace_existing=True,
        )
        # Bi-annual report: fires on the 1st of Jan/Jul at 00:30 UTC.
        self.scheduler.add_job(
            self.guarded("biannual_report", self.job_biannual_report),
            CronTrigger(month="1,7", day=1, hour=0, minute=30),
            id="biannual_report",
            replace_existing=True,
        )
        # Annual report: fires on January 1st at 01:00 UTC.
        self.scheduler.add_job(
            self.guarded("annual_report", self.job_annual_report),
            CronTrigger(month=1, day=1, hour=1, minute=0),
            id="annual_report",
            replace_existing=True,
        )
        # Account-equity snapshot every 15 minutes — feeds the dashboard's
        # "andamento del saldo totale" chart. Purely additive, never
        # interferes with trading lifecycle. Skipped silently if the
        # broker call fails (next tick will retry).
        self.scheduler.add_job(
            self.guarded("equity_snapshot", self.job_record_equity_snapshot),
            CronTrigger(minute="*/15"),
            id="equity_snapshot",
            replace_existing=True,
        )
        # Closed-trade reconciliation every 30 minutes — overwrites locally
        # estimated close prices/PnL with eToro's realized history and backfills
        # untracked closed positions so the trades DB matches the account.
        self.scheduler.add_job(
            self.guarded("reconcile_closed_trades", self.job_reconcile_closed_trades),
            CronTrigger(minute="5,35"),
            id="reconcile_closed_trades",
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
