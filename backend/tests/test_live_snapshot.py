"""Tests for services.live_snapshot.LiveSnapshotCache.

Follows the project's unittest.TestCase style with sys.modules stubs for
heavy optional deps (dotenv), matching test_etoro_equity_snapshots.py.

Clock injection (monotonic=) mirrors the RateLimiter's ``monotonic`` pattern
so TTL behavior can be driven deterministically without sleeping.
"""

import sys
import unittest
from types import ModuleType

# -- stub heavy optional deps that are not installed in the host venv --------
dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

# ---------------------------------------------------------------------------

from core.utils import PROVIDER_ETORO, AppConfig  # noqa: E402
from services.live_snapshot import LiveSnapshotCache  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------

def _make_trade(
    id: int,
    symbol: str,
    category: str = "CRYPTO",
    entry_price: float = 100.0,
    current_price: float = 110.0,
    quantity: float = 2.0,
    pnl: float = 20.0,
    take_profit: float | None = 130.0,
    stop_loss: float | None = 90.0,
    position_id: str | None = "pos1",
    instrument_id: int | None = 42,
    account_currency: str = "USD",
    unrealized_pnl: float | None = None,
) -> dict:
    return {
        "id": id,
        "symbol": symbol,
        "category": category,
        "status": "OPEN",
        "entry_price": entry_price,
        "current_price": current_price,
        "quantity": quantity,
        "pnl": pnl,
        "unrealized_pnl": unrealized_pnl if unrealized_pnl is not None else pnl,
        "take_profit": take_profit,
        "stop_loss": stop_loss,
        "position_id": position_id,
        "instrument_id": instrument_id,
        "account_currency": account_currency,
    }


TRADE_A = _make_trade(1, "BTC", entry_price=100.0, current_price=110.0, quantity=2.0, pnl=20.0)
TRADE_B = _make_trade(2, "ETH", category="CRYPTO", entry_price=50.0, current_price=55.0, quantity=4.0, pnl=20.0)


class FakeMetrics:
    """Returns a fixed list of trades; tracks call count."""

    def __init__(self, items: list):
        self._items = items
        self.list_trades_calls = 0

    def list_trades(self, **kwargs) -> dict:
        self.list_trades_calls += 1
        return {"items": list(self._items)}


class FakeBroker:
    """Returns configurable quotes and account values; tracks call counts."""

    def __init__(
        self,
        quotes: dict | None = None,  # symbol -> {"bid_price": x, "ask_price": y}
        equity: float = 5000.0,
        cash: float = 1000.0,
        raise_on_quote: set | None = None,  # symbols that raise RuntimeError
    ):
        self._quotes = quotes or {}
        self._equity = equity
        self._cash = cash
        self._raise_on_quote = raise_on_quote or set()
        self.quote_calls = 0
        self.equity_calls = 0
        self.cash_calls = 0

    def get_latest_quote(self, symbol: str, category: str) -> dict:
        self.quote_calls += 1
        if symbol in self._raise_on_quote:
            raise RuntimeError(f"Simulated broker error for {symbol}")
        return self._quotes.get(symbol, {"bid_price": None, "ask_price": None})

    def get_account_equity(self) -> float:
        self.equity_calls += 1
        return self._equity

    def get_available_cash(self) -> float:
        self.cash_calls += 1
        return self._cash


class FakeClock:
    """Mutable monotonic clock for deterministic TTL testing."""

    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_config(**overrides) -> AppConfig:
    cfg = AppConfig(
        openai_api_key="k",
        etoro_api_key="a",
        etoro_user_key="b",
        etoro_account_type="demo",
    )
    for k, v in overrides.items():
        object.__setattr__(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class LiveSnapshotCacheBasicTests(unittest.TestCase):
    """Happy-path: build, shape, live prices, equity/cash."""

    def setUp(self):
        self.clock = FakeClock(start=0.0)
        self.broker = FakeBroker(
            quotes={
                "BTC": {"bid_price": 108.0, "ask_price": 112.0},  # mid = 110.0
                "ETH": {"bid_price": 54.0, "ask_price": None},    # bid only = 54.0
            },
            equity=5000.0,
            cash=1000.0,
        )
        self.metrics = FakeMetrics([TRADE_A, TRADE_B])
        self.config = _make_config(account_currency="USD")
        import logging
        self.cache = LiveSnapshotCache(
            metrics=self.metrics,
            brokers={PROVIDER_ETORO: self.broker},
            config=self.config,
            logger=logging.getLogger("test"),
            ttl_seconds=5.0,
            monotonic=self.clock,
        )

    def test_snapshot_has_required_top_level_keys(self):
        snap = self.cache.get_snapshot()
        self.assertIn("ts", snap)
        self.assertIn("currency", snap)
        self.assertIn("equity", snap)
        self.assertIn("cash", snap)
        self.assertIn("positions", snap)

    def test_snapshot_has_two_positions(self):
        snap = self.cache.get_snapshot()
        self.assertEqual(len(snap["positions"]), 2)

    def test_equity_and_cash_populated(self):
        snap = self.cache.get_snapshot()
        self.assertAlmostEqual(snap["equity"], 5000.0)
        self.assertAlmostEqual(snap["cash"], 1000.0)

    def test_currency_from_trade_account_currency(self):
        snap = self.cache.get_snapshot()
        self.assertEqual(snap["currency"], "USD")

    def test_btc_price_is_mid_of_bid_ask(self):
        snap = self.cache.get_snapshot()
        btc = next(p for p in snap["positions"] if p["symbol"] == "BTC")
        # mid of 108 and 112 = 110.0
        self.assertAlmostEqual(btc["current_price"], 110.0)

    def test_btc_unrealized_pnl(self):
        snap = self.cache.get_snapshot()
        btc = next(p for p in snap["positions"] if p["symbol"] == "BTC")
        # (110.0 - 100.0) * 2.0 = 20.0
        self.assertAlmostEqual(btc["unrealized_pnl"], 20.0)

    def test_btc_unrealized_pnl_pct(self):
        snap = self.cache.get_snapshot()
        btc = next(p for p in snap["positions"] if p["symbol"] == "BTC")
        # (110 / 100 - 1) * 100 = 10.0%
        self.assertAlmostEqual(btc["unrealized_pnl_pct"], 10.0)

    def test_eth_price_falls_back_to_bid_only(self):
        snap = self.cache.get_snapshot()
        eth = next(p for p in snap["positions"] if p["symbol"] == "ETH")
        # bid = 54.0, ask = None => use bid
        self.assertAlmostEqual(eth["current_price"], 54.0)

    def test_eth_unrealized_pnl(self):
        snap = self.cache.get_snapshot()
        eth = next(p for p in snap["positions"] if p["symbol"] == "ETH")
        # (54.0 - 50.0) * 4.0 = 16.0
        self.assertAlmostEqual(eth["unrealized_pnl"], 16.0)

    def test_position_has_all_required_fields(self):
        snap = self.cache.get_snapshot()
        pos = snap["positions"][0]
        for field in (
            "id", "symbol", "category", "units", "entry_price",
            "current_price", "unrealized_pnl", "unrealized_pnl_pct",
            "take_profit", "stop_loss", "position_id", "instrument_id",
        ):
            self.assertIn(field, pos, f"Missing field: {field}")


class LiveSnapshotCacheTTLTests(unittest.TestCase):
    """TTL caching: served from cache within window; rebuilt when expired or forced."""

    def setUp(self):
        self.clock = FakeClock(start=0.0)
        self.broker = FakeBroker(
            quotes={"BTC": {"bid_price": 100.0, "ask_price": 102.0}},
        )
        self.metrics = FakeMetrics([TRADE_A])
        import logging
        self.cache = LiveSnapshotCache(
            metrics=self.metrics,
            brokers={PROVIDER_ETORO: self.broker},
            config=_make_config(),
            logger=logging.getLogger("test"),
            ttl_seconds=5.0,
            monotonic=self.clock,
        )

    def test_second_call_within_ttl_does_not_call_broker(self):
        self.cache.get_snapshot()
        calls_after_first = self.broker.quote_calls
        self.clock.advance(2.0)  # within 5 s TTL
        self.cache.get_snapshot()
        self.assertEqual(self.broker.quote_calls, calls_after_first,
                         "Broker should NOT be called again within TTL")

    def test_call_after_ttl_expires_rebuilds(self):
        self.cache.get_snapshot()
        calls_after_first = self.broker.quote_calls
        self.clock.advance(6.0)  # past 5 s TTL
        self.cache.get_snapshot()
        self.assertGreater(self.broker.quote_calls, calls_after_first,
                           "Broker SHOULD be called again after TTL expires")

    def test_force_true_rebuilds_within_ttl(self):
        self.cache.get_snapshot()
        calls_after_first = self.broker.quote_calls
        self.clock.advance(1.0)  # well within TTL
        self.cache.get_snapshot(force=True)
        self.assertGreater(self.broker.quote_calls, calls_after_first,
                           "force=True should bypass TTL and rebuild")

    def test_metrics_list_trades_called_only_once_within_ttl(self):
        self.cache.get_snapshot()
        self.clock.advance(2.0)
        self.cache.get_snapshot()
        self.assertEqual(self.metrics.list_trades_calls, 1)

    def test_metrics_list_trades_called_again_after_ttl(self):
        self.cache.get_snapshot()
        self.clock.advance(10.0)
        self.cache.get_snapshot()
        self.assertEqual(self.metrics.list_trades_calls, 2)


class LiveSnapshotCacheFallbackTests(unittest.TestCase):
    """Error handling: broker failures fall back to stored values without raising."""

    def setUp(self):
        self.clock = FakeClock(start=0.0)
        import logging
        self.logger = logging.getLogger("test")

    def test_broker_raises_on_quote_still_returns_snapshot(self):
        broker = FakeBroker(raise_on_quote={"BTC", "ETH"})
        metrics = FakeMetrics([TRADE_A, TRADE_B])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=self.clock,
        )
        # Must not raise
        snap = cache.get_snapshot()
        self.assertIsNotNone(snap)
        self.assertEqual(len(snap["positions"]), 2)

    def test_broker_fallback_uses_stored_current_price(self):
        """When get_latest_quote raises, position uses trade's current_price."""
        broker = FakeBroker(raise_on_quote={"BTC"})
        trade = _make_trade(1, "BTC", entry_price=100.0, current_price=115.0, pnl=30.0, quantity=2.0)
        metrics = FakeMetrics([trade])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=self.clock,
        )
        snap = cache.get_snapshot()
        pos = snap["positions"][0]
        self.assertAlmostEqual(pos["current_price"], 115.0)
        # unrealized_pnl falls back to stored trade pnl on error
        self.assertAlmostEqual(pos["unrealized_pnl"], 30.0)

    def test_mixed_one_symbol_raises_other_succeeds(self):
        """Only the erroring symbol falls back; the good one gets live price."""
        broker = FakeBroker(
            quotes={"ETH": {"bid_price": 60.0, "ask_price": 62.0}},
            raise_on_quote={"BTC"},
        )
        metrics = FakeMetrics([TRADE_A, TRADE_B])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=self.clock,
        )
        snap = cache.get_snapshot()
        btc = next(p for p in snap["positions"] if p["symbol"] == "BTC")
        eth = next(p for p in snap["positions"] if p["symbol"] == "ETH")
        # BTC fell back
        self.assertAlmostEqual(btc["current_price"], TRADE_A["current_price"])
        # ETH got live mid price
        self.assertAlmostEqual(eth["current_price"], 61.0)

    def test_equity_failure_returns_none(self):
        class BrokenEquityBroker(FakeBroker):
            def get_account_equity(self):
                raise RuntimeError("equity call failed")

        broker = BrokenEquityBroker()
        metrics = FakeMetrics([TRADE_A])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=self.clock,
        )
        snap = cache.get_snapshot()
        self.assertIsNone(snap["equity"])

    def test_cash_failure_returns_none(self):
        class BrokenCashBroker(FakeBroker):
            def get_available_cash(self):
                raise RuntimeError("cash call failed")

        broker = BrokenCashBroker()
        metrics = FakeMetrics([TRADE_A])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=self.clock,
        )
        snap = cache.get_snapshot()
        self.assertIsNone(snap["cash"])


class LiveSnapshotCacheNoBrokerTests(unittest.TestCase):
    """When no broker is configured, snapshot is built from DB values only."""

    def test_no_broker_snapshot_has_none_equity_and_cash(self):
        import logging
        metrics = FakeMetrics([TRADE_A, TRADE_B])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={},  # eToro not in brokers dict
            config=_make_config(),
            logger=logging.getLogger("test"),
            ttl_seconds=5.0,
            monotonic=FakeClock(),
        )
        snap = cache.get_snapshot()
        self.assertIsNone(snap["equity"])
        self.assertIsNone(snap["cash"])

    def test_no_broker_still_returns_positions_from_db(self):
        import logging
        metrics = FakeMetrics([TRADE_A, TRADE_B])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={},
            config=_make_config(),
            logger=logging.getLogger("test"),
            ttl_seconds=5.0,
            monotonic=FakeClock(),
        )
        snap = cache.get_snapshot()
        self.assertEqual(len(snap["positions"]), 2)
        btc = next(p for p in snap["positions"] if p["symbol"] == "BTC")
        # Uses stored current_price
        self.assertAlmostEqual(btc["current_price"], TRADE_A["current_price"])

    def test_no_broker_currency_falls_back_to_config(self):
        import logging
        metrics = FakeMetrics([])
        cfg = _make_config(account_currency="EUR")
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={},
            config=cfg,
            logger=logging.getLogger("test"),
            ttl_seconds=5.0,
            monotonic=FakeClock(),
        )
        snap = cache.get_snapshot()
        self.assertEqual(snap["currency"], "EUR")


class LiveSnapshotCacheEdgeCaseTests(unittest.TestCase):
    """Edge cases: empty trade list, zero-entry price, ask-only quotes."""

    def setUp(self):
        import logging
        self.logger = logging.getLogger("test")

    def test_empty_positions_list(self):
        broker = FakeBroker()
        metrics = FakeMetrics([])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=FakeClock(),
        )
        snap = cache.get_snapshot()
        self.assertEqual(snap["positions"], [])

    def test_ask_only_quote_used_when_no_bid(self):
        broker = FakeBroker(
            quotes={"BTC": {"bid_price": None, "ask_price": 120.0}},
        )
        metrics = FakeMetrics([TRADE_A])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=FakeClock(),
        )
        snap = cache.get_snapshot()
        btc = snap["positions"][0]
        self.assertAlmostEqual(btc["current_price"], 120.0)

    def test_unrealized_pnl_pct_is_none_when_entry_price_is_zero(self):
        trade = _make_trade(1, "BTC", entry_price=0.0, current_price=50.0, quantity=1.0, pnl=0.0)
        broker = FakeBroker(quotes={"BTC": {"bid_price": 50.0, "ask_price": 50.0}})
        metrics = FakeMetrics([trade])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=FakeClock(),
        )
        snap = cache.get_snapshot()
        self.assertIsNone(snap["positions"][0]["unrealized_pnl_pct"])

    def test_no_quote_both_none_falls_back_to_stored_current_price(self):
        """Broker returns {bid:None, ask:None} — fall through to trade's stored price."""
        broker = FakeBroker(quotes={"BTC": {"bid_price": None, "ask_price": None}})
        trade = _make_trade(1, "BTC", entry_price=100.0, current_price=105.0, quantity=1.0, pnl=5.0)
        metrics = FakeMetrics([trade])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
            ttl_seconds=5.0,
            monotonic=FakeClock(),
        )
        snap = cache.get_snapshot()
        self.assertAlmostEqual(snap["positions"][0]["current_price"], 105.0)


if __name__ == "__main__":
    unittest.main()
