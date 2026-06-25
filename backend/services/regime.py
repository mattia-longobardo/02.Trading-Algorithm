"""Market-regime entry gate: only open longs in an up-regime (price >= SMA).

Pure and fail-open: when history is too short to form the SMA the gate returns
True so a thin-data symbol is never silently blocked. The caller supplies bars
(ascending or not) as {"close": ...} dicts and optionally the live price.
"""

from __future__ import annotations


def _closes(bars: list[dict]) -> list[float]:
    out: list[float] = []
    for bar in bars:
        raw = bar.get("close")
        try:
            close = float(raw)
        except (TypeError, ValueError):
            continue
        if close > 0:
            out.append(close)
    return out


def passes_regime_gate(
    bars: list[dict], sma_period: int, current_price: float | None = None
) -> bool:
    closes = _closes(bars)
    if sma_period <= 0 or len(closes) < sma_period:
        return True  # fail-open: insufficient history
    window = closes[-sma_period:]
    sma = sum(window) / len(window)
    price = current_price if (current_price is not None and current_price > 0) else closes[-1]
    return price >= sma
