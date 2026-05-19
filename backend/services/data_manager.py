"""Market data download, persistence, and cleanup.

Multi-provider aware: receives a registry of broker clients keyed by provider
name (``alpaca``) and dispatches OHLCV fetches to whichever broker owns the
symbol.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Mapping

from core.db import db_cursor, ensure_market_symbol_table, fetch_all, get_market_symbol_table, list_market_symbols
from core.utils import AppConfig, market_data_start, parse_datetime, retry, utc_now


class DataManager:
    """Maintain OHLCV history in SQLite, dispatching by trading provider."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        broker_clients: Mapping[str, Any] | Any | None = None,
        *,
        alpaca_client: Any | None = None,
    ) -> None:
        self.config = config
        self.logger = logger.getChild("data_manager")
        if isinstance(broker_clients, Mapping):
            self._brokers: dict[str, Any] = dict(broker_clients)
        elif broker_clients is not None:
            self._brokers = {"alpaca": broker_clients}
        else:
            self._brokers = {}
        if alpaca_client is not None:
            self._brokers["alpaca"] = alpaca_client

    @property
    def alpaca_client(self) -> Any | None:
        return self._brokers.get("alpaca")

    def broker(self, provider: str) -> Any | None:
        return self._brokers.get(provider)

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
    def update_symbol(self, symbol: str, category: str, provider: str = "alpaca") -> int:
        normalized_symbol = str(symbol).upper().strip()
        broker = self.broker(provider)
        if broker is None:
            self.logger.debug("No broker registered for provider %s; skipping %s", provider, symbol)
            return 0
        last_timestamp = self.get_last_timestamp(normalized_symbol)
        first_download = last_timestamp is None
        start = market_data_start(first_download)
        if last_timestamp:
            start = parse_datetime(last_timestamp) + timedelta(days=1)
        if start >= utc_now():
            self.cleanup_old_records(normalized_symbol)
            return 0

        rows = broker.get_bars(symbol=normalized_symbol, category=category, start=start)
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
        self.logger.debug(
            "Updated %s with %s new bars from %s",
            normalized_symbol,
            inserted,
            provider,
        )
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

    def update_symbols(self, symbol_categories: dict[str, str | tuple[str, str] | dict[str, str]]) -> None:
        """Bulk update OHLCV for a set of monitored symbols.

        ``symbol_categories`` may map ``symbol -> category`` (legacy single-broker
        shape, defaults to Alpaca) or ``symbol -> {category, provider}`` /
        ``symbol -> (category, provider)`` for the multi-provider case.
        """

        for symbol, value in symbol_categories.items():
            category, provider = self._unpack_value(value)
            try:
                self.update_symbol(symbol, category, provider)
            except Exception:
                self.logger.exception(
                    "Market data update failed for %s (%s/%s)", symbol, provider, category
                )

    @staticmethod
    def _unpack_value(value: Any) -> tuple[str, str]:
        if isinstance(value, tuple) and len(value) == 2:
            return str(value[0]).upper(), str(value[1]).lower()
        if isinstance(value, dict):
            category = str(value.get("category") or "CRYPTO").upper()
            provider = str(value.get("provider") or "alpaca").lower()
            return category, provider
        return str(value).upper(), "alpaca"
