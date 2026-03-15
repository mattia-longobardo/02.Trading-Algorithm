"""Application entry point."""

from __future__ import annotations

from alpaca_client import AlpacaClient
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
    """Initialize dependencies and start the scheduler."""

    config = load_config()
    logger = setup_logging(config)
    initialize_databases(config.db_market_data, config.db_trades)

    alpaca_client = AlpacaClient(config, logger)
    gpt_client = GPTClient(config, logger)
    data_manager = DataManager(config, logger, alpaca_client)
    trade_manager = TradeManager(config, logger, alpaca_client, data_manager, gpt_client)
    universe_manager = UniverseManager(config, logger, alpaca_client, gpt_client)
    report_generator = ReportGenerator(logger, trade_manager)

    current_universe = universe_manager.get_current_universe()
    if not current_universe.get("STOCK") and not current_universe.get("CRYPTO"):
        logger.info("Universe file is empty, generating an initial weekly universe before starting the scheduler")
        universe_manager.select_weekly_universe()

    scheduler = TradingScheduler(config, logger, trade_manager, universe_manager, report_generator)
    scheduler.start()


if __name__ == "__main__":
    main()
