"""Read daily OHLCV bars from market_data.sqlite for backtest replay. Read-only."""

from __future__ import annotations

import sqlite3

from core.db import get_market_symbol_table


def load_daily_bars(market_db_path: str, symbol: str) -> list[dict]:
    """Return ascending-by-timestamp OHLCV bars for *symbol*; [] if unknown."""
    table = get_market_symbol_table(market_db_path, symbol)
    if not table:
        return []
    conn = sqlite3.connect(market_db_path)
    try:
        rows = conn.execute(
            f'SELECT timestamp, open, high, low, close, volume FROM "{table}" ORDER BY timestamp'
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "timestamp": r[0],
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
            "volume": float(r[5]),
        }
        for r in rows
    ]
