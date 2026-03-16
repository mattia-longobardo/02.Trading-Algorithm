"""Trading workflow orchestration and trade persistence."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta
from typing import Any

from alpaca_client import AlpacaClient
from data_manager import DataManager
from db import db_cursor, fetch_all, fetch_one
from gpt_client import GPTClient
from utils import AppConfig, isoformat_utc, parse_datetime, utc_now


class TradeManager:
    """Coordinate Alpaca orders, DB state, and GPT decisions."""

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

    def _save_new_trade(self, category: str, signal: dict[str, Any], order_payload: dict[str, Any], allocated_capital: float) -> None:
        order = order_payload["order"]
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                INSERT INTO trades (
                    symbol, category, direction, status, entry_price, quantity, allocated_capital,
                    take_profit, stop_loss, trailing_stop_distance, alpaca_order_id, client_order_id,
                    reasoning, confidence
                ) VALUES (?, ?, 'LONG', 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal["symbol"],
                    category,
                    signal["entry_price"],
                    order_payload["quantity"],
                    allocated_capital,
                    signal["take_profit"],
                    signal["stop_loss"],
                    signal["trailing_stop_distance"],
                    str(getattr(order, "id", "")),
                    order_payload["client_order_id"],
                    signal.get("reasoning"),
                    signal.get("confidence"),
                ),
            )
        self.logger.info("Stored new pending trade for %s", signal["symbol"])

    def _signal_has_required_levels(self, signal: dict[str, Any]) -> bool:
        required_fields = ("entry_price", "take_profit", "stop_loss", "trailing_stop_distance")
        for field in required_fields:
            value = signal.get(field)
            if not isinstance(value, (int, float)) or float(value) <= 0:
                self.logger.warning("GPT returned OPEN for %s with invalid %s=%s; skipping trade", signal.get("symbol"), field, value)
                return False
        return True

    def maybe_open_trade(self, category: str, symbol: str) -> None:
        if self.get_symbol_trades(symbol):
            return
        max_trades = self.config.max_open_trades_stock if category == "STOCK" else self.config.max_open_trades_crypto
        if self.count_active_trades(category) >= max_trades:
            return

        candles = self.data_manager.get_symbol_history(symbol)
        if not candles:
            self.logger.warning("No market data found for %s, skipping new trade decision", symbol)
            return

        signal = self.gpt_client.request_new_signal(symbol, category, candles, [])
        if signal["action"] != "OPEN":
            self.logger.info("GPT skipped %s", symbol)
            return
        if not self._signal_has_required_levels(signal):
            return

        allocated_capital = self.compute_allocated_capital()
        order_payload = self.alpaca_client.place_limit_bracket_order(
            symbol=symbol,
            category=category,
            entry_price=float(signal["entry_price"]),
            take_profit=float(signal["take_profit"]),
            stop_loss=float(signal["stop_loss"]),
            allocated_capital=allocated_capital,
        )
        self._save_new_trade(category, signal, order_payload, allocated_capital)

    def sync_pending_trade(self, trade: dict[str, Any]) -> None:
        if not trade.get("alpaca_order_id"):
            return
        order = self.alpaca_client.get_order(str(trade["alpaca_order_id"]))
        status = str(getattr(order, "status", "")).lower()
        if status == "filled":
            filled_at = getattr(order, "filled_at", None) or utc_now()
            avg_fill_price = float(getattr(order, "filled_avg_price", trade["entry_price"]) or trade["entry_price"])
            with db_cursor(self.config.db_trades) as cursor:
                cursor.execute(
                    """
                    UPDATE trades
                    SET status = 'OPEN', open_timestamp = ?, entry_price = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (isoformat_utc(filled_at), avg_fill_price, trade["id"]),
                )
            self.logger.info("Trade %s moved from PENDING to OPEN", trade["id"])
            return
        if status in {"canceled", "expired", "rejected"}:
            with db_cursor(self.config.db_trades) as cursor:
                cursor.execute(
                    """
                    UPDATE trades
                    SET status = 'CLOSED', close_reason = 'EXPIRED', close_timestamp = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (isoformat_utc(utc_now()), trade["id"]),
                )
            self.logger.info("Pending trade %s closed as expired/cancelled", trade["id"])

    def sync_open_trade(self, trade: dict[str, Any]) -> None:
        position = self.alpaca_client.get_open_position(trade["symbol"])
        if position is None:
            close_price = float(trade.get("current_price") or trade["entry_price"])
            close_reason = "GPT_SIGNAL"
            if trade.get("alpaca_order_id"):
                order = self.alpaca_client.get_order(str(trade["alpaca_order_id"]))
                close_reason = self.alpaca_client.infer_close_reason(order)
                close_price = float(getattr(order, "filled_avg_price", close_price) or close_price)
            pnl = (close_price - float(trade["entry_price"])) * float(trade["quantity"])
            with db_cursor(self.config.db_trades) as cursor:
                cursor.execute(
                    """
                    UPDATE trades
                    SET status = 'CLOSED', close_price = ?, close_timestamp = ?, close_reason = ?, pnl = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (close_price, isoformat_utc(utc_now()), close_reason, pnl, trade["id"]),
                )
            self.logger.info("Trade %s closed via Alpaca sync", trade["id"])
            return

        current_price = float(getattr(position, "current_price", trade["entry_price"]) or trade["entry_price"])
        pnl = (current_price - float(trade["entry_price"])) * float(trade["quantity"])
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET current_price = ?, pnl = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (current_price, pnl, trade["id"]),
            )

    def sync_alpaca_state(self) -> None:
        for trade in self.get_open_or_pending_trades():
            try:
                if trade["status"] == "PENDING":
                    self.sync_pending_trade(trade)
                elif trade["status"] == "OPEN":
                    self.sync_open_trade(trade)
            except Exception:
                self.logger.exception("Failed to sync trade %s", trade["id"])

    def _cancel_existing_order_if_needed(self, trade: dict[str, Any]) -> None:
        if trade.get("alpaca_order_id"):
            try:
                self.alpaca_client.cancel_order(str(trade["alpaca_order_id"]))
            except Exception:
                self.logger.warning("Could not cancel order %s before refresh", trade["alpaca_order_id"], exc_info=True)

    def _recreate_updated_order(self, trade: dict[str, Any], decision: dict[str, Any]) -> None:
        if not self.alpaca_client.supports_advanced_orders(trade["category"], float(trade["quantity"])):
            take_profit = float(decision["new_take_profit"] or trade["take_profit"] or 0.0)
            stop_loss = float(decision["new_stop_loss"] or trade["stop_loss"] or 0.0)
            with db_cursor(self.config.db_trades) as cursor:
                cursor.execute(
                    """
                    UPDATE trades
                    SET take_profit = ?, stop_loss = ?, trailing_stop_distance = ?, reasoning = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        take_profit if take_profit > 0 else None,
                        stop_loss if stop_loss > 0 else None,
                        decision["new_trailing_stop_distance"] or trade["trailing_stop_distance"],
                        decision["reasoning"],
                        trade["id"],
                    ),
                )
            self.logger.info("Trade %s updated in DB only because %s does not support bracket refresh", trade["id"], trade["category"])
            return

        self._cancel_existing_order_if_needed(trade)
        take_profit = float(decision["new_take_profit"] or trade["take_profit"])
        stop_loss = float(decision["new_stop_loss"] or trade["stop_loss"])
        order_payload = self.alpaca_client.place_limit_bracket_order(
            symbol=trade["symbol"],
            category=trade["category"],
            entry_price=float(trade["entry_price"]),
            take_profit=take_profit,
            stop_loss=stop_loss,
            allocated_capital=float(trade["allocated_capital"]),
        )
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET take_profit = ?, stop_loss = ?, trailing_stop_distance = ?, alpaca_order_id = ?, client_order_id = ?,
                    reasoning = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    take_profit,
                    stop_loss,
                    decision["new_trailing_stop_distance"] or trade["trailing_stop_distance"],
                    str(getattr(order_payload["order"], "id", "")),
                    order_payload["client_order_id"],
                    decision["reasoning"],
                    trade["id"],
                ),
            )
        self.logger.info("Trade %s updated with refreshed bracket order", trade["id"])

    def _close_trade_immediately(self, trade: dict[str, Any], reasoning: str) -> None:
        self._cancel_existing_order_if_needed(trade)
        self.alpaca_client.place_market_exit_order(trade["symbol"], float(trade["quantity"]), trade["category"])
        close_price = float(trade.get("current_price") or trade["entry_price"])
        pnl = (close_price - float(trade["entry_price"])) * float(trade["quantity"])
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET status = 'CLOSED', close_price = ?, close_timestamp = ?, close_reason = 'GPT_SIGNAL',
                    pnl = ?, reasoning = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (close_price, isoformat_utc(utc_now()), pnl, reasoning, trade["id"]),
            )
        self.logger.info("Trade %s closed immediately by GPT signal", trade["id"])

    def manage_existing_trade(self, trade: dict[str, Any]) -> None:
        candles = self.data_manager.get_symbol_history(trade["symbol"])
        if not candles:
            return
        decision = self.gpt_client.request_trade_management(
            trade["symbol"],
            trade["category"],
            candles,
            self.get_symbol_trades(trade["symbol"]),
        )
        action = decision["action"]
        if action == "HOLD":
            self.logger.info("GPT holds trade %s", trade["id"])
            return
        if action == "CANCEL" and trade["status"] == "PENDING":
            self._cancel_existing_order_if_needed(trade)
            with db_cursor(self.config.db_trades) as cursor:
                cursor.execute(
                    """
                    UPDATE trades
                    SET status = 'CLOSED', close_reason = 'EXPIRED', close_timestamp = ?, reasoning = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (isoformat_utc(utc_now()), decision["reasoning"], trade["id"]),
                )
            return
        if action == "UPDATE":
            self._recreate_updated_order(trade, decision)
            return
        if action == "CLOSE" or decision.get("close_immediately"):
            self._close_trade_immediately(trade, decision["reasoning"])

    def evaluate_cycle(self, universe: dict[str, list[str]]) -> None:
        for trade in self.get_open_or_pending_trades():
            try:
                self.manage_existing_trade(trade)
            except Exception:
                self.logger.exception("Failed to manage existing trade %s", trade["id"])

        for category, symbols in universe.items():
            for symbol in symbols:
                try:
                    if not self.get_symbol_trades(symbol):
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
