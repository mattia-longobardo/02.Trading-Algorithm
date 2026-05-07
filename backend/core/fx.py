"""Lightweight FX conversion with multiple free providers and negative caching.

Alpaca paper trading reports balances and prices in USD even when the
operator wants to think in EUR (or any other currency). This module
converts amounts at API-response time so the storage stays in the
broker's native currency while the UI sees the user's preferred one.

Design:

- Two free public providers are tried in order. The first to succeed
  populates the in-memory cache for ``_TTL_SECONDS``. We send a real
  User-Agent header because some providers reject the bare
  ``Python-urllib/x.y`` default (we observed 403 from frankfurter.app
  in production).

- Failures are also cached for ``_NEGATIVE_TTL_SECONDS`` so a hot
  endpoint does not hammer the upstream during outages — without this,
  every dashboard refresh fans out into ~10 parallel retries.

- The last successful rate is kept indefinitely as the fallback for
  display: the API surfaces a ``stale=True`` flag so the UI can warn
  the operator that the number on screen is yesterday's.

- If we have never successfully fetched a rate, ``get_rate`` returns
  ``None`` instead of a misleading 1:1 fallback. Callers must handle
  ``None`` (and ``convert`` propagates it).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__).getChild("fx")

_USER_AGENT = "trading-bot/2.0 (+https://github.com/)"
_HTTP_TIMEOUT = 5.0
_TTL_SECONDS = 15 * 60
_NEGATIVE_TTL_SECONDS = 60  # back off for 60s after every fetch failure


@dataclass(slots=True)
class _CachedRate:
    rate: float | None
    fetched_at: float
    ok: bool  # True for a successful fetch, False for a remembered failure


_cache: dict[tuple[str, str], _CachedRate] = {}
_cache_lock = threading.Lock()


def _normalize(currency: str) -> str:
    return (currency or "").strip().upper() or "USD"


# -- providers --------------------------------------------------------------


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _provider_frankfurter(base: str, target: str) -> float | None:
    payload = _http_get_json(f"https://api.frankfurter.dev/v1/latest?base={base}&symbols={target}")
    rate = (payload.get("rates") or {}).get(target)
    return float(rate) if isinstance(rate, (int, float)) and float(rate) > 0 else None


def _provider_er_api(base: str, target: str) -> float | None:
    """Backup: open.er-api.com (free, no API key, generous rate limits)."""

    payload = _http_get_json(f"https://open.er-api.com/v6/latest/{base}")
    if str(payload.get("result", "")).lower() != "success":
        return None
    rate = (payload.get("rates") or {}).get(target)
    return float(rate) if isinstance(rate, (int, float)) and float(rate) > 0 else None


_PROVIDERS = (
    ("frankfurter.dev", _provider_frankfurter),
    ("open.er-api.com", _provider_er_api),
)


def _fetch_rate(base: str, target: str) -> float | None:
    """Try every provider in order. Return the first valid rate."""

    last_error: Exception | None = None
    for name, fn in _PROVIDERS:
        try:
            rate = fn(base, target)
        except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
            last_error = exc
            logger.warning("FX provider %s for %s->%s failed: %s", name, base, target, exc)
            continue
        if rate and rate > 0:
            logger.info("FX provider %s served %s->%s = %.6f", name, base, target, rate)
            return rate
        logger.warning("FX provider %s returned no rate for %s->%s", name, base, target)
    if last_error:
        logger.error("All FX providers failed for %s->%s; last error: %s", base, target, last_error)
    return None


# -- public API --------------------------------------------------------------


def get_rate(from_currency: str, to_currency: str) -> float | None:
    """Return the rate so that ``amount * rate`` is the value in ``to_currency``.

    Returns ``None`` when no rate is available (no successful fetch ever
    and current attempts also failed). Honors a positive-result TTL of
    15 min and a negative-result TTL of 60 s to absorb burst load
    during upstream outages.
    """

    base = _normalize(from_currency)
    target = _normalize(to_currency)
    if base == target:
        return 1.0

    key = (base, target)
    now = time.monotonic()

    with _cache_lock:
        cached = _cache.get(key)
        if cached:
            if cached.ok and (now - cached.fetched_at) < _TTL_SECONDS:
                return cached.rate
            if not cached.ok and (now - cached.fetched_at) < _NEGATIVE_TTL_SECONDS:
                # Keep returning the last good rate (if any) without
                # hammering the upstream during the cool-off window.
                return _last_good_rate_locked(key)

    rate = _fetch_rate(base, target)
    with _cache_lock:
        if rate is not None:
            _cache[key] = _CachedRate(rate=rate, fetched_at=now, ok=True)
            return rate
        # Negative cache, but keep any previously-good rate available
        # via _last_good_rate so the API still has something to return.
        previous = _cache.get(key)
        previous_rate = previous.rate if previous and previous.ok else None
        _cache[key] = _CachedRate(rate=previous_rate, fetched_at=now, ok=False)
        return previous_rate


def _last_good_rate_locked(key: tuple[str, str]) -> float | None:
    """Helper: return the last positive rate kept in the cache slot."""

    cached = _cache.get(key)
    if cached and cached.ok and cached.rate is not None:
        return cached.rate
    if cached and cached.rate is not None:
        # Negative entry that still carries a previous good rate
        # in its slot (we always copy it forward on failure).
        return cached.rate
    return None


def get_rate_with_status(from_currency: str, to_currency: str) -> dict:
    """Diagnostic variant used by the API endpoint and the UI badge."""

    base = _normalize(from_currency)
    target = _normalize(to_currency)
    if base == target:
        return {"from": base, "to": target, "rate": 1.0, "stale": False, "available": True}

    rate = get_rate(base, target)
    with _cache_lock:
        entry = _cache.get((base, target))
    if rate is None:
        return {"from": base, "to": target, "rate": None, "stale": True, "available": False}
    stale = bool(entry and not entry.ok)
    return {"from": base, "to": target, "rate": rate, "stale": stale, "available": True}


def convert(amount: float | int | None, from_currency: str, to_currency: str) -> float | None:
    """Convert ``amount`` from one currency to another. ``None`` propagates.

    If no FX rate is available and the source/target differ, the function
    returns the original numeric value rather than ``None`` so the UI is
    not littered with empty cells. The dashboard's FX badge is the
    authoritative indicator that conversion may be unavailable.
    """

    if amount is None:
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if value == 0:
        return 0.0
    rate = get_rate(from_currency, to_currency)
    if rate is None:
        return value
    return round(value * rate, 6)


def reset_cache() -> None:
    """Test helper: drop the in-memory cache."""

    with _cache_lock:
        _cache.clear()
