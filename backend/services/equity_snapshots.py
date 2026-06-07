"""Periodic capture of broker account equity (per provider) into app.sqlite.

The dashboard's "andamento del saldo totale" chart needs a history of
balance values, but brokers only expose the *current* state. We persist a
rolling time series in ``account_equity_snapshots`` so the chart can plot
across the timeframe selector.

Multi-provider note: each broker is sampled independently, with its own
broker-native currency. ``equity_curve_for_api`` then sums the
per-provider series at each bucket so the dashboard sees a single
aggregated equity line in the user's display currency.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from core import fx
from core.app_db import app_cursor, app_fetch_all, app_fetch_one
from core.utils import (
    PROVIDER_ETORO,
    AppConfig,
    isoformat_utc,
    parse_datetime,
    utc_now,
)


def record_snapshot(
    config: AppConfig,
    broker_client: Any,
    logger: logging.Logger,
    provider: str = PROVIDER_ETORO,
) -> dict[str, Any] | None:
    """Persist the current account equity (in broker-native currency).

    Returns the inserted row dict, or ``None`` if the broker call failed.
    """

    if broker_client is None:
        return None
    try:
        equity = float(broker_client.get_account_equity())
    except Exception:
        logger.exception("equity snapshot: failed to read %s account balance", provider)
        return None
    if equity <= 0:
        logger.debug("equity snapshot: %s balance is zero, skipping", provider)
        return None

    currency = config.provider_account_currency(provider)
    now_iso = isoformat_utc(utc_now()) or ""
    with app_cursor(config.db_app) as cursor:
        cursor.execute(
            "INSERT INTO account_equity_snapshots (recorded_at, equity, currency, provider) VALUES (?, ?, ?, ?)",
            (now_iso, equity, currency, provider),
        )
    return {
        "recorded_at": now_iso,
        "equity": equity,
        "currency": currency,
        "provider": provider,
    }


def record_snapshots_all(
    config: AppConfig,
    brokers: Mapping[str, Any],
    logger: logging.Logger,
) -> dict[str, dict[str, Any] | None]:
    """Snapshot every active provider in one call. Used by the scheduler."""

    out: dict[str, dict[str, Any] | None] = {}
    for provider in config.active_providers():
        broker = brokers.get(provider)
        if broker is None:
            continue
        try:
            out[provider] = record_snapshot(config, broker, logger, provider=provider)
        except Exception:
            logger.exception("equity snapshot: provider %s failed", provider)
            out[provider] = None
    return out


def list_snapshots(
    db_path: str,
    *,
    from_dt: datetime | None,
    to_dt: datetime | None,
    granularity: str = "hourly",
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """Return raw (broker-native) snapshots within the requested window.

    The caller is responsible for FX conversion at the API edge so the
    same series can be presented in any display currency without
    rewriting history. Pass ``provider`` to constrain the result to a
    single broker.
    """

    sql = ["SELECT recorded_at, equity, currency, provider FROM account_equity_snapshots WHERE 1=1"]
    params: list[Any] = []
    if provider:
        sql.append("AND provider = ?")
        params.append(provider)
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

    # Per-provider buckets are kept independent so the API view can decide
    # whether to sum them or surface a single provider's line.
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
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
        prov = str(row.get("provider") or PROVIDER_ETORO)
        buckets[(key, prov)] = {
            "t": key,
            "equity": float(row["equity"]),
            "currency": str(row["currency"]),
            "provider": prov,
        }
    return [buckets[bucket_key] for bucket_key in sorted(buckets.keys())]


def latest_snapshot(db_path: str, provider: str | None = None) -> dict[str, Any] | None:
    if provider:
        return app_fetch_one(
            db_path,
            "SELECT recorded_at, equity, currency, provider FROM account_equity_snapshots WHERE provider = ? ORDER BY recorded_at DESC LIMIT 1",
            (provider,),
        )
    return app_fetch_one(
        db_path,
        "SELECT recorded_at, equity, currency, provider FROM account_equity_snapshots ORDER BY recorded_at DESC LIMIT 1",
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
    provider: str | None = None,
) -> dict[str, Any]:
    """Build the dashboard payload: snapshots aggregated across providers.

    For each timestamp bucket we sum the per-provider equity values after
    converting them to ``target_currency``. This lets the user drop in a
    second broker without ever changing the dashboard contract.
    """

    raw = list_snapshots(
        db_path,
        from_dt=from_dt,
        to_dt=to_dt,
        granularity=granularity,
        provider=provider,
    )
    aggregated: dict[str, float] = {}
    contributing_providers_per_bucket: dict[str, set[str]] = {}
    for row in raw:
        converted = fx.convert(row["equity"], row["currency"], target_currency)
        if converted is None:
            continue
        bucket_t = row["t"]
        aggregated[bucket_t] = round(aggregated.get(bucket_t, 0.0) + float(converted), 2)
        contributing_providers_per_bucket.setdefault(bucket_t, set()).add(row["provider"])
    points = [
        {"t": bucket_t, "equity": value} for bucket_t, value in sorted(aggregated.items())
    ]
    return {
        "points": points,
        "currency": target_currency,
        "providers_per_bucket": {
            bucket_t: sorted(provs)
            for bucket_t, provs in contributing_providers_per_bucket.items()
        },
    }
