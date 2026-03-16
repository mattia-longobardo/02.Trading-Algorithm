"""Logging configuration for the trading system."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from utils import AppConfig

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s"


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


def setup_logging(config: AppConfig) -> logging.Logger:
    """Configure console and rotating file logging."""

    root_logger = logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT)
    if root_logger.handlers:
        _ensure_universe_logger(config, formatter)
        return logging.getLogger("trading_bot")

    root_logger.setLevel(getattr(logging, config.log_level, logging.INFO))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        config.log_file,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    _ensure_universe_logger(config, formatter)

    return logging.getLogger("trading_bot")
