"""A simple sliding-window rate limiter for the eToro REST client."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class RateLimiter:
    """Sliding-window limiter: at most ``max_calls`` acquisitions per ``period`` seconds.

    ``monotonic`` and ``sleep`` are injectable so tests can drive a fake clock.
    Thread-safe so the scheduler's monitor loop and signal jobs can share one.
    """

    def __init__(
        self,
        max_calls: int,
        period: float,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._max_calls = max(1, int(max_calls))
        self._period = float(period)
        self._monotonic = monotonic
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._monotonic()
            self._evict(now)
            if len(self._calls) >= self._max_calls:
                wait = self._period - (now - self._calls[0])
                if wait > 0:
                    self._sleep(wait)
                now = self._monotonic()
                self._evict(now)
            self._calls.append(now)

    def _evict(self, now: float) -> None:
        while self._calls and (now - self._calls[0]) >= self._period:
            self._calls.popleft()
