"""Read-only analytics over the trades database.

Used by the dashboard endpoints (KPIs, equity curve, PnL-by-symbol,
allocation, return distribution). Closed trades drive realized PnL;
open trades drive unrealized PnL using the current price kept up to
date by the script-managed lifecycle every minute.

Multi-provider aware: each trade carries its own ``provider`` and
``account_currency``. Monetary fields are converted to the user's
display currency at API edge using the trade's own native currency,
so the dashboard reports every trade in the same display number.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from core import fx
from core.db import fetch_all
from core.utils import (
    PROVIDER_ETORO,
    AppConfig,
    parse_datetime,
    utc_now,
)


# Trade columns whose stored value is a *monetary amount* (price, capital,
# PnL) in the broker's account currency. They get converted to the display
# currency at the API edge. Quantity / percentage / score columns are not
# in this set because they are not currency-denominated.
_MONETARY_TRADE_FIELDS: tuple[str, ...] = (
    "entry_price",
    "target_entry_price",
    "take_profit",
    "trailing_take_profit_distance",
    "stop_loss",
    "trailing_stop_distance",
    "trailing_take_profit_price",
    "trailing_stop_price",
    "high_water_mark",
    "current_price",
    "close_price",
    "allocated_capital",
    "pnl",
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_close_dt(row: dict[str, Any]) -> datetime | None:
    return parse_datetime(row.get("close_timestamp"))


def _trade_open_dt(row: dict[str, Any]) -> datetime | None:
    return parse_datetime(row.get("open_timestamp")) or parse_datetime(row.get("created_at"))


def _within(row: dict[str, Any], from_dt: datetime | None, to_dt: datetime | None) -> bool:
    """A closed trade is within [from, to) iff its close timestamp falls there."""

    close_dt = _trade_close_dt(row)
    if close_dt is None:
        return False
    if from_dt is not None and close_dt < from_dt:
        return False
    if to_dt is not None and close_dt >= to_dt:
        return False
    return True


def _unrealized_pnl(row: dict[str, Any]) -> float:
    """Best-effort unrealized PnL for an OPEN trade using current_price."""

    if row.get("status") != "OPEN":
        return 0.0
    entry = _safe_float(row.get("entry_price"))
    current = _safe_float(row.get("current_price"))
    qty = _safe_float(row.get("quantity"))
    if entry <= 0 or current <= 0 or qty <= 0:
        return 0.0
    return (current - entry) * qty


def _realized_pnl(row: dict[str, Any]) -> float:
    return _safe_float(row.get("pnl"))


class MetricsService:
    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        broker_clients: Mapping[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.logger = logger.getChild("metrics")
        self._brokers: dict[str, Any] = dict(broker_clients) if isinstance(broker_clients, Mapping) else {}

    @property
    def brokers(self) -> dict[str, Any]:
        return self._brokers

    # -- FX helpers -------------------------------------------------------

    def _fx_convert(self, value: Any, source_currency: str | None = None) -> float | None:
        """Convert a monetary amount to the operator's display currency.

        ``source_currency`` lets the caller specify the trade's own native
        currency (different brokers report in different currencies). If
        omitted we fall back to the global account_currency for backwards
        compatibility.
        """

        if value is None:
            return None
        try:
            num = float(value)
        except (TypeError, ValueError):
            return None
        source = source_currency or self.config.account_currency
        return fx.convert(num, source, self.config.currency)

    def _fx_round(self, value: Any, decimals: int = 2, source_currency: str | None = None) -> float:
        converted = self._fx_convert(value, source_currency=source_currency)
        if converted is None:
            return 0.0
        return round(converted, decimals)

    def _trade_native_currency(self, trade: dict[str, Any]) -> str:
        currency = str(trade.get("account_currency") or "").strip().upper()
        if currency:
            return currency
        provider = str(trade.get("provider") or PROVIDER_ETORO)
        return self.config.provider_account_currency(provider)

    # -- raw trade access --------------------------------------------------

    def all_trades(self) -> list[dict[str, Any]]:
        return fetch_all(self.config.db_trades, "SELECT * FROM trades ORDER BY created_at")

    def list_trades(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        symbol: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
        sort: str = "-created_at",
    ) -> dict[str, Any]:
        rows = self.all_trades()
        if status:
            wanted = {s.strip().upper() for s in status.split(",") if s.strip()}
            rows = [r for r in rows if str(r.get("status")) in wanted]
        if category:
            wanted_cat = {c.strip().upper() for c in category.split(",") if c.strip()}
            rows = [r for r in rows if str(r.get("category")) in wanted_cat]
        if symbol:
            sym = symbol.strip().upper()
            rows = [r for r in rows if str(r.get("symbol", "")).upper() == sym]
        if from_dt or to_dt:
            def _matches(r: dict[str, Any]) -> bool:
                # Filter by either close_timestamp (preferred) or created_at
                # so that PENDING/OPEN trades created in window are also kept.
                close_dt = _trade_close_dt(r)
                ref_dt = close_dt if close_dt is not None else _trade_open_dt(r)
                if ref_dt is None:
                    return False
                if from_dt is not None and ref_dt < from_dt:
                    return False
                if to_dt is not None and ref_dt >= to_dt:
                    return False
                return True

            rows = [r for r in rows if _matches(r)]

        sort_field = sort.lstrip("-+")
        descending = sort.startswith("-")
        rows.sort(
            key=lambda r: (r.get(sort_field) is None, r.get(sort_field)),
            reverse=descending,
        )

        total = len(rows)
        page = max(1, int(page))
        page_size = max(1, min(int(page_size), 500))
        start = (page - 1) * page_size
        page_rows = rows[start : start + page_size]
        decorated = [self._decorate(r) for r in page_rows]
        return {"items": decorated, "total": total, "page": page, "page_size": page_size}

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        native = self._trade_native_currency(row)
        # Compute realized / unrealized PnL on the broker-native values
        # FIRST, then convert everything monetary into the display currency.
        realized_native = _realized_pnl(row)
        unrealized_native = _unrealized_pnl(row)
        out["realized_pnl"] = self._fx_convert(realized_native, source_currency=native) or 0.0
        out["unrealized_pnl"] = self._fx_convert(unrealized_native, source_currency=native) or 0.0
        for field in _MONETARY_TRADE_FIELDS:
            if field in out and out[field] is not None:
                converted = self._fx_convert(out[field], source_currency=native)
                if converted is not None:
                    out[field] = converted
        # Surface the originating provider so the UI can group / badge.
        out.setdefault("provider", str(row.get("provider") or PROVIDER_ETORO))
        out.setdefault("account_currency", native)
        return out

    def get_trade(self, trade_id: int) -> dict[str, Any] | None:
        rows = fetch_all(self.config.db_trades, "SELECT * FROM trades WHERE id = ?", (int(trade_id),))
        return self._decorate(rows[0]) if rows else None

    # -- account ----------------------------------------------------------

    def account_equity(self) -> float:
        """Sum of broker-native equity across providers, expressed in display currency.

        Each provider's native value is FX-converted to the user's
        display currency *before* summation (different brokers can report
        in different currencies).
        """

        total = 0.0
        for provider, broker in self._brokers.items():
            if broker is None:
                continue
            try:
                native = float(broker.get_account_equity())
            except Exception:
                self.logger.exception("Failed to fetch %s account equity", provider)
                continue
            converted = self._fx_convert(
                native, source_currency=self.config.provider_account_currency(provider)
            )
            if converted is not None:
                total += float(converted)
        return total

    def account_equity_display(self) -> float:
        """Equity (already converted) rounded for the UI."""

        return round(self.account_equity(), 2)

    def account_equity_breakdown(self) -> list[dict[str, Any]]:
        """Per-provider equity values, in both native and display currency."""

        rows: list[dict[str, Any]] = []
        for provider, broker in self._brokers.items():
            if broker is None:
                continue
            native_currency = self.config.provider_account_currency(provider)
            try:
                native_value = float(broker.get_account_equity())
            except Exception:
                self.logger.exception("Failed to fetch %s account equity", provider)
                continue
            converted = self._fx_convert(native_value, source_currency=native_currency) or 0.0
            rows.append(
                {
                    "provider": provider,
                    "equity_native": round(native_value, 8),
                    "native_currency": native_currency,
                    "equity_display": round(converted, 2),
                    "display_currency": self.config.currency,
                }
            )
        return rows

    # -- KPIs -------------------------------------------------------------

    def _pnl_in_display(self, row: dict[str, Any]) -> float:
        native = self._trade_native_currency(row)
        converted = self._fx_convert(_realized_pnl(row), source_currency=native)
        return float(converted or 0.0)

    def compute_metrics(
        self,
        from_dt: datetime | None,
        to_dt: datetime | None,
    ) -> dict[str, Any]:
        rows = self.all_trades()
        non_cancelled = [r for r in rows if r.get("status") != "CANCELLED"]
        closed_in_period = [r for r in non_cancelled if _within(r, from_dt, to_dt)]

        # PnL values, converted to display currency (each trade by its own
        # native currency) so multi-broker portfolios sum correctly.
        pnls_display = [self._pnl_in_display(r) for r in closed_in_period]
        allocated_display = [
            float(self._fx_convert(_safe_float(r.get("allocated_capital")), source_currency=self._trade_native_currency(r)) or 0.0)
            for r in closed_in_period
        ]
        wins = [v for v in pnls_display if v > 0]
        losses = [v for v in pnls_display if v < 0]
        n_trades = len(closed_in_period)
        n_open = sum(1 for r in non_cancelled if r.get("status") == "OPEN")
        n_pending = sum(1 for r in non_cancelled if r.get("status") == "PENDING")

        total_pnl_abs = round(sum(pnls_display), 2)
        allocated_sum = sum(allocated_display)
        total_pnl_pct = round((total_pnl_abs / allocated_sum) * 100.0, 2) if allocated_sum > 0 else 0.0

        win_rate = round(len(wins) / n_trades, 4) if n_trades else 0.0
        avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
        avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0
        sum_wins = sum(wins)
        sum_losses_abs = abs(sum(losses))
        if sum_losses_abs > 0:
            profit_factor = round(sum_wins / sum_losses_abs, 4)
        elif sum_wins > 0:
            profit_factor = float("inf")
        else:
            profit_factor = 0.0
        if not math.isfinite(profit_factor):
            profit_factor = 9999.0

        equity_points = self._equity_curve_points_display(closed_in_period)
        max_drawdown_display = self._max_drawdown(equity_points)
        sharpe = self._sharpe_from_curve(equity_points)

        return {
            "total_pnl_abs": total_pnl_abs,
            "total_pnl_pct": total_pnl_pct,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "max_drawdown": round(max_drawdown_display, 2),
            "sharpe": round(sharpe, 4),
            "n_trades": n_trades,
            "n_open": n_open,
            "n_pending": n_pending,
            "account_equity": self.account_equity_display(),
            "currency": self.config.currency,
            "account_currency": self.config.account_currency,
            "providers": [
                p
                for p, broker in self._brokers.items()
                if broker is not None
            ],
        }

    def _equity_curve_points(self, closed: list[dict[str, Any]]) -> list[tuple[datetime, float]]:
        points: list[tuple[datetime, float]] = []
        running = 0.0
        for row in sorted(closed, key=lambda r: _trade_close_dt(r) or datetime.min.replace(tzinfo=UTC)):
            close_dt = _trade_close_dt(row)
            if close_dt is None:
                continue
            running += _realized_pnl(row)
            points.append((close_dt, round(running, 2)))
        return points

    def _equity_curve_points_display(self, closed: list[dict[str, Any]]) -> list[tuple[datetime, float]]:
        """Same as :meth:`_equity_curve_points` but in the display currency.

        Each trade's PnL is converted by its own native currency before being
        added to the running total, so multi-broker portfolios are coherent.
        """

        points: list[tuple[datetime, float]] = []
        running = 0.0
        for row in sorted(closed, key=lambda r: _trade_close_dt(r) or datetime.min.replace(tzinfo=UTC)):
            close_dt = _trade_close_dt(row)
            if close_dt is None:
                continue
            running += self._pnl_in_display(row)
            points.append((close_dt, round(running, 2)))
        return points

    @staticmethod
    def _max_drawdown(points: list[tuple[datetime, float]]) -> float:
        if not points:
            return 0.0
        peak = points[0][1]
        max_dd = 0.0
        for _, equity in points:
            peak = max(peak, equity)
            dd = peak - equity
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @staticmethod
    def _sharpe_from_curve(points: list[tuple[datetime, float]]) -> float:
        # Crude proxy: compute returns between successive equity points and
        # take mean / stdev. Risk-free rate ignored (paper account).
        if len(points) < 2:
            return 0.0
        rets: list[float] = []
        for i in range(1, len(points)):
            rets.append(points[i][1] - points[i - 1][1])
        if not rets:
            return 0.0
        mean = sum(rets) / len(rets)
        if len(rets) < 2:
            return 0.0
        variance = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        stdev = math.sqrt(variance)
        if stdev == 0:
            return 0.0
        return mean / stdev

    # -- equity curve series ---------------------------------------------

    def equity_curve(
        self,
        from_dt: datetime | None,
        to_dt: datetime | None,
        granularity: str = "daily",
    ) -> dict[str, Any]:
        rows = self.all_trades()
        closed = [
            r
            for r in rows
            if r.get("status") == "CLOSED" and _trade_close_dt(r) is not None
        ]
        # Always anchor the curve from before the user's window, so the first
        # point inside the window already shows the running PnL up to that day.
        closed.sort(key=lambda r: _trade_close_dt(r) or datetime.min.replace(tzinfo=UTC))
        running = 0.0
        bucket = "%Y-%m-%dT%H:00:00+00:00" if granularity == "hourly" else "%Y-%m-%d"
        # Map bucket key -> last running equity (already in display currency,
        # because we convert each trade's PnL by its own native currency
        # before accumulating).
        buckets: dict[str, float] = {}
        for r in closed:
            close_dt = _trade_close_dt(r)
            if close_dt is None:
                continue
            running += self._pnl_in_display(r)
            key = close_dt.strftime(bucket)
            buckets[key] = round(running, 2)

        points = [{"t": k, "equity": v} for k, v in sorted(buckets.items())]
        if from_dt is not None or to_dt is not None:
            def _within_str(point_t: str) -> bool:
                try:
                    parsed = datetime.fromisoformat(point_t.replace("Z", "+00:00"))
                except ValueError:
                    return True
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                if from_dt is not None and parsed < from_dt:
                    return False
                if to_dt is not None and parsed >= to_dt:
                    return False
                return True

            points = [p for p in points if _within_str(p["t"])]
        return {"points": points}

    # -- PnL by symbol ----------------------------------------------------

    def pnl_by_symbol(
        self,
        from_dt: datetime | None,
        to_dt: datetime | None,
    ) -> dict[str, Any]:
        rows = self.all_trades()
        closed_in_period = [
            r for r in rows if r.get("status") == "CLOSED" and _within(r, from_dt, to_dt)
        ]
        agg: dict[tuple[str, str], dict[str, Any]] = {}
        for r in closed_in_period:
            sym = str(r.get("symbol", "")).upper()
            provider = str(r.get("provider") or PROVIDER_ETORO)
            key = (sym, provider)
            entry = agg.setdefault(
                key,
                {"symbol": sym, "provider": provider, "pnl_abs": 0.0, "allocated": 0.0, "n_trades": 0},
            )
            entry["pnl_abs"] += self._pnl_in_display(r)
            allocated_native = _safe_float(r.get("allocated_capital"))
            allocated_display = self._fx_convert(
                allocated_native, source_currency=self._trade_native_currency(r)
            ) or 0.0
            entry["allocated"] += float(allocated_display)
            entry["n_trades"] += 1
        items = []
        for entry in agg.values():
            allocated = entry["allocated"]
            pnl_pct = round((entry["pnl_abs"] / allocated) * 100.0, 2) if allocated > 0 else 0.0
            items.append(
                {
                    "symbol": entry["symbol"],
                    "provider": entry["provider"],
                    "pnl_abs": round(entry["pnl_abs"], 2),
                    "pnl_pct": pnl_pct,
                    "n_trades": entry["n_trades"],
                }
            )
        items.sort(key=lambda x: x["pnl_abs"], reverse=True)
        return {"items": items, "currency": self.config.currency}

    # -- allocation -------------------------------------------------------

    def allocation(self) -> dict[str, Any]:
        rows = self.all_trades()
        open_trades = [r for r in rows if r.get("status") == "OPEN"]
        by_category: dict[str, float] = {}
        by_provider: dict[str, float] = {}
        by_symbol: list[dict[str, Any]] = []
        for r in open_trades:
            native = self._trade_native_currency(r)
            qty = _safe_float(r.get("quantity"))
            current = _safe_float(r.get("current_price"))
            entry = _safe_float(r.get("entry_price"))
            value_native = qty * (current if current > 0 else entry)
            value_display = float(self._fx_convert(value_native, source_currency=native) or 0.0)
            cat = str(r.get("category", "")).upper()
            provider = str(r.get("provider") or PROVIDER_ETORO)
            by_category[cat] = by_category.get(cat, 0.0) + value_display
            by_provider[provider] = by_provider.get(provider, 0.0) + value_display
            by_symbol.append(
                {
                    "symbol": str(r.get("symbol", "")).upper(),
                    "category": cat,
                    "provider": provider,
                    "value": round(value_display, 2),
                }
            )
        by_symbol.sort(key=lambda x: x["value"], reverse=True)
        return {
            "by_category": [
                {"category": k, "value": round(v, 2)} for k, v in by_category.items()
            ],
            "by_provider": [
                {"provider": k, "value": round(v, 2)} for k, v in by_provider.items()
            ],
            "by_symbol": by_symbol,
            "currency": self.config.currency,
        }

    # -- returns distribution ---------------------------------------------

    def returns_distribution(
        self,
        from_dt: datetime | None,
        to_dt: datetime | None,
        bins: int = 12,
    ) -> dict[str, Any]:
        rows = self.all_trades()
        closed_in_period = [
            r for r in rows if r.get("status") == "CLOSED" and _within(r, from_dt, to_dt)
        ]
        returns_pct: list[float] = []
        for r in closed_in_period:
            entry = _safe_float(r.get("entry_price"))
            close = _safe_float(r.get("close_price"))
            if entry > 0 and close > 0:
                returns_pct.append((close - entry) / entry * 100.0)
        if not returns_pct:
            return {"bins": []}
        lo = min(returns_pct)
        hi = max(returns_pct)
        if lo == hi:
            return {"bins": [{"lo": lo, "hi": hi, "count": len(returns_pct)}]}
        bins = max(2, min(int(bins), 50))
        width = (hi - lo) / bins
        buckets = [{"lo": lo + i * width, "hi": lo + (i + 1) * width, "count": 0} for i in range(bins)]
        for v in returns_pct:
            idx = min(bins - 1, int((v - lo) / width))
            buckets[idx]["count"] += 1
        for b in buckets:
            b["lo"] = round(b["lo"], 2)
            b["hi"] = round(b["hi"], 2)
        return {"bins": buckets}


# -- helpers exposed for the API --------------------------------------------


def parse_window(from_param: str | None, to_param: str | None) -> tuple[datetime | None, datetime | None]:
    def _parse(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    return _parse(from_param), _parse(to_param)


def parse_named_window(window: str) -> tuple[datetime | None, datetime | None]:
    """Map a friendly window like ``1D`` / ``YTD`` / ``All`` to (from, to)."""

    now = utc_now()
    label = (window or "All").strip().upper()
    if label == "ALL":
        return None, None
    if label == "1D":
        return now - timedelta(days=1), now
    if label == "1W":
        return now - timedelta(weeks=1), now
    if label == "1M":
        return now - timedelta(days=30), now
    if label == "3M":
        return now - timedelta(days=90), now
    if label == "6M":
        return now - timedelta(days=180), now
    if label == "1Y":
        return now - timedelta(days=365), now
    if label == "YTD":
        return datetime(now.year, 1, 1, tzinfo=UTC), now
    return None, None
