"""Market data download, persistence, and cleanup."""

from __future__ import annotations

import logging
from datetime import timedelta

from clients.alpaca_client import AlpacaClient
from core.db import db_cursor, ensure_market_symbol_table, fetch_all, get_market_symbol_table, list_market_symbols
from core.utils import AppConfig, market_data_start, parse_datetime, retry, utc_now


class DataManager:
    """Maintain OHLCV history in SQLite."""

    def __init__(self, config: AppConfig, logger: logging.Logger, alpaca_client: AlpacaClient) -> None:
        self.config = config
        self.logger = logger.getChild("data_manager")
        self.alpaca_client = alpaca_client

    def get_known_symbols(self) -> list[str]:
        rows = list_market_symbols(self.config.db_market_data)
        return [row["symbol"] for row in rows]

    def get_symbol_history(self, symbol: str, limit: int | None = None) -> list[dict]:
        normalized_symbol = str(symbol).upper().strip()
        table_name = get_market_symbol_table(self.config.db_market_data, normalized_symbol)
        if table_name is None:
            return []
        sql = (
            f"SELECT ? AS symbol, timestamp, open, high, low, close, volume "
            f'FROM "{table_name}" ORDER BY timestamp'
        )
        params: tuple = (normalized_symbol,)
        if limit:
            sql = (
                f"SELECT ? AS symbol, timestamp, open, high, low, close, volume "
                f'FROM (SELECT * FROM "{table_name}" ORDER BY timestamp DESC LIMIT ?) ORDER BY timestamp'
            )
            params = (normalized_symbol, limit)
        return fetch_all(self.config.db_market_data, sql, params)

    def get_last_timestamp(self, symbol: str) -> str | None:
        normalized_symbol = str(symbol).upper().strip()
        table_name = get_market_symbol_table(self.config.db_market_data, normalized_symbol)
        if table_name is None:
            return None
        rows = fetch_all(
            self.config.db_market_data,
            f'SELECT timestamp FROM "{table_name}" ORDER BY timestamp DESC LIMIT 1',
        )
        row = rows[0] if rows else None
        return row["timestamp"] if row else None

    @retry()
    def update_symbol(self, symbol: str, category: str) -> int:
        normalized_symbol = str(symbol).upper().strip()
        last_timestamp = self.get_last_timestamp(normalized_symbol)
        first_download = last_timestamp is None
        start = market_data_start(first_download)
        if last_timestamp:
            start = parse_datetime(last_timestamp) + timedelta(days=1)
        if start >= utc_now():
            self.cleanup_old_records(normalized_symbol)
            return 0

        rows = self.alpaca_client.get_bars(symbol=normalized_symbol, category=category, start=start)
        inserted = 0
        if rows:
            with db_cursor(self.config.db_market_data) as cursor:
                table_name = ensure_market_symbol_table(cursor.connection, normalized_symbol)
                for row in rows:
                    cursor.execute(
                        f"""
                        INSERT OR IGNORE INTO "{table_name}"(timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["timestamp"],
                            row["open"],
                            row["high"],
                            row["low"],
                            row["close"],
                            row["volume"],
                        ),
                    )
                    inserted += cursor.rowcount
        self.cleanup_old_records(normalized_symbol)
        self.logger.debug("Updated %s with %s new bars", normalized_symbol, inserted)
        return inserted

    def cleanup_old_records(self, symbol: str | None = None) -> None:
        cutoff = (utc_now() - timedelta(days=365 * 5)).isoformat()
        targets = list_market_symbols(self.config.db_market_data)
        if symbol:
            normalized_symbol = str(symbol).upper().strip()
            targets = [row for row in targets if row["symbol"] == normalized_symbol]
        for row in targets:
            with db_cursor(self.config.db_market_data) as cursor:
                cursor.execute(f'DELETE FROM "{row["table_name"]}" WHERE timestamp < ?', (cutoff,))

    def update_symbols(self, symbol_categories: dict[str, str]) -> None:
        for symbol, category in symbol_categories.items():
            try:
                self.update_symbol(symbol, category)
            except Exception:
                self.logger.exception("Market data update failed for %s", symbol)
