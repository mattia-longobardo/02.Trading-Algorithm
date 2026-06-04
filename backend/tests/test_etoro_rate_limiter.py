import unittest

from clients.etoro_rate_limiter import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_allows_up_to_capacity_without_sleeping(self):
        clock = FakeClock()
        limiter = RateLimiter(max_calls=3, period=60.0, monotonic=clock.monotonic, sleep=clock.sleep)
        for _ in range(3):
            limiter.acquire()
        self.assertEqual(clock.slept, [])

    def test_blocks_when_capacity_exceeded(self):
        clock = FakeClock()
        limiter = RateLimiter(max_calls=2, period=60.0, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()  # third call must wait until the window rolls
        self.assertEqual(len(clock.slept), 1)
        self.assertAlmostEqual(clock.slept[0], 60.0)

    def test_window_slides(self):
        clock = FakeClock()
        limiter = RateLimiter(max_calls=2, period=60.0, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        limiter.acquire()
        clock.now += 61.0  # both timestamps expire
        limiter.acquire()
        self.assertEqual(clock.slept, [])


if __name__ == "__main__":
    unittest.main()
