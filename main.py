"""Application entry point."""

from __future__ import annotations

import signal
import threading

from alpaca_client import AlpacaClient
from api_server import create_api_server
from data_manager import DataManager
from db import initialize_databases
from gpt_client import GPTClient
from logger import setup_logging
from report import ReportGenerator
from scheduler import TradingScheduler
from trade_manager import TradeManager
from universe_manager import UniverseManager
from utils import load_config


def main() -> None:
    """Initialize dependencies and start the scheduler plus manual API server."""

    config = load_config()
    logger = setup_logging(config)
    initialize_databases(config.db_market_data, config.db_trades)

    alpaca_client = AlpacaClient(config, logger)
    gpt_client = GPTClient(config, logger)
    data_manager = DataManager(config, logger, alpaca_client)
    trade_manager = TradeManager(config, logger, alpaca_client, data_manager, gpt_client)
    universe_manager = UniverseManager(config, logger, alpaca_client, gpt_client)
    report_generator = ReportGenerator(config, logger, trade_manager)

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
