"""Operator-driven mutations to existing trades from the Console UI.

The trading bot owns the lifecycle (PENDING → OPEN → CLOSED/CANCELLED). The
operator can only adjust certain numeric parameters on an existing trade —
target entry price, quantity, take profit, stop loss, trailing TP/TSL — and
each change is validated and audit-logged.
"""

from __future__ import annotations

from typing import Any

from core.db import db_cursor, fetch_one
from core.utils import AppConfig, isoformat_utc, utc_now


# Whitelist of fields the operator can edit on a trade row.
EDITABLE_TRADE_FIELDS: tuple[str, ...] = (
    "target_entry_price",
    "quantity",
    "take_profit",
    "trailing_take_profit_distance",
    "trailing_take_profit_activation_pct",
    "stop_loss",
    "trailing_stop_distance",
    # ``high_water_mark`` drives the trailing TP / trailing stop levels: letting
    # the operator override it is what allows them to "reset" a runaway trailing
    # TP that has armed below entry, without waiting for the bot to recompute.
    "high_water_mark",
)


class TradeValidationError(ValueError):
    """Raised when an attempted update violates the trade rules."""


def _coerce_optional_float(name: str, value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TradeValidationError(f"{name} must be a number") from exc
    if result <= 0:
        raise TradeValidationError(f"{name} must be a positive number")
    return result


def get_trade_row(config: AppConfig, trade_id: int) -> dict[str, Any] | None:
    return fetch_one(config.db_trades, "SELECT * FROM trades WHERE id = ?", (int(trade_id),))


def update_trade(
    config: AppConfig,
    trade_id: int,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply a partial update to a trade row.

    Returns ``(before, after)`` row dicts so the caller can write an audit
    entry. Raises :class:`TradeValidationError` on any rule violation.
    """

    before = get_trade_row(config, trade_id)
    if before is None:
        raise TradeValidationError("Trade not found")

    updates: dict[str, Any] = {}
    for field in EDITABLE_TRADE_FIELDS:
        if field not in payload:
            continue
        raw = payload[field]
        if field == "quantity":
            # Quantity is special — must be positive (allow fractional for crypto).
            if raw is None:
                raise TradeValidationError("quantity is required")
            try:
                qty = float(raw)
            except (TypeError, ValueError) as exc:
                raise TradeValidationError("quantity must be a number") from exc
            if qty <= 0:
                raise TradeValidationError("quantity must be a positive number")
            updates[field] = qty
        else:
            updates[field] = _coerce_optional_float(field, raw)

    # Trailing-take-profit pair rule: both null or both positive.
    new_ttp_distance = updates.get(
        "trailing_take_profit_distance", before.get("trailing_take_profit_distance")
    )
    new_ttp_activation = updates.get(
        "trailing_take_profit_activation_pct",
        before.get("trailing_take_profit_activation_pct"),
    )
    if (new_ttp_distance is None) ^ (new_ttp_activation is None):
        raise TradeValidationError(
            "trailing_take_profit_distance and trailing_take_profit_activation_pct "
            "must be either both null or both positive numbers"
        )

    if not updates:
        return before, before  # no-op update

    now = isoformat_utc(utc_now()) or ""
    set_clauses = ", ".join(f"{column} = ?" for column in updates) + ", updated_at = ?"
    params = list(updates.values()) + [now, int(trade_id)]
    with db_cursor(config.db_trades) as cursor:
        cursor.execute(f"UPDATE trades SET {set_clauses} WHERE id = ?", tuple(params))

    after = get_trade_row(config, trade_id)
    if after is None:
        raise TradeValidationError("Trade vanished during update")
    return before, after


def manual_close_or_cancel(
    trade_manager: Any,
    trade_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Operator-driven close (OPEN) or cancel (PENDING) of a trade.

    Dispatches based on current status:
      * ``PENDING`` → cancel any open broker order, mark the row CANCELLED
        with reason ``MANUAL_CANCEL``.
      * ``OPEN``    → request a market exit via the broker with reason
        ``MANUAL_CLOSE``. The exit fill is reconciled by ``sync_broker_state``
        on the next scheduler tick.
      * anything else → :class:`TradeValidationError`.

    Returns ``(before, after)`` rows for audit. The trade is read back from
    the DB after the action so the caller gets the post-state.
    """

    before = trade_manager.get_trade(int(trade_id))
    if before is None:
        raise TradeValidationError("Trade not found")
    status = str(before.get("status") or "").upper()
    if status == "PENDING":
        order_id = before.get("alpaca_order_id")
        if order_id:
            try:
                trade_manager._cancel_broker_order(before, str(order_id))
            except Exception:
                trade_manager.logger.exception(
                    "Manual cancel: broker rejected cancel of order %s for trade %s",
                    order_id,
                    trade_id,
                )
        trade_manager._cancel_pending_trade_record(before, "MANUAL_CANCEL")
    elif status == "OPEN":
        trigger_price = (
            float(before.get("current_price") or 0.0)
            or float(before.get("entry_price") or 0.0)
        )
        trade_manager._request_market_close(before, "MANUAL_CLOSE", trigger_price)
    else:
        raise TradeValidationError(
            f"Trade is {status or 'in an unknown state'} and cannot be manually closed"
        )

    after = trade_manager.get_trade(int(trade_id)) or before
    return before, after
