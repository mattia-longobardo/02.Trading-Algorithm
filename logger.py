"""Logging configuration for the trading system."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from utils import AppConfig

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s"


class ProductionNoiseFilter(logging.Filter):
    """Drop low-signal recurring records in production."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "trading_bot.scheduler":
            message = record.getMessage()
            if message.startswith("Starting job: monitor_trades") or message.startswith("Completed job: monitor_trades"):
                return False
        return True


def _ensure_universe_logger(config: AppConfig, formatter: logging.Formatter) -> None:
    universe_logger = logging.getLogger("trading_bot.universe.candidates")
    universe_logger.setLevel(logging.INFO)
    universe_logger.propagate = False
    if universe_logger.handlers:
        return

    universe_handler = RotatingFileHandler(
        config.universe_log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    universe_handler.setFormatter(formatter)
    universe_logger.addHandler(universe_handler)


def _configure_external_loggers(config: AppConfig) -> None:
    if config.debug_logging:
        third_party_level = logging.INFO
    else:
        third_party_level = logging.WARNING

    for logger_name in ("apscheduler", "httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(logger_name).setLevel(third_party_level)


def _configure_handlers(
    config: AppConfig,
    formatter: logging.Formatter,
    root_logger: logging.Logger,
) -> None:
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)
        handler.setLevel(getattr(logging, config.log_level, logging.INFO))
        handler.filters.clear()
        if not config.debug_logging:
            handler.addFilter(ProductionNoiseFilter())


def setup_logging(config: AppConfig) -> logging.Logger:
    """Configure console and rotating file logging."""

    root_logger = logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT)

    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        file_handler = RotatingFileHandler(
            config.log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    _configure_handlers(config, formatter, root_logger)
    _configure_external_loggers(config)
    _ensure_universe_logger(config, formatter)

    return logging.getLogger("trading_bot")
