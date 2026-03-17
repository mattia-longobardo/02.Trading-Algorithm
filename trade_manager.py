"""Trading workflow orchestration and script-managed trade persistence."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from alpaca_client import AlpacaClient
from data_manager import DataManager
from db import db_cursor, fetch_all, fetch_one
from gpt_client import GPTClient
from utils import AppConfig, isoformat_utc, parse_datetime, utc_now


class TradeManager:
    """Coordinate Alpaca orders, DB state, and GPT entry decisions."""

    TERMINAL_PENDING_STATUSES = {
        "canceled": "CANCELED",
        "cancelled": "CANCELED",
        "expired": "EXPIRED",
        "rejected": "REJECTED",
    }
    TERMINAL_EXIT_STATUSES = {"canceled", "cancelled", "expired", "rejected"}
    FILLED_ENTRY_STATUSES = {"filled", "partially_filled"}

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        alpaca_client: AlpacaClient,
        data_manager: DataManager,
        gpt_client: GPTClient,
    ) -> None:
        self.config = config
        self.logger = logger.getChild("trade_manager")
        self.alpaca_client = alpaca_client
        self.data_manager = data_manager
        self.gpt_client = gpt_client

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _order_status(order: Any) -> str:
        return str(getattr(order, "status", "")).lower()

    def _order_timestamp(self, order: Any, *field_names: str) -> datetime | None:
        for field_name in field_names:
            value = getattr(order, field_name, None)
            if value is None:
                continue
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return parse_datetime(value)
        return None

    def _resolve_current_price(
        self,
        symbol: str,
        category: str,
        position: Any | None = None,
        fallback: float | None = None,
    ) -> float:
        try:
            return self.alpaca_client.get_latest_price(symbol, category)
        except Exception:
            current_price = self._as_float(getattr(position, "current_price", None)) if position is not None else None
            if current_price is not None:
                return current_price
            if fallback is not None:
                return fallback
            raise

    @staticmethod
    def _compute_trailing_stop_price(high_water_mark: float, trailing_stop_distance: float | None) -> float | None:
        if trailing_stop_distance is None or trailing_stop_distance <= 0:
            return None
        return round(high_water_mark - trailing_stop_distance, 8)

    @staticmethod
    def _downside_close_reason(
        current_price: float,
        stop_loss: float | None,
        trailing_stop_price: float | None,
    ) -> str | None:
        if trailing_stop_price is not None and stop_loss is not None:
            if trailing_stop_price >= stop_loss and current_price <= trailing_stop_price:
                return "TRAILING_STOP"
            if current_price <= stop_loss:
                return "STOP_LOSS"
            if current_price <= trailing_stop_price:
                return "TRAILING_STOP"
            return None
        if stop_loss is not None and current_price <= stop_loss:
            return "STOP_LOSS"
        if trailing_stop_price is not None and current_price <= trailing_stop_price:
            return "TRAILING_STOP"
        return None

    def get_trade(self, trade_id: int) -> dict[str, Any] | None:
        return fetch_one(self.config.db_trades, "SELECT * FROM trades WHERE id = ?", (trade_id,))

    def get_open_or_pending_trades(self) -> list[dict[str, Any]]:
        return fetch_all(
            self.config.db_trades,
            "SELECT * FROM trades WHERE status IN ('PENDING', 'OPEN') ORDER BY created_at",
        )

    def get_symbol_trades(self, symbol: str) -> list[dict[str, Any]]:
        return fetch_all(
            self.config.db_trades,
            "SELECT * FROM trades WHERE symbol = ? AND status IN ('PENDING', 'OPEN') ORDER BY created_at",
            (symbol,),
        )

    def count_active_trades(self, category: str) -> int:
        row = fetch_one(
            self.config.db_trades,
            "SELECT COUNT(*) AS count FROM trades WHERE category = ? AND status IN ('PENDING', 'OPEN')",
            (category,),
        )
        return int(row["count"]) if row else 0

    def compute_allocated_capital(self) -> float:
        cash = self.alpaca_client.get_available_cash()
        slots = self.config.max_open_trades_stock + self.config.max_open_trades_crypto
        active = len(self.get_open_or_pending_trades())
        available_slots = max(slots - active, 1)
        return round(cash / available_slots, 2)

    def _save_new_trade(
        self,
        category: str,
        symbol: str,
        signal: dict[str, Any],
        order_payload: dict[str, Any],
        allocated_capital: float,
    ) -> None:
        order = order_payload["order"]
        trailing_stop_distance = self._as_float(signal.get("trailing_stop_distance"))
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                INSERT INTO trades (
                    symbol, category, direction, status, entry_price, target_entry_price, quantity, allocated_capital,
                    take_profit, stop_loss, trailing_stop_distance, alpaca_order_id, client_order_id,
                    reasoning, confidence
                ) VALUES (?, ?, 'LONG', 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    category,
                    float(signal["entry_price"]),
                    float(signal["entry_price"]),
                    float(order_payload["quantity"]),
                    allocated_capital,
                    float(signal["take_profit"]),
                    float(signal["stop_loss"]),
                    trailing_stop_distance,
                    str(getattr(order, "id", "")),
                    order_payload["client_order_id"],
                    signal.get("reasoning"),
                    signal.get("confidence"),
                ),
            )
        self.logger.info("Stored new pending trade for %s", symbol)

    def _signal_has_required_levels(self, signal: dict[str, Any]) -> bool:
        for field in ("entry_price", "take_profit", "stop_loss"):
            value = signal.get(field)
            if not isinstance(value, (int, float)) or float(value) <= 0:
                self.logger.warning(
                    "GPT returned OPEN for %s with invalid %s=%s; skipping trade",
                    signal.get("symbol"),
                    field,
                    value,
                )
                return False
        trailing_stop_distance = signal.get("trailing_stop_distance")
        if trailing_stop_distance is None:
            return True
        if not isinstance(trailing_stop_distance, (int, float)) or float(trailing_stop_distance) <= 0:
            self.logger.warning(
                "GPT returned OPEN for %s with invalid trailing_stop_distance=%s; skipping trade",
                signal.get("symbol"),
                trailing_stop_distance,
            )
            return False
        return True

    def maybe_open_trade(self, category: str, symbol: str) -> None:
        if self.get_symbol_trades(symbol):
            self.logger.debug("Skipping %s because an active trade already exists for the symbol", symbol)
            return
        if self.alpaca_client.get_open_position(symbol) is not None:
            self.logger.debug("Skipping %s because Alpaca already reports an open position", symbol)
            return

        max_trades = self.config.max_open_trades_stock if category == "STOCK" else self.config.max_open_trades_crypto
        if self.count_active_trades(category) >= max_trades:
            self.logger.debug("Skipping %s because the max number of active %s trades has been reached", symbol, category)
            return

        candles = self.data_manager.get_symbol_history(symbol)
        if not candles:
            self.logger.warning("No market data found for %s, skipping new trade decision", symbol)
            return

        signal = self.gpt_client.request_new_signal(symbol, category, candles, [])
        if signal["action"] != "OPEN":
            self.logger.debug("GPT skipped %s", symbol)
            return
        if not self._signal_has_required_levels(signal):
            return

        allocated_capital = self.compute_allocated_capital()
        try:
            order_payload = self.alpaca_client.place_limit_entry_order(
                symbol=symbol,
                category=category,
                entry_price=float(signal["entry_price"]),
                allocated_capital=allocated_capital,
            )
        except Exception as exc:
            if self.alpaca_client.is_insufficient_balance_error(exc):
                self.logger.warning(
                    "Skipping %s because available capital is insufficient for the proposed entry",
                    symbol,
                )
                return
            raise
        self._save_new_trade(category, symbol, signal, order_payload, allocated_capital)

    def _activate_trade_from_entry_fill(self, trade: dict[str, Any], order: Any) -> None:
        position = self.alpaca_client.get_open_position(trade["symbol"])
        filled_quantity = (
            self._as_float(getattr(order, "filled_qty", None))
            or self._as_float(getattr(position, "qty", None))
            or float(trade["quantity"])
        )
        entry_price = (
            self._as_float(getattr(order, "filled_avg_price", None))
            or self._as_float(getattr(position, "avg_entry_price", None))
            or float(trade["entry_price"])
        )
        current_price = self._resolve_current_price(
            trade["symbol"],
            trade["category"],
            position=position,
            fallback=entry_price,
        )
        high_water_mark = max(
            self._as_float(trade.get("high_water_mark")) or entry_price,
            entry_price,
            current_price,
        )
        trailing_stop_price = self._compute_trailing_stop_price(
            high_water_mark,
            self._as_float(trade.get("trailing_stop_distance")),
        )
        pnl = (current_price - entry_price) * filled_quantity
        open_timestamp = self._order_timestamp(order, "filled_at", "updated_at", "submitted_at") or utc_now()
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET status = 'OPEN', open_timestamp = ?, entry_price = ?, quantity = ?, current_price = ?, pnl = ?,
                    high_water_mark = ?, trailing_stop_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    isoformat_utc(open_timestamp),
                    entry_price,
                    filled_quantity,
                    current_price,
                    pnl,
                    high_water_mark,
                    trailing_stop_price,
                    trade["id"],
                ),
            )
        self.logger.info("Trade %s moved from PENDING to OPEN", trade["id"])

    def sync_pending_trade(self, trade: dict[str, Any]) -> None:
        if not trade.get("alpaca_order_id"):
            return
        order = self.alpaca_client.get_order(str(trade["alpaca_order_id"]))
        status = self._order_status(order)
        if status in self.FILLED_ENTRY_STATUSES:
            if status == "partially_filled":
                try:
                    self.alpaca_client.cancel_order(str(trade["alpaca_order_id"]))
                except Exception:
                    self.logger.warning("Could not cancel partially-filled remainder for trade %s", trade["id"], exc_info=True)
            self._activate_trade_from_entry_fill(trade, order)
            return
        if status in self.TERMINAL_PENDING_STATUSES:
            close_timestamp = self._order_timestamp(order, "expired_at", "canceled_at", "updated_at") or utc_now()
            with db_cursor(self.config.db_trades) as cursor:
                cursor.execute(
                    """
                    UPDATE trades
                    SET status = 'CLOSED', close_reason = ?, close_timestamp = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (self.TERMINAL_PENDING_STATUSES[status], isoformat_utc(close_timestamp), trade["id"]),
                )
            self.logger.info("Pending trade %s closed with status %s", trade["id"], status)

    def _mark_trade_closed(
        self,
        trade: dict[str, Any],
        close_reason: str,
        close_price: float,
        close_timestamp: datetime | None = None,
    ) -> None:
        pnl = (close_price - float(trade["entry_price"])) * float(trade["quantity"])
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET status = 'CLOSED', close_price = ?, close_timestamp = ?, close_reason = ?, pending_close_reason = NULL,
                    pnl = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (close_price, isoformat_utc(close_timestamp or utc_now()), close_reason, pnl, trade["id"]),
            )
        self.logger.info("Trade %s closed with reason %s", trade["id"], close_reason)

    def _request_market_close(self, trade: dict[str, Any], close_reason: str, trigger_price: float) -> None:
        if trade.get("exit_order_id"):
            return
        try:
            order = self.alpaca_client.close_position_market(trade["symbol"])
        except Exception as exc:
            message = str(exc).lower()
            if "position does not exist" in message or "not found" in message:
                self._mark_trade_closed(trade, close_reason, trigger_price)
                return
            raise
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET exit_order_id = ?, exit_client_order_id = ?, exit_requested_at = ?, pending_close_reason = ?,
                    current_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    str(getattr(order, "id", "")),
                    str(getattr(order, "client_order_id", "")),
                    isoformat_utc(utc_now()),
                    close_reason,
                    trigger_price,
                    trade["id"],
                ),
            )
        refreshed_trade = self.get_trade(trade["id"]) or trade
        self._sync_exit_order(refreshed_trade)

    def _close_trade_without_position(self, trade: dict[str, Any], close_reason: str | None = None) -> None:
        reason = close_reason or trade.get("pending_close_reason") or trade.get("close_reason") or "EXTERNAL_CLOSE"
        close_price = float(trade.get("current_price") or trade["entry_price"])
        self._mark_trade_closed(trade, reason, close_price)

    def _sync_exit_order(self, trade: dict[str, Any]) -> None:
        exit_order_id = trade.get("exit_order_id")
        if not exit_order_id:
            return
        order = self.alpaca_client.get_order(str(exit_order_id))
        status = self._order_status(order)
        if status == "filled":
            close_price = self._as_float(getattr(order, "filled_avg_price", None)) or float(trade.get("current_price") or trade["entry_price"])
            close_timestamp = self._order_timestamp(order, "filled_at", "updated_at") or utc_now()
            self._mark_trade_closed(
                trade,
                str(trade.get("pending_close_reason") or "MARKET_EXIT"),
                close_price,
                close_timestamp,
            )
            return
        if status in self.TERMINAL_EXIT_STATUSES:
            position = self.alpaca_client.get_open_position(trade["symbol"])
            if position is None:
                self._close_trade_without_position(trade)
                return
            with db_cursor(self.config.db_trades) as cursor:
                cursor.execute(
                    """
                    UPDATE trades
                    SET exit_order_id = NULL, exit_client_order_id = NULL, exit_requested_at = NULL,
                        pending_close_reason = NULL, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (trade["id"],),
                )
            self.logger.warning("Exit order for trade %s ended with %s; trade remains OPEN", trade["id"], status)
            return
        if self.alpaca_client.get_open_position(trade["symbol"]) is None:
            self._close_trade_without_position(trade)

    def sync_open_trade(self, trade: dict[str, Any]) -> None:
        if trade.get("exit_order_id"):
            self._sync_exit_order(trade)
            return

        position = self.alpaca_client.get_open_position(trade["symbol"])
        if position is None:
            self._close_trade_without_position(trade)
            return

        quantity = self._as_float(getattr(position, "qty", None)) or float(trade["quantity"])
        current_price = self._resolve_current_price(
            trade["symbol"],
            trade["category"],
            position=position,
            fallback=float(trade.get("current_price") or trade["entry_price"]),
        )
        entry_price = float(trade["entry_price"])
        stop_loss = self._as_float(trade.get("stop_loss"))
        take_profit = self._as_float(trade.get("take_profit"))
        high_water_mark = max(self._as_float(trade.get("high_water_mark")) or entry_price, current_price)
        trailing_stop_price = self._compute_trailing_stop_price(
            high_water_mark,
            self._as_float(trade.get("trailing_stop_distance")),
        )
        pnl = (current_price - entry_price) * quantity

        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET quantity = ?, current_price = ?, pnl = ?, high_water_mark = ?, trailing_stop_price = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (quantity, current_price, pnl, high_water_mark, trailing_stop_price, trade["id"]),
            )

        if take_profit is not None and current_price >= take_profit:
            self._request_market_close(trade, "TAKE_PROFIT", current_price)
            return

        close_reason = self._downside_close_reason(current_price, stop_loss, trailing_stop_price)
        if close_reason:
            self._request_market_close(trade, close_reason, current_price)

    def sync_alpaca_state(self) -> None:
        for trade in self.get_open_or_pending_trades():
            try:
                if trade["status"] == "PENDING":
                    self.sync_pending_trade(trade)
                elif trade["status"] == "OPEN":
                    self.sync_open_trade(trade)
            except Exception:
                self.logger.exception("Failed to sync trade %s", trade["id"])

    def evaluate_cycle(self, universe: dict[str, list[str]]) -> None:
        for category, symbols in universe.items():
            for symbol in symbols:
                try:
                    self.maybe_open_trade(category, symbol)
                except Exception:
                    self.logger.exception("Failed to evaluate symbol %s", symbol)

    def symbols_to_monitor(self, universe: dict[str, list[str]]) -> dict[str, str]:
        monitored = {symbol: "STOCK" for symbol in universe.get("STOCK", [])}
        monitored.update({symbol: "CRYPTO" for symbol in universe.get("CRYPTO", [])})
        for trade in self.get_open_or_pending_trades():
            monitored[trade["symbol"]] = trade["category"]
        return monitored

    def weekly_summary(self) -> dict[str, Any]:
        rows = fetch_all(self.config.db_trades, "SELECT * FROM trades")
        cutoff = utc_now() - timedelta(days=7)
        rows = [
            row
            for row in rows
            if row["status"] in {"PENDING", "OPEN"}
            or (parse_datetime(row.get("close_timestamp")) and parse_datetime(row.get("close_timestamp")) >= cutoff)
        ]
        closed = [row for row in rows if row["status"] == "CLOSED"]
        winners = [row for row in closed if (row.get("pnl") or 0) > 0]
        pnls = [row.get("pnl") or 0 for row in closed]
        best_trade = max(closed, key=lambda row: row.get("pnl") or float("-inf"), default=None)
        worst_trade = min(closed, key=lambda row: row.get("pnl") or float("inf"), default=None)
        most_traded = Counter(row["symbol"] for row in rows).most_common(5)
        pnl_by_category: dict[str, float] = {}
        for row in closed:
            pnl_by_category[row["category"]] = pnl_by_category.get(row["category"], 0.0) + float(row.get("pnl") or 0.0)
        return {
            "open_trades": [row for row in rows if row["status"] == "OPEN"],
            "pending_trades": [row for row in rows if row["status"] == "PENDING"],
            "closed_trades": closed,
            "pnl_total": round(sum(pnls), 2),
            "pnl_by_category": {key: round(value, 2) for key, value in pnl_by_category.items()},
            "win_rate": round(len(winners) / len(closed), 4) if closed else 0.0,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "most_traded_symbols": most_traded,
        }
