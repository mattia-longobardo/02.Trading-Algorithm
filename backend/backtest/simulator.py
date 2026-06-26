"""Deterministic per-trade exit replay. Pure: prices in, verdict out.

Daily granularity. Intraday-ambiguity rule: if a day's [low, high] straddles
both an adverse (stop/trailing-stop) and a favorable (TP/trailing-TP) trigger,
the adverse one is assumed to fire first (conservative). GPT entry selection is
NOT replayed — the trade's entry/levels are taken as given.
"""

from __future__ import annotations

from services import exit_eval
from services.exit_levels import normalize_exit_levels
from services.regime import passes_regime_gate


def _f(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def simulate_trade(trade, entry_bars, forward_bars, *, mode, exit_cfg, regime_cfg):
    if mode not in ("old", "new"):
        raise ValueError(f"unknown mode: {mode!r}")
    entry = float(trade["entry_price"])
    stop = float(trade["stop_loss"])
    tp = _f(trade.get("take_profit"))
    ttp_dist = _f(trade.get("trailing_take_profit_distance"))
    ttp_act = _f(trade.get("trailing_take_profit_activation_pct"))
    ts_dist = _f(trade.get("trailing_stop_distance"))
    risk = entry - stop
    result = {"taken": True, "exit_reason": None, "close_price": None,
              "realized_r": None, "reached_tp": False}
    if risk <= 0:
        result["taken"] = False
        return result

    if mode == "new":
        if regime_cfg.get("enabled"):
            if not passes_regime_gate(entry_bars, int(regime_cfg["sma_period"]), current_price=entry):
                result["taken"] = False
                return result
        lv = normalize_exit_levels(
            entry, stop, tp, ttp_dist, ttp_act,
            min_reward_risk=exit_cfg["min_reward_risk"],
            arm_r=exit_cfg["arm_r"], trail_r=exit_cfg["trail_r"],
        )
        tp = lv["take_profit"]
        ttp_dist = lv["trailing_take_profit_distance"]
        ttp_act = lv["trailing_take_profit_activation_pct"]

    min_buf = exit_cfg.get("min_profit_buffer_pct", 0.0)
    hwm = entry
    for bar in forward_bars:
        hi = float(bar["high"]); lo = float(bar["low"])
        hwm = max(hwm, hi)
        ts_price = exit_eval.compute_trailing_stop_price(hwm, ts_dist)
        ttp_price = exit_eval.compute_trailing_take_profit_price(hwm, entry, ttp_dist, ttp_act, min_buf)
        # adverse first (conservative): test the day's low against downside triggers
        down = exit_eval.downside_close_reason(lo, stop, ts_price)
        if down == "STOP_LOSS":
            return _close(result, stop, entry, risk, "STOP_LOSS")
        if down == "TRAILING_STOP" and ts_price is not None:
            return _close(result, ts_price, entry, risk, "TRAILING_STOP")
        # favorable: test the day's high
        if tp is not None and hi >= tp:
            result["reached_tp"] = True
            return _close(result, tp, entry, risk, "TAKE_PROFIT")
        ttp_reason = exit_eval.trailing_take_profit_close_reason(lo, ttp_price)
        if ttp_reason == "TRAILING_TAKE_PROFIT" and ttp_price is not None:
            return _close(result, ttp_price, entry, risk, "TRAILING_TAKE_PROFIT")
    return result  # never triggered → still open at data end


def _close(result, price, entry, risk, reason):
    result["exit_reason"] = reason
    result["close_price"] = round(price, 8)
    result["realized_r"] = (price - entry) / risk
    return result
