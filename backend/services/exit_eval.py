"""Pure exit-trigger evaluation functions.

These are module-level equivalents of the four ``TradeManager`` staticmethods,
extracted so they can be tested and reused without pulling in any I/O or
database dependencies.  The logic is copied **verbatim** from
``TradeManager._compute_trailing_stop_price``,
``TradeManager._compute_trailing_take_profit_price``,
``TradeManager._downside_close_reason``, and
``TradeManager._trailing_take_profit_close_reason``; no behaviour change.
"""


def compute_trailing_stop_price(high_water_mark: float, trailing_stop_distance: float | None) -> float | None:
    if trailing_stop_distance is None or trailing_stop_distance <= 0:
        return None
    return round(high_water_mark - trailing_stop_distance, 8)


def compute_trailing_take_profit_price(
    high_water_mark: float,
    entry_price: float | None,
    trailing_take_profit_distance: float | None,
    trailing_take_profit_activation_pct: float | None,
    min_profit_buffer_pct: float = 0.0,
) -> float | None:
    """Compute the trailing TP trigger, floored at entry + min profit buffer.

    Without the floor, a trade with ``distance > (HWM − entry)`` would
    trigger below the entry price and close at a loss labelled
    ``TRAILING_TAKE_PROFIT``. The floor guarantees that whenever the
    trailing arms it will close, at worst, at a small minimum profit —
    which is what "take profit" is supposed to mean. The signal-side
    validator (`_validate_trailing_take_profit_pair`) keeps the floor
    from ever silently changing GPT's intent on healthy signals.
    """

    if (
        entry_price is None
        or entry_price <= 0
        or trailing_take_profit_distance is None
        or trailing_take_profit_distance <= 0
        or trailing_take_profit_activation_pct is None
        or trailing_take_profit_activation_pct <= 0
    ):
        return None
    activation_threshold = entry_price * (1 + trailing_take_profit_activation_pct / 100.0)
    if high_water_mark < activation_threshold:
        return None
    raw_trigger = high_water_mark - trailing_take_profit_distance
    floor = entry_price * (1 + max(min_profit_buffer_pct, 0.0) / 100.0)
    return round(max(raw_trigger, floor), 8)


def downside_close_reason(
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


def trailing_take_profit_close_reason(
    current_price: float,
    trailing_take_profit_price: float | None,
) -> str | None:
    if trailing_take_profit_price is not None and current_price <= trailing_take_profit_price:
        return "TRAILING_TAKE_PROFIT"
    return None
