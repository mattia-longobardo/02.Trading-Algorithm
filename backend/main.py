"""Application entry point."""

from __future__ import annotations

import signal
import threading
from typing import Any

from api.api_server import create_api_server
from clients.alpaca_client import AlpacaClient
from clients.etoro_client import EToroClient
from clients.gpt_client import GPTClient, get_default_prompts
from core.app_db import (
    initialize_app_database,
    read_all_settings,
    seed_admin_user_if_missing,
    seed_initial_prompt_versions,
)
from core.db import initialize_databases
from core.logger import setup_logging
from core.utils import (
    PROVIDER_ALPACA,
    PROVIDER_ETORO,
    apply_settings_overlay,
    load_config,
)
from services.data_manager import DataManager
from services.report import ReportGenerator
from services.report_index import reorganize_uncategorized, sync_reports
from services.scheduler import TradingScheduler
from services.trade_manager import TradeManager
from services.universe_manager import UniverseManager


def main() -> None:
    """Initialize dependencies and start the scheduler plus manual API server."""

    config = load_config()
    logger = setup_logging(config)

    # Trading databases (unchanged behavior).
    initialize_databases(config.db_market_data, config.db_trades)

    # Application database (auth, prompts, settings, audit, report index).
    initialize_app_database(config.db_app)

    # Seed the admin user from env on first boot. If the row already exists
    # we never touch it — operators must rotate via the UI or a manual reset.
    seeded = seed_admin_user_if_missing(
        config.db_app,
        username=config.admin_username,
        password=config.admin_password,
        display_name=config.admin_display_name or config.admin_username,
    )
    if seeded:
        logger.info(
            "Seeded admin user %s from ADMIN_USERNAME/ADMIN_PASSWORD env",
            config.admin_username,
        )

    # Seed the initial prompt versions from the hard-coded constants.
    seed_initial_prompt_versions(config.db_app, get_default_prompts())

    # Apply any operator-supplied settings overlay before instantiating the
    # rest of the trading components, so changes already in app.sqlite take
    # effect on this boot.
    overlay = read_all_settings(config.db_app)
    if overlay:
        apply_settings_overlay(config, overlay)
        logger.info("Applied %s setting override(s) from app.sqlite", len(overlay))

    # Index any report files that already exist on disk, then auto-place
    # any historical reports that pre-date the year/month folder feature.
    try:
        added = sync_reports(config.db_app, config.report_dir, logger)
        if added:
            logger.info("Indexed %s previously-unseen report file(s)", added)
        moved = reorganize_uncategorized(config.db_app, logger)
        if moved:
            logger.info("Backfilled folder placement for %s existing report(s)", moved)
    except Exception:
        logger.exception("Initial report-index sync failed")

    # ------------------------------------------------------------------
    # Provider auto-detection: instantiate only the brokers whose API
    # keys are configured. The frontend reads the active set from
    # ``GET /api/providers`` and hides surfaces accordingly.
    # ------------------------------------------------------------------
    brokers: dict[str, Any] = {}
    if config.alpaca_enabled:
        brokers[PROVIDER_ALPACA] = AlpacaClient(config, logger)
        logger.info("Alpaca client enabled")
    else:
        logger.info("Alpaca credentials missing; module disabled")

    if config.etoro_enabled:
        brokers[PROVIDER_ETORO] = EToroClient(config, logger)
        logger.info("eToro client enabled (%s account)", "demo" if config.demo else "real")
    else:
        logger.info("eToro credentials missing; module disabled")

    if not brokers:
        logger.warning(
            "No broker is configured. The scheduler will start but every "
            "trading job will be a no-op until at least one provider is "
            "configured. The frontend will surface an empty/onboarding state."
        )

    gpt_client = GPTClient(config, logger)
    data_manager = DataManager(config, logger, brokers)
    trade_manager = TradeManager(config, logger, brokers, data_manager, gpt_client)
    universe_manager = UniverseManager(config, logger, brokers, gpt_client)
    report_generator = ReportGenerator(config, logger, trade_manager)

    # Best-effort first snapshot per provider so the dashboard chart has
    # at least one data point before the 15-min snapshot job fires.
    try:
        from services.equity_snapshots import record_snapshots_all

        record_snapshots_all(config, brokers, logger)
    except Exception:
        logger.exception("Initial equity snapshot failed (non-fatal)")

    scheduler = TradingScheduler(config, logger, trade_manager, universe_manager, report_generator)
    api_server = create_api_server(config.api_host, config.api_port, scheduler, logger)
    scheduler_thread = threading.Thread(target=scheduler.start, name="trading-scheduler", daemon=True)
    shutdown_requested = False

    def handle_shutdown(signum: int, _frame: object) -> None:
        nonlocal shutdown_requested
        if shutdown_requested:
            logger.warning("Received signal %s again while shutdown is already in progress", signum)
            return
        shutdown_requested = True
        logger.info("Received signal %s, shutting down gracefully", signum)
        api_server.shutdown()
        api_server.server_close()
        scheduler.shutdown(wait=True)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        scheduler_thread.start()
        logger.info("API server listening on http://%s:%s", config.api_host, config.api_port)
        api_server.serve_forever()
    finally:
        api_server.server_close()
        scheduler.shutdown(wait=False)
        scheduler_thread.join(timeout=5)


if __name__ == "__main__":
    main()
