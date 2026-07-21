"""Rate limiter a finestra scorrevole per i pool condivisi dell'API eToro.

I limiti eToro sono per pool condivisi, non per endpoint (docs/etoro_api.md §2):
execution 20/60s, order-info/portfolio 60/60s, market-data 120/60s, default
60/60s. Il limiter usa solo l'80% del budget come margine di sicurezza, così il
pacing preventivo evita i 429 anche con piccole derive di clock lato server.
Thread-safe: API, scheduler e run girano in concorrenza sullo stesso client.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

# pool -> (budget, finestra in secondi) — vedi docs/etoro_api.md §2
POOL_BUDGETS: dict[str, tuple[int, float]] = {
    "execution": (20, 60.0),
    "trading-info": (60, 60.0),
    "market-data": (120, 60.0),
    "default": (60, 60.0),
}

SAFETY_FACTOR = 0.8


class RateLimiter:
    """Finestra scorrevole per pool: blocca (sleep) finché non c'è budget."""

    def __init__(
        self,
        budgets: dict[str, tuple[int, float]] | None = None,
        safety_factor: float = SAFETY_FACTOR,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._budgets: dict[str, tuple[int, float]] = {
            pool: (max(1, int(limit * safety_factor)), window)
            for pool, (limit, window) in (budgets or POOL_BUDGETS).items()
        }
        self._events: dict[str, deque[float]] = {pool: deque() for pool in self._budgets}
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleep

    def acquire(self, pool: str = "default") -> None:
        """Consuma uno slot del pool; attende se la finestra è piena."""
        if pool not in self._budgets:
            pool = "default"
        limit, window = self._budgets[pool]
        events = self._events[pool]
        while True:
            with self._lock:
                now = self._clock()
                while events and now - events[0] >= window:
                    events.popleft()
                if len(events) < limit:
                    events.append(now)
                    return
                wait = window - (now - events[0])
            self._sleep(max(wait, 0.01))
