"""Logging configuration for the trading system."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from utils import AppConfig

LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s"


def setup_logging(config: AppConfig) -> logging.Logger:
    """Configure console and rotating file logging."""

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return logging.getLogger("trading_bot")

    root_logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    formatter = logging.Formatter(LOG_FORMAT)

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
    return logging.getLogger("trading_bot")
