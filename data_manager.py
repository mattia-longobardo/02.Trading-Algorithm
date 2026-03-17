"""Market data download, persistence, and cleanup."""

from __future__ import annotations

import logging
from datetime import timedelta

from alpaca_client import AlpacaClient
from db import db_cursor, fetch_all, fetch_one
from utils import AppConfig, market_data_start, parse_datetime, retry, utc_now


class DataManager:
    """Maintain OHLCV history in SQLite."""

    def __init__(self, config: AppConfig, logger: logging.Logger, alpaca_client: AlpacaClient) -> None:
        self.config = config
        self.logger = logger.getChild("data_manager")
        self.alpaca_client = alpaca_client

    def get_known_symbols(self) -> list[str]:
        rows = fetch_all(self.config.db_market_data, "SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol")
        return [row["symbol"] for row in rows]

    def get_symbol_history(self, symbol: str, limit: int | None = None) -> list[dict]:
        sql = "SELECT symbol, timestamp, open, high, low, close, volume FROM ohlcv WHERE symbol = ? ORDER BY timestamp"
        params: tuple = (symbol,)
        if limit:
            sql = (
                "SELECT symbol, timestamp, open, high, low, close, volume "
                "FROM (SELECT * FROM ohlcv WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?) ORDER BY timestamp"
            )
            params = (symbol, limit)
        return fetch_all(self.config.db_market_data, sql, params)

    def get_last_timestamp(self, symbol: str) -> str | None:
        row = fetch_one(
            self.config.db_market_data,
            "SELECT timestamp FROM ohlcv WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        )
        return row["timestamp"] if row else None

    @retry()
    def update_symbol(self, symbol: str, category: str) -> int:
        last_timestamp = self.get_last_timestamp(symbol)
        first_download = last_timestamp is None
        start = market_data_start(first_download)
        if last_timestamp:
            start = parse_datetime(last_timestamp) + timedelta(days=1)
        if start >= utc_now():
            self.cleanup_old_records(symbol)
            return 0

        rows = self.alpaca_client.get_bars(symbol=symbol, category=category, start=start)
        inserted = 0
        if rows:
            with db_cursor(self.config.db_market_data) as cursor:
                for row in rows:
                    cursor.execute(
                        """
                        INSERT OR IGNORE INTO ohlcv(symbol, timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["symbol"],
                            row["timestamp"],
                            row["open"],
                            row["high"],
                            row["low"],
                            row["close"],
                            row["volume"],
                        ),
                    )
                    inserted += cursor.rowcount
        self.cleanup_old_records(symbol)
        self.logger.debug("Updated %s with %s new bars", symbol, inserted)
        return inserted

    def cleanup_old_records(self, symbol: str | None = None) -> None:
        cutoff = (utc_now() - timedelta(days=365 * 5)).isoformat()
        query = "DELETE FROM ohlcv WHERE timestamp < ?"
        params: tuple = (cutoff,)
        if symbol:
            query += " AND symbol = ?"
            params = (cutoff, symbol)
        with db_cursor(self.config.db_market_data) as cursor:
            cursor.execute(query, params)

    def update_symbols(self, symbol_categories: dict[str, str]) -> None:
        for symbol, category in symbol_categories.items():
            try:
                self.update_symbol(symbol, category)
            except Exception:
                self.logger.exception("Market data update failed for %s", symbol)
