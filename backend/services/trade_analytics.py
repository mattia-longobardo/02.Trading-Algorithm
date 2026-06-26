# backend/services/trade_analytics.py
"""Pure R-multiple analytics for trade open/close logging. No DB, no I/O."""

from __future__ import annotations


def planned_metrics(entry_price: float, stop_loss: float, take_profit: float | None) -> dict:
    risk = entry_price - stop_loss
    if entry_price <= 0 or risk <= 0:
        return {"risk_per_unit": 0.0, "reward_risk": None}
    reward_risk = None
    if take_profit is not None and take_profit > entry_price:
        reward_risk = (take_profit - entry_price) / risk
    return {"risk_per_unit": round(risk, 8), "reward_risk": reward_risk}


def realized_r(entry_price: float, stop_loss: float, close_price: float) -> float | None:
    risk = entry_price - stop_loss
    if entry_price <= 0 or risk <= 0:
        return None
    return (close_price - entry_price) / risk


def excursion_r(entry_price: float, stop_loss: float, water_mark: float) -> float | None:
    """Excursion from entry to a high/low water mark, in R-multiples.

    Positive for a favorable mark (MFE), negative for an adverse one (MAE).
    None when not a valid long (entry <= stop or entry <= 0).
    """
    risk = entry_price - stop_loss
    if entry_price <= 0 or risk <= 0:
        return None
    return (water_mark - entry_price) / risk
