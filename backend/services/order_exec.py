"""Pure order-execution helpers (no broker, no DB)."""

from __future__ import annotations


def is_marketable(ask: float, target: float, max_chase_bps: float) -> bool:
    """True when the current ask is close enough to the target to fill at market.

    Mirrors the live fill rule: fill when ``ask <= target * (1 + max_chase_bps/10_000)``.
    A wider ``max_chase_bps`` accepts more slippage above target and fills more
    orders (fewer ENTRY_TIMEOUT cancellations). Non-positive ask/target never fill.
    """
    if ask <= 0 or target <= 0:
        return False
    ceiling = target * (1.0 + max_chase_bps / 10_000.0)
    return ask <= ceiling
