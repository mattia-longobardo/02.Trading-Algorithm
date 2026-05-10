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
        equity = float(alpaca_client.get_account_equity())
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

    # Each granularity floors the timestamp to the start of its bucket so
    # the last snapshot inside the bucket "wins" — a stable end-of-period
    # value the chart can plot without averaging across noise.
    norm = (granularity or "").strip().lower()
    if norm in ("daily", "1d"):
        floor_minutes = 24 * 60
    elif norm == "4h":
        floor_minutes = 4 * 60
    elif norm in ("hourly", "1h"):
        floor_minutes = 60
    elif norm == "30m":
        floor_minutes = 30
    elif norm == "15m":
        floor_minutes = 15
    else:
        floor_minutes = 60

    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        recorded = parse_datetime(row["recorded_at"])
        if recorded is None:
            continue
        if floor_minutes >= 24 * 60:
            bucket_dt = recorded.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            total_min = recorded.hour * 60 + recorded.minute
            floored = (total_min // floor_minutes) * floor_minutes
            bucket_dt = recorded.replace(
                hour=floored // 60, minute=floored % 60, second=0, microsecond=0
            )
        key = bucket_dt.strftime("%Y-%m-%dT%H:%M:00+00:00")
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
