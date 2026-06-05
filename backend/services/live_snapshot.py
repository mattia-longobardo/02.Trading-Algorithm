"""Rate-safe live snapshot cache for open positions + account state.

Aggregates eToro trade data from the DB (via MetricsService) with live
quotes from the broker client, returning a single dict that the API layer
can serve without worrying about rate limits.

The TTL gate (default 5 s) means the broker is queried at most once every
``ttl_seconds`` regardless of how many dashboard requests arrive. A
``threading.Lock`` makes it safe to share across threads.

The ``monotonic`` clock is injectable so tests can drive TTL behavior
deterministically without sleeping — following the same pattern as
``clients.etoro_rate_limiter.RateLimiter``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from core.utils import PROVIDER_ETORO, AppConfig, isoformat_utc, utc_now


class LiveSnapshotCache:
    """Cache that rebuilds the live snapshot at most once per TTL window.

    Parameters
    ----------
    metrics:
        A ``MetricsService``-like object exposing ``list_trades(**kwargs)``.
    brokers:
        Provider-keyed broker dict (``{PROVIDER_ETORO: <client>}``).
    config:
        Application config (used for fallback ``account_currency``).
    logger:
        Standard :class:`logging.Logger`.
    ttl_seconds:
        Minimum seconds between full rebuilds. Default 5 s.
    monotonic:
        Callable returning a monotonic float, injectable for testing.
        Defaults to ``time.monotonic``.
    """

    def __init__(
        self,
        metrics: Any,
        brokers: dict[str, Any],
        config: AppConfig,
        logger: Any,
        ttl_seconds: float = 5.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._metrics = metrics
        self._broker = brokers.get(PROVIDER_ETORO)
        self._config = config
        self._logger = logger
        self._ttl = float(ttl_seconds)
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._cached: dict[str, Any] | None = None
        self._cached_at: float = -float("inf")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_snapshot(self, *, force: bool = False) -> dict[str, Any]:
        """Return the current snapshot, rebuilding if necessary.

        Under the lock:
        - If a cached snapshot exists and was built within ``ttl_seconds``
          ago (and ``force`` is False), return the cached dict.
        - Otherwise rebuild, cache the result, and return it.
        """
        with self._lock:
            now = self._monotonic()
            if (
                not force
                and self._cached is not None
                and (now - self._cached_at) < self._ttl
            ):
                return self._cached
            snapshot = self._build()
            self._cached = snapshot
            self._cached_at = now
            return snapshot

    # ------------------------------------------------------------------
    # Build logic
    # ------------------------------------------------------------------

    def _build(self) -> dict[str, Any]:
        items: list[dict[str, Any]] = (
            self._metrics.list_trades(status="OPEN", page_size=500) or {}
        ).get("items", [])

        positions: list[dict[str, Any]] = []
        currency = (
            items[0].get("account_currency")
            if items
            else None
        ) or getattr(self._config, "account_currency", "USD") or "USD"

        for trade in items:
            pos = self._build_position(trade)
            positions.append(pos)

        equity: float | None = None
        cash: float | None = None

        if self._broker is not None:
            try:
                equity = float(self._broker.get_account_equity())
            except Exception as exc:
                self._logger.debug("live_snapshot: get_account_equity failed: %s", exc)

            try:
                cash = float(self._broker.get_available_cash())
            except Exception as exc:
                self._logger.debug("live_snapshot: get_available_cash failed: %s", exc)

        return {
            "ts": isoformat_utc(utc_now()) or "",
            "currency": currency,
            "equity": equity,
            "cash": cash,
            "positions": positions,
        }

    def _build_position(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Build a single position dict from a trade row, enriched with live quote."""
        symbol: str = str(trade.get("symbol") or "")
        category: str = str(trade.get("category") or "")
        entry_price: float = float(trade.get("entry_price") or 0.0)
        units: float = float(trade.get("quantity") or 0.0)

        # Determine price direction for PnL sign.
        # The bot is 1x unleveraged long; negate if short.
        is_buy: bool = bool(trade.get("is_buy", True))
        direction: int = 1 if is_buy else -1

        # Try to get a live quote; fall back to stored values on any error.
        current_price: float | None = None
        unrealized_pnl: float | None = None
        unrealized_pnl_pct: float | None = None

        live_price_ok = False
        if self._broker is not None:
            try:
                quote = self._broker.get_latest_quote(symbol, category)
                bid = quote.get("bid_price")
                ask = quote.get("ask_price")
                if bid is not None and ask is not None:
                    live_price = (float(bid) + float(ask)) / 2.0
                elif bid is not None:
                    live_price = float(bid)
                elif ask is not None:
                    live_price = float(ask)
                else:
                    live_price = None

                if live_price is not None:
                    current_price = live_price
                    live_price_ok = True
            except Exception as exc:
                self._logger.debug(
                    "live_snapshot: get_latest_quote(%s, %s) failed: %s",
                    symbol, category, exc,
                )

        if not live_price_ok:
            # Fall back to stored price from the DB trade row.
            stored = trade.get("current_price")
            current_price = float(stored) if stored is not None else None

        # Compute unrealized PnL from the resolved price.
        if current_price is not None:
            unrealized_pnl = (current_price - entry_price) * units * direction
            if entry_price > 0:
                unrealized_pnl_pct = (current_price / entry_price - 1.0) * 100.0 * direction
            else:
                unrealized_pnl_pct = None
        else:
            # No price available at all — fall back to stored pnl fields.
            stored_upnl = trade.get("unrealized_pnl")
            unrealized_pnl = float(stored_upnl) if stored_upnl is not None else trade.get("pnl")
            unrealized_pnl_pct = None

        # On quote error, also fall back to stored unrealized_pnl.
        if not live_price_ok and self._broker is not None:
            stored_upnl = trade.get("unrealized_pnl")
            if stored_upnl is not None:
                unrealized_pnl = float(stored_upnl)

        return {
            "id": trade.get("id"),
            "symbol": symbol,
            "category": category,
            "units": units,
            "entry_price": entry_price,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "take_profit": trade.get("take_profit"),
            "stop_loss": trade.get("stop_loss"),
            "position_id": trade.get("position_id"),
            "instrument_id": trade.get("instrument_id"),
        }
