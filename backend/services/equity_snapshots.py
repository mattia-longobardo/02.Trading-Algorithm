"""Periodic capture of the broker's account equity into app.sqlite.

The dashboard's "andamento del saldo totale" chart needs a history of
balance values, but Alpaca only exposes the *current* state. We persist
a rolling time series in `account_equity_snapshots` so the chart has
something to draw across the timeframe selector.

Snapshots are written by a low-frequency scheduler job (default every
15 minutes); read endpoints layer FX conversion on top of the stored
broker-native value at request time.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from clients.alpaca_client import AlpacaClient
from core import fx
from core.app_db import app_cursor, app_fetch_all, app_fetch_one
from core.utils import AppConfig, isoformat_utc, parse_datetime, utc_now


def record_snapshot(
    config: AppConfig,
    alpaca_client: AlpacaClient,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    """Persist the current account equity (in broker-native currency).

    Returns the inserted row dict, or ``None`` if the broker call failed.
    """

    try:
        equity = float(alpaca_client.get_available_cash())
    except Exception:
        logger.exception("equity snapshot: failed to read account balance")
        return None
    if equity <= 0:
        logger.debug("equity snapshot: balance is zero, skipping")
        return None

    now_iso = isoformat_utc(utc_now()) or ""
    with app_cursor(config.db_app) as cursor:
        cursor.execute(
            "INSERT INTO account_equity_snapshots (recorded_at, equity, currency) VALUES (?, ?, ?)",
            (now_iso, equity, config.account_currency),
        )
    return {"recorded_at": now_iso, "equity": equity, "currency": config.account_currency}


def list_snapshots(
    db_path: str,
    *,
    from_dt: datetime | None,
    to_dt: datetime | None,
    granularity: str = "hourly",
) -> list[dict[str, Any]]:
    """Return raw (broker-native) snapshots within the requested window.

    The caller is responsible for FX conversion at the API edge so the
    same series can be presented in any display currency without
    rewriting history.
    """

    sql = ["SELECT recorded_at, equity, currency FROM account_equity_snapshots WHERE 1=1"]
    params: list[Any] = []
    if from_dt is not None:
        sql.append("AND recorded_at >= ?")
        params.append(isoformat_utc(from_dt))
    if to_dt is not None:
        sql.append("AND recorded_at < ?")
        params.append(isoformat_utc(to_dt))
    sql.append("ORDER BY recorded_at ASC")
    rows = app_fetch_all(db_path, " ".join(sql), tuple(params))

    if not rows:
        return []

    bucket_fmt = "%Y-%m-%dT%H:00:00+00:00" if granularity == "hourly" else "%Y-%m-%d"
    # Take the last value within each bucket — best snapshot of where the
    # balance sat at the end of the period.
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        recorded = parse_datetime(row["recorded_at"])
        if recorded is None:
            continue
        key = recorded.strftime(bucket_fmt)
        buckets[key] = {
            "t": key,
            "equity": float(row["equity"]),
            "currency": str(row["currency"]),
        }
    return [buckets[k] for k in sorted(buckets.keys())]


def latest_snapshot(db_path: str) -> dict[str, Any] | None:
    return app_fetch_one(
        db_path,
        "SELECT recorded_at, equity, currency FROM account_equity_snapshots ORDER BY recorded_at DESC LIMIT 1",
    )


def prune_old_snapshots(db_path: str, keep_days: int = 365) -> int:
    """Delete snapshots older than ``keep_days``. Returns rows removed."""

    cutoff = utc_now() - timedelta(days=keep_days)
    with app_cursor(db_path) as cursor:
        cursor.execute(
            "DELETE FROM account_equity_snapshots WHERE recorded_at < ?",
            (isoformat_utc(cutoff),),
        )
        return cursor.rowcount or 0


def equity_curve_for_api(
    db_path: str,
    *,
    from_dt: datetime | None,
    to_dt: datetime | None,
    granularity: str,
    target_currency: str,
) -> dict[str, Any]:
    """Build the dashboard payload: snapshots + FX-converted points."""

    raw = list_snapshots(db_path, from_dt=from_dt, to_dt=to_dt, granularity=granularity)
    points = []
    for r in raw:
        converted = fx.convert(r["equity"], r["currency"], target_currency)
        if converted is None:
            continue
        points.append({"t": r["t"], "equity": round(converted, 2)})
    return {
        "points": points,
        "currency": target_currency,
    }
