"""SQLite initialization and repository helpers."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS ohlcv (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    UNIQUE(symbol, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_ts ON ohlcv(symbol, timestamp);
"""

TRADES_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('STOCK', 'CRYPTO')),
    direction TEXT NOT NULL DEFAULT 'LONG',
    status TEXT NOT NULL CHECK(status IN ('PENDING', 'OPEN', 'CLOSED')),
    entry_price REAL NOT NULL,
    target_entry_price REAL,
    quantity REAL NOT NULL,
    allocated_capital REAL NOT NULL,
    take_profit REAL,
    stop_loss REAL,
    trailing_stop_distance REAL,
    high_water_mark REAL,
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
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_status ON trades(symbol, status);
CREATE INDEX IF NOT EXISTS idx_trades_category_status ON trades(category, status);
"""

TRADE_OPTIONAL_COLUMNS: dict[str, str] = {
    "broker_protection_type": "TEXT NOT NULL DEFAULT 'SCRIPT'",
    "protection_order_id": "TEXT",
    "protection_client_order_id": "TEXT",
    "target_entry_price": "REAL",
    "high_water_mark": "REAL",
    "trailing_stop_price": "REAL",
    "pending_close_reason": "TEXT",
    "exit_order_id": "TEXT",
    "exit_client_order_id": "TEXT",
    "exit_requested_at": "TEXT",
}


def _connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA foreign_keys=ON;")
    return connection


def _ensure_optional_trade_columns(connection: sqlite3.Connection) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(trades)").fetchall()
    }
    for column, definition in TRADE_OPTIONAL_COLUMNS.items():
        if column in existing_columns:
            continue
        connection.execute(f"ALTER TABLE trades ADD COLUMN {column} {definition}")


def initialize_databases(market_db_path: str, trades_db_path: str) -> None:
    """Create all SQLite tables if missing."""

    with _connect(market_db_path) as market_conn:
        market_conn.executescript(MARKET_SCHEMA)
        market_conn.commit()
    with _connect(trades_db_path) as trade_conn:
        trade_conn.executescript(TRADES_SCHEMA)
        _ensure_optional_trade_columns(trade_conn)
        trade_conn.commit()


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

    with _connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def fetch_one(db_path: str, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    """Return the first row for a query as a dictionary."""

    with _connect(db_path) as connection:
        row = connection.execute(query, params).fetchone()
    return dict(row) if row else None
