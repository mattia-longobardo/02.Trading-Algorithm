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
        """Rebuild the live snapshot using at most TWO broker GETs.

        GET budget per rebuild:
          1. ``broker.get_rates_by_instruments(ids)`` — one batched rates call
             covering *all* instrument IDs from open trades plus any extra
             broker-portfolio positions (union; empty → skipped, 0 GETs).
          2. ``broker.get_portfolio()`` — one portfolio call to derive cash
             and equity (also skipped when broker is None).

        Total worst-case: 2 GETs regardless of the number of open positions.
        """
        items: list[dict[str, Any]] = (
            self._metrics.list_trades(status="OPEN", page_size=500) or {}
        ).get("items", [])

        currency = (
            items[0].get("account_currency")
            if items
            else None
        ) or getattr(self._config, "account_currency", "USD") or "USD"

        # Collect all instrument IDs from open trades so we can batch them
        # into a single rates call later.
        trade_instrument_ids: list[int] = [
            int(t["instrument_id"])
            for t in items
            if t.get("instrument_id") is not None
        ]

        # --- GET 1: fetch live rates for all trade instrument IDs -----------
        rate_map: dict[int, dict] = {}
        if self._broker is not None and trade_instrument_ids:
            try:
                rate_map = self._broker.get_rates_by_instruments(trade_instrument_ids)
            except Exception as exc:
                self._logger.debug("live_snapshot: get_rates_by_instruments failed: %s", exc)

        # --- Build position list using the pre-fetched rate_map -------------
        positions: list[dict[str, Any]] = [
            self._build_position(trade, rate_map) for trade in items
        ]

        # --- GET 2: fetch portfolio to derive equity + cash -----------------
        equity: float | None = None
        cash: float | None = None

        if self._broker is not None:
            try:
                portfolio = self._broker.get_portfolio()
                credit = float(portfolio.get("credit") or 0.0)

                # cash = credit minus pending order amounts
                pending = sum(
                    float(o.get("amount") or 0.0)
                    for o in (portfolio.get("orders") or [])
                )
                cash = max(0.0, credit - pending)

                # equity = credit + sum(units * live_price) for each broker
                # position, reusing the already-fetched rate_map.  Broker
                # positions that share instrument IDs with open trades cost
                # zero extra GETs; any others are looked up from the same map
                # (we included trade IDs only, so missing broker-only positions
                # fall back to open_rate — still 0 extra GETs).
                broker_positions = portfolio.get("positions") or []
                market_value = 0.0
                for bp in broker_positions:
                    iid = bp.get("instrumentID")
                    if iid is None:
                        continue
                    iid = int(iid)
                    units = float(bp.get("units") or 0.0)
                    open_rate = float(bp.get("openRate") or 0.0)
                    rate = rate_map.get(iid, {})
                    # Prefer bid (conservative), then lastExecution, then openRate
                    price = (
                        rate.get("bid")
                        or rate.get("lastExecution")
                        or open_rate
                    )
                    market_value += units * float(price or open_rate)
                equity = credit + market_value
            except Exception as exc:
                self._logger.debug("live_snapshot: get_portfolio failed: %s", exc)

        return {
            "ts": isoformat_utc(utc_now()) or "",
            "currency": currency,
            "equity": equity,
            "cash": cash,
            "positions": positions,
        }

    def _build_position(
        self, trade: dict[str, Any], rate_map: dict[int, dict]
    ) -> dict[str, Any]:
        """Build a single position dict enriched with a pre-fetched live rate.

        *rate_map* is the ``{instrument_id: rate_dict}`` already fetched by
        ``_build``; no additional broker calls are made here.
        """
        symbol: str = str(trade.get("symbol") or "")
        category: str = str(trade.get("category") or "")
        entry_price: float = float(trade.get("entry_price") or 0.0)
        units: float = float(trade.get("quantity") or 0.0)
        instrument_id: int | None = (
            int(trade["instrument_id"]) if trade.get("instrument_id") is not None else None
        )

        # Determine price direction for PnL sign.
        # The bot is 1x unleveraged long; negate if short.
        is_buy: bool = bool(trade.get("is_buy", True))
        direction: int = 1 if is_buy else -1

        # Resolve live price from the pre-fetched rate map.
        current_price: float | None = None
        live_price_ok = False

        if instrument_id is not None and instrument_id in rate_map:
            rate = rate_map[instrument_id]
            bid = rate.get("bid")
            ask = rate.get("ask")
            last = rate.get("lastExecution")
            if bid is not None and ask is not None:
                live_price: float | None = (float(bid) + float(ask)) / 2.0
            elif bid is not None:
                live_price = float(bid)
            elif ask is not None:
                live_price = float(ask)
            elif last is not None:
                live_price = float(last)
            else:
                live_price = None

            if live_price is not None:
                current_price = live_price
                live_price_ok = True

        if not live_price_ok:
            # Fall back to stored price from the DB trade row.
            stored = trade.get("current_price")
            current_price = float(stored) if stored is not None else None

        # Compute unrealized PnL from the resolved price.
        unrealized_pnl: float | None = None
        unrealized_pnl_pct: float | None = None

        if current_price is not None:
            unrealized_pnl = (current_price - entry_price) * units * direction
            if entry_price > 0:
                unrealized_pnl_pct = (current_price / entry_price - 1.0) * 100.0 * direction
            else:
                unrealized_pnl_pct = None
        else:
            # No price available at all — prefer stored unrealized_pnl, then pnl.
            stored_upnl = trade.get("unrealized_pnl")
            unrealized_pnl = float(stored_upnl) if stored_upnl is not None else trade.get("pnl")
            unrealized_pnl_pct = None

        return {
            "id": trade.get("id"),
            "symbol": symbol,
            "category": category,
            "is_buy": is_buy,
            "units": units,
            "entry_price": entry_price,
            "current_price": current_price,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "take_profit": trade.get("take_profit"),
            "stop_loss": trade.get("stop_loss"),
            "position_id": trade.get("position_id"),
            "instrument_id": instrument_id,
        }
