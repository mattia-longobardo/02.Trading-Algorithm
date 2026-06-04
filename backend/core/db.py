"""SQLite initialization and repository helpers."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

TRADE_STATUS_VALUES = "'PENDING', 'OPEN', 'CLOSED', 'CANCELLED'"

MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_symbols (
    symbol TEXT PRIMARY KEY,
    table_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

INSTRUMENT_MAP_SCHEMA = """
CREATE TABLE IF NOT EXISTS instrument_map (
    symbol TEXT PRIMARY KEY,
    instrument_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    display_name TEXT,
    tradable INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_instrument_map_id ON instrument_map(instrument_id);
"""

TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('STOCK', 'CRYPTO')),
    direction TEXT NOT NULL DEFAULT 'LONG',
    status TEXT NOT NULL CHECK(status IN (""" + TRADE_STATUS_VALUES + """)),
    entry_price REAL NOT NULL,
    target_entry_price REAL,
    quantity REAL NOT NULL,
    allocated_capital REAL NOT NULL,
    take_profit REAL,
    trailing_take_profit_distance REAL,
    trailing_take_profit_activation_pct REAL,
    stop_loss REAL,
    trailing_stop_distance REAL,
    high_water_mark REAL,
    trailing_take_profit_price REAL,
    trailing_stop_price REAL,
    open_timestamp TEXT,
    close_timestamp TEXT,
    close_price REAL,
    current_price REAL,
    pnl REAL,
    close_reason TEXT,
    pending_close_reason TEXT,
    alpaca_order_id TEXT,
    client_order_id TEXT,
    exit_order_id TEXT,
    exit_client_order_id TEXT,
    exit_requested_at TEXT,
    reasoning TEXT,
    confidence REAL,
    provider TEXT NOT NULL DEFAULT 'alpaca',
    account_currency TEXT NOT NULL DEFAULT 'USD',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_status ON trades(symbol, status);
CREATE INDEX IF NOT EXISTS idx_trades_category_status ON trades(category, status);
CREATE INDEX IF NOT EXISTS idx_trades_provider_status ON trades(provider, status);
"""

TRADE_OPTIONAL_COLUMNS: dict[str, str] = {
    "broker_protection_type": "TEXT NOT NULL DEFAULT 'SCRIPT'",
    "protection_order_id": "TEXT",
    "protection_client_order_id": "TEXT",
    "target_entry_price": "REAL",
    "high_water_mark": "REAL",
    "trailing_take_profit_distance": "REAL",
    "trailing_take_profit_activation_pct": "REAL",
    "trailing_take_profit_price": "REAL",
    "trailing_stop_price": "REAL",
    "pending_close_reason": "TEXT",
    "exit_order_id": "TEXT",
    "exit_client_order_id": "TEXT",
    "exit_requested_at": "TEXT",
    "trade_score": "REAL",
    "provider": "TEXT NOT NULL DEFAULT 'alpaca'",
    "account_currency": "TEXT NOT NULL DEFAULT 'USD'",
}

SYMBOL_TABLE_PREFIX = "ohlcv_"


def _connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA foreign_keys=ON;")
    return connection


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _market_table_name_for_symbol(symbol: str) -> str:
    normalized_symbol = str(symbol).upper().strip()
    slug = re.sub(r"[^A-Z0-9]+", "_", normalized_symbol).strip("_") or "SYMBOL"
    digest = hashlib.sha1(normalized_symbol.encode("utf-8")).hexdigest()[:10]
    return f"{SYMBOL_TABLE_PREFIX}{slug}_{digest}"


def _create_symbol_table(connection: sqlite3.Connection, table_name: str) -> None:
    connection.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_quote_identifier(table_name)} (
            timestamp TEXT PRIMARY KEY,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL
        )
        """
    ).close()


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    cursor = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    )
    try:
        return cursor.fetchone() is not None
    finally:
        cursor.close()


def ensure_market_symbol_table(connection: sqlite3.Connection, symbol: str) -> str:
    normalized_symbol = str(symbol).upper().strip()
    cursor = connection.execute("SELECT table_name FROM market_symbols WHERE symbol = ?", (normalized_symbol,))
    try:
        row = cursor.fetchone()
    finally:
        cursor.close()
    if row:
        table_name = str(row["table_name"])
    else:
        table_name = _market_table_name_for_symbol(normalized_symbol)
        connection.execute(
            "INSERT INTO market_symbols(symbol, table_name) VALUES (?, ?)",
            (normalized_symbol, table_name),
        ).close()
    _create_symbol_table(connection, table_name)
    return table_name


def get_market_symbol_table(db_path: str, symbol: str) -> str | None:
    normalized_symbol = str(symbol).upper().strip()
    connection = _connect(db_path)
    try:
        cursor = connection.execute("SELECT table_name FROM market_symbols WHERE symbol = ?", (normalized_symbol,))
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    finally:
        connection.close()
    return str(row["table_name"]) if row else None


def list_market_symbols(db_path: str) -> list[dict[str, Any]]:
    return fetch_all(db_path, "SELECT symbol, table_name FROM market_symbols ORDER BY symbol")


def _migrate_legacy_ohlcv_table(connection: sqlite3.Connection) -> None:
    if not _table_exists(connection, "ohlcv"):
        return

    cursor = connection.execute("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol")
    try:
        symbols = [str(row["symbol"]).upper().strip() for row in cursor.fetchall()]
    finally:
        cursor.close()

    for symbol in symbols:
        table_name = ensure_market_symbol_table(connection, symbol)
        connection.execute(
            f"""
            INSERT OR IGNORE INTO {_quote_identifier(table_name)} (timestamp, open, high, low, close, volume)
            SELECT timestamp, open, high, low, close, volume
            FROM ohlcv
            WHERE symbol = ?
            ORDER BY timestamp
            """,
            (symbol,),
        ).close()

    connection.execute("DROP TABLE ohlcv").close()


def _ensure_optional_trade_columns(connection: sqlite3.Connection) -> None:
    cursor = connection.execute("PRAGMA table_info(trades)")
    try:
        existing_columns = {row["name"] for row in cursor.fetchall()}
    finally:
        cursor.close()
    for column, definition in TRADE_OPTIONAL_COLUMNS.items():
        if column in existing_columns:
            continue
        alter_cursor = connection.execute(f"ALTER TABLE trades ADD COLUMN {column} {definition}")
        alter_cursor.close()


def initialize_databases(market_db_path: str, trades_db_path: str) -> None:
    """Create all SQLite tables if missing."""

    market_conn = _connect(market_db_path)
    try:
        market_conn.executescript(MARKET_SCHEMA)
        market_conn.executescript(INSTRUMENT_MAP_SCHEMA)
        _migrate_legacy_ohlcv_table(market_conn)
        market_conn.commit()
    finally:
        market_conn.close()

    trade_conn = _connect(trades_db_path)
    try:
        trade_conn.executescript(TRADES_SCHEMA)
        _ensure_optional_trade_columns(trade_conn)
        trade_conn.commit()
    finally:
        trade_conn.close()


@contextmanager
def db_cursor(db_path: str) -> Iterator[sqlite3.Cursor]:
    """Yield a SQLite cursor with automatic commit/rollback."""

    connection = _connect(db_path)
    cursor = connection.cursor()
    try:
        yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def fetch_all(db_path: str, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Return all rows for a query as dictionaries."""

    connection = _connect(db_path)
    try:
        cursor = connection.execute(query, params)
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def fetch_one(db_path: str, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Return the first row for a query as a dictionary."""

    connection = _connect(db_path)
    try:
        cursor = connection.execute(query, params)
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    finally:
        connection.close()
    return dict(row) if row else None


def upsert_instrument_mapping(
    db_path: str,
    symbol: str,
    instrument_id: int,
    category: str,
    display_name: str | None,
    tradable: bool,
) -> None:
    """Insert or update a symbol → eToro instrumentId mapping."""

    normalized = str(symbol).upper().strip()
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO instrument_map (symbol, instrument_id, category, display_name, tradable, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(symbol) DO UPDATE SET
                instrument_id = excluded.instrument_id,
                category = excluded.category,
                display_name = excluded.display_name,
                tradable = excluded.tradable,
                updated_at = CURRENT_TIMESTAMP
            """,
            (normalized, int(instrument_id), str(category).upper().strip(), display_name, 1 if tradable else 0),
        )


def get_instrument_mapping(db_path: str, symbol: str) -> dict[str, Any] | None:
    """Return the cached mapping row for a symbol, or None."""

    normalized = str(symbol).upper().strip()
    return fetch_one(
        db_path,
        "SELECT symbol, instrument_id, category, display_name, tradable FROM instrument_map WHERE symbol = ?",
        (normalized,),
    )
