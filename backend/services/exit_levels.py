"""Deterministic, R-multiple-based normalization of exit levels.

R = entry_price - stop_loss is the per-trade risk unit (a long). GPT proposes
take_profit and trailing-take-profit parameters but historically clipped winners
to ~0.4R; this module clamps those levels to risk multiples so winners are
allowed to run to a configured reward/risk. Pure: no DB, no broker, no I/O.
"""

from __future__ import annotations


def normalize_exit_levels(
    entry_price: float,
    stop_loss: float,
    take_profit: float | None,
    trailing_take_profit_distance: float | None,
    trailing_take_profit_activation_pct: float | None,
    *,
    min_reward_risk: float,
    arm_r: float,
    trail_r: float,
) -> dict:
    """Clamp exit levels to multiples of the initial risk R = entry - stop.

    - take_profit is raised (never lowered) to at least entry + min_reward_risk * R.
    - When a trailing take profit is requested (both inputs set), its activation is
      set to arm_r * R (as a percent of entry) and its distance to trail_r * R, then
      the activation is nudged up so it always exceeds distance/entry*100 (the
      bot's arming invariant: trigger sits above entry the moment it arms).
    - When entry <= stop (not a valid long) inputs are returned unchanged.
    """

    out = {
        "take_profit": take_profit,
        "trailing_take_profit_distance": trailing_take_profit_distance,
        "trailing_take_profit_activation_pct": trailing_take_profit_activation_pct,
    }
    risk = entry_price - stop_loss
    if entry_price <= 0 or risk <= 0:
        return out

    floor_tp = entry_price + min_reward_risk * risk
    if take_profit is None or take_profit < floor_tp:
        out["take_profit"] = round(floor_tp, 8)

    if trailing_take_profit_distance is not None and trailing_take_profit_activation_pct is not None:
        distance = round(trail_r * risk, 8)
        distance_pct = distance / entry_price * 100.0
        activation_pct = arm_r * risk / entry_price * 100.0
        # keep the bot's invariant: activation must clear distance_pct with margin
        activation_pct = max(activation_pct, distance_pct + 0.5)
        out["trailing_take_profit_distance"] = distance
        out["trailing_take_profit_activation_pct"] = round(activation_pct, 8)

    return out
