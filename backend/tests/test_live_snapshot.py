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
    is_buy: bool = True,
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
        "is_buy": is_buy,
    }


# Instrument IDs differ so the rate_map can distinguish them.
TRADE_A = _make_trade(1, "BTC", entry_price=100.0, current_price=110.0, quantity=2.0, pnl=20.0, instrument_id=1)
TRADE_B = _make_trade(2, "ETH", category="CRYPTO", entry_price=50.0, current_price=55.0, quantity=4.0, pnl=20.0, instrument_id=2)


class FakeMetrics:
    """Returns a fixed list of trades; tracks call count."""

    def __init__(self, items: list):
        self._items = items
        self.list_trades_calls = 0

    def list_trades(self, **kwargs) -> dict:
        self.list_trades_calls += 1
        return {"items": list(self._items)}


class FakeBroker:
    """Returns configurable rates and portfolio; tracks call counts.

    Replaces the old per-symbol ``get_latest_quote`` / ``get_account_equity``
    / ``get_available_cash`` interface with the new batched API:

    - ``get_rates_by_instruments(ids)`` — returns a rate map keyed by int id.
    - ``get_portfolio()`` — returns a portfolio dict with ``credit``,
      ``positions``, and ``orders``.
    """

    def __init__(
        self,
        # instrument_id (int) -> {"bid": x, "ask": y, "lastExecution": z}
        rates: dict | None = None,
        credit: float = 5000.0,
        broker_positions: list | None = None,  # raw broker positions
        orders: list | None = None,
        raise_on_rates: bool = False,
        raise_on_portfolio: bool = False,
    ):
        self._rates = rates or {}
        self._credit = credit
        self._broker_positions = broker_positions or []
        self._orders = orders or []
        self._raise_on_rates = raise_on_rates
        self._raise_on_portfolio = raise_on_portfolio
        self.rates_calls = 0
        self.portfolio_calls = 0

    def get_rates_by_instruments(self, instrument_ids: list[int]) -> dict[int, dict]:
        self.rates_calls += 1
        if self._raise_on_rates:
            raise RuntimeError("Simulated rates error")
        result = {}
        for iid in instrument_ids:
            if iid in self._rates:
                result[iid] = self._rates[iid]
        return result

    def get_portfolio(self) -> dict:
        self.portfolio_calls += 1
        if self._raise_on_portfolio:
            raise RuntimeError("Simulated portfolio error")
        return {
            "credit": self._credit,
            "positions": list(self._broker_positions),
            "orders": list(self._orders),
        }

    @property
    def total_broker_calls(self) -> int:
        """Total number of broker GET-style calls made."""
        return self.rates_calls + self.portfolio_calls


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


def _make_rates_for_trades(*trades: dict, bid_offset: float = 0.0, ask_offset: float = 0.0) -> dict:
    """Build a rate map for a list of trades (mid price = current_price)."""
    rates = {}
    for t in trades:
        iid = t.get("instrument_id")
        if iid is None:
            continue
        price = float(t.get("current_price") or t.get("entry_price") or 100.0)
        rates[iid] = {
            "bid": price + bid_offset,
            "ask": price + ask_offset,
            "lastExecution": price,
        }
    return rates


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class LiveSnapshotCacheBasicTests(unittest.TestCase):
    """Happy-path: build, shape, live prices, equity/cash."""

    def setUp(self):
        self.clock = FakeClock(start=0.0)
        # BTC: instrument_id=1, mid = (108+112)/2 = 110.0
        # ETH: instrument_id=2, bid=54, ask=None → use bid=54.0
        self.broker = FakeBroker(
            rates={
                1: {"bid": 108.0, "ask": 112.0, "lastExecution": 110.0},
                2: {"bid": 54.0, "ask": None, "lastExecution": 54.0},
            },
            credit=5000.0,
            broker_positions=[
                {"instrumentID": 1, "units": 2.0, "openRate": 100.0},
                {"instrumentID": 2, "units": 4.0, "openRate": 50.0},
            ],
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

    def test_equity_populated(self):
        snap = self.cache.get_snapshot()
        # equity = credit(5000) + BTC(2 * bid108=216) + ETH(4 * bid54=216)
        # = 5000 + 216 + 216 = 5432
        self.assertIsNotNone(snap["equity"])
        self.assertAlmostEqual(snap["equity"], 5000.0 + 2.0 * 108.0 + 4.0 * 54.0)

    def test_cash_populated(self):
        snap = self.cache.get_snapshot()
        # no pending orders → cash = credit = 5000
        self.assertAlmostEqual(snap["cash"], 5000.0)

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
            "id", "symbol", "category", "is_buy", "units", "entry_price",
            "current_price", "unrealized_pnl", "unrealized_pnl_pct",
            "take_profit", "stop_loss", "position_id", "instrument_id",
        ):
            self.assertIn(field, pos, f"Missing field: {field}")

    def test_is_buy_defaults_true(self):
        snap = self.cache.get_snapshot()
        btc = next(p for p in snap["positions"] if p["symbol"] == "BTC")
        self.assertIs(btc["is_buy"], True)


class LiveSnapshotCacheBrokerCallBoundTests(unittest.TestCase):
    """Key rate-limit invariant: at most 2 broker GETs per rebuild."""

    def _make_many_trades(self, n: int) -> list[dict]:
        """Create n distinct open trades with unique instrument IDs."""
        trades = []
        for i in range(n):
            trades.append(_make_trade(
                id=i + 1,
                symbol=f"SYM{i}",
                instrument_id=i + 100,
                entry_price=100.0,
                current_price=105.0,
                quantity=1.0,
                pnl=5.0,
            ))
        return trades

    def test_at_most_two_broker_calls_for_three_positions(self):
        """Regardless of position count, rebuild must make ≤ 2 broker GETs."""
        trades = self._make_many_trades(3)
        rates = {t["instrument_id"]: {"bid": 105.0, "ask": 106.0, "lastExecution": 105.5}
                 for t in trades}
        broker = FakeBroker(rates=rates, credit=10000.0)
        import logging
        cache = LiveSnapshotCache(
            metrics=FakeMetrics(trades),
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=logging.getLogger("test"),
        )
        cache.get_snapshot()
        self.assertLessEqual(
            broker.total_broker_calls, 2,
            f"Expected ≤ 2 broker calls for 3 positions but got {broker.total_broker_calls}",
        )

    def test_at_most_two_broker_calls_for_ten_positions(self):
        """Scaling to 10 positions still must not exceed 2 broker GETs."""
        trades = self._make_many_trades(10)
        rates = {t["instrument_id"]: {"bid": 105.0, "ask": 106.0, "lastExecution": 105.5}
                 for t in trades}
        broker = FakeBroker(rates=rates, credit=10000.0)
        import logging
        cache = LiveSnapshotCache(
            metrics=FakeMetrics(trades),
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=logging.getLogger("test"),
        )
        cache.get_snapshot()
        self.assertLessEqual(
            broker.total_broker_calls, 2,
            f"Expected ≤ 2 broker calls for 10 positions but got {broker.total_broker_calls}",
        )

    def test_rates_call_is_exactly_one_per_rebuild(self):
        trades = self._make_many_trades(5)
        rates = {t["instrument_id"]: {"bid": 100.0, "ask": 101.0, "lastExecution": 100.5}
                 for t in trades}
        broker = FakeBroker(rates=rates, credit=1000.0)
        import logging
        cache = LiveSnapshotCache(
            metrics=FakeMetrics(trades),
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=logging.getLogger("test"),
        )
        cache.get_snapshot()
        self.assertEqual(broker.rates_calls, 1,
                         "get_rates_by_instruments should be called exactly once per rebuild")
        self.assertEqual(broker.portfolio_calls, 1,
                         "get_portfolio should be called exactly once per rebuild")


class LiveSnapshotCacheTTLTests(unittest.TestCase):
    """TTL caching: served from cache within window; rebuilt when expired or forced."""

    def setUp(self):
        self.clock = FakeClock(start=0.0)
        self.broker = FakeBroker(
            rates={1: {"bid": 100.0, "ask": 102.0, "lastExecution": 101.0}},
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
        calls_after_first = self.broker.total_broker_calls
        self.clock.advance(2.0)  # within 5 s TTL
        self.cache.get_snapshot()
        self.assertEqual(self.broker.total_broker_calls, calls_after_first,
                         "Broker should NOT be called again within TTL")

    def test_call_after_ttl_expires_rebuilds(self):
        self.cache.get_snapshot()
        calls_after_first = self.broker.total_broker_calls
        self.clock.advance(6.0)  # past 5 s TTL
        self.cache.get_snapshot()
        self.assertGreater(self.broker.total_broker_calls, calls_after_first,
                           "Broker SHOULD be called again after TTL expires")

    def test_force_true_rebuilds_within_ttl(self):
        self.cache.get_snapshot()
        calls_after_first = self.broker.total_broker_calls
        self.clock.advance(1.0)  # well within TTL
        self.cache.get_snapshot(force=True)
        self.assertGreater(self.broker.total_broker_calls, calls_after_first,
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

    def test_broker_raises_on_rates_still_returns_snapshot(self):
        broker = FakeBroker(raise_on_rates=True)
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

    def test_rates_failure_falls_back_to_stored_current_price(self):
        """When get_rates_by_instruments raises, position uses trade's current_price."""
        broker = FakeBroker(raise_on_rates=True)
        trade = _make_trade(1, "BTC", instrument_id=1, entry_price=100.0, current_price=115.0, pnl=30.0, quantity=2.0)
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
        # unrealized_pnl falls back to stored unrealized_pnl (= pnl = 30)
        self.assertAlmostEqual(pos["unrealized_pnl"], 30.0)

    def test_missing_instrument_id_in_rate_map_falls_back(self):
        """If a trade's instrument_id isn't in the rate map, use stored price."""
        # Rate map only has instrument 99, but TRADE_A has instrument_id=1
        broker = FakeBroker(
            rates={99: {"bid": 999.0, "ask": 1000.0, "lastExecution": 999.5}},
        )
        trade = _make_trade(1, "BTC", instrument_id=1, entry_price=100.0, current_price=115.0, pnl=30.0, quantity=2.0)
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
        # Should use stored current_price since id=1 not in rate map
        self.assertAlmostEqual(pos["current_price"], 115.0)

    def test_portfolio_failure_returns_none_equity_and_cash(self):
        broker = FakeBroker(
            rates={1: {"bid": 110.0, "ask": 112.0, "lastExecution": 111.0}},
            raise_on_portfolio=True,
        )
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
        self.assertIsNone(snap["cash"])

    def test_cash_deducts_pending_orders(self):
        broker = FakeBroker(
            rates={1: {"bid": 110.0, "ask": 112.0, "lastExecution": 111.0}},
            credit=5000.0,
            orders=[{"amount": 200.0}, {"amount": 300.0}],
        )
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
        # cash = 5000 - 200 - 300 = 4500
        self.assertAlmostEqual(snap["cash"], 4500.0)


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

    def test_no_broker_zero_broker_calls(self):
        """No broker → no rates or portfolio calls whatsoever."""
        import logging
        metrics = FakeMetrics([TRADE_A, TRADE_B])
        # Use a real FakeBroker but don't register it
        stray_broker = FakeBroker()
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={},  # empty — broker not registered
            config=_make_config(),
            logger=logging.getLogger("test"),
        )
        cache.get_snapshot()
        self.assertEqual(stray_broker.total_broker_calls, 0)

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
    """Edge cases: empty trade list, zero-entry price, ask-only quotes, shorts."""

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

    def test_empty_positions_no_rates_call(self):
        """No open trades → get_rates_by_instruments must NOT be called (empty id list)."""
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
        cache.get_snapshot()
        self.assertEqual(broker.rates_calls, 0,
                         "No open trades → should skip the rates GET entirely")

    def test_ask_only_quote_used_when_no_bid(self):
        broker = FakeBroker(
            rates={1: {"bid": None, "ask": 120.0, "lastExecution": None}},
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

    def test_last_execution_used_as_fallback_when_no_bid_ask(self):
        broker = FakeBroker(
            rates={1: {"bid": None, "ask": None, "lastExecution": 107.5}},
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
        self.assertAlmostEqual(btc["current_price"], 107.5)

    def test_unrealized_pnl_pct_is_none_when_entry_price_is_zero(self):
        trade = _make_trade(1, "BTC", instrument_id=1, entry_price=0.0, current_price=50.0, quantity=1.0, pnl=0.0)
        broker = FakeBroker(rates={1: {"bid": 50.0, "ask": 50.0, "lastExecution": 50.0}})
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
        """Rate map has all-None bid/ask/last — fall through to trade's stored price."""
        broker = FakeBroker(rates={1: {"bid": None, "ask": None, "lastExecution": None}})
        trade = _make_trade(1, "BTC", instrument_id=1, entry_price=100.0, current_price=105.0, quantity=1.0, pnl=5.0)
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

    def test_short_position_pnl_sign_is_negative_when_price_rises(self):
        """A short (is_buy=False) trade losing money when price rises above entry."""
        # Short BTC: entry=100, current=110, qty=2
        # Expected PnL = (110 - 100) * 2 * -1 = -20
        trade = _make_trade(
            1, "BTC", instrument_id=1,
            entry_price=100.0, current_price=110.0, quantity=2.0, pnl=-20.0,
            is_buy=False,
        )
        broker = FakeBroker(
            rates={1: {"bid": 109.0, "ask": 111.0, "lastExecution": 110.0}},
        )
        metrics = FakeMetrics([trade])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
        )
        snap = cache.get_snapshot()
        pos = snap["positions"][0]
        self.assertIs(pos["is_buy"], False)
        # mid = (109+111)/2 = 110; PnL = (110-100)*2*-1 = -20
        self.assertAlmostEqual(pos["unrealized_pnl"], -20.0)
        # pnl_pct = (110/100 - 1)*100*-1 = -10%
        self.assertAlmostEqual(pos["unrealized_pnl_pct"], -10.0)

    def test_short_position_pnl_sign_is_positive_when_price_falls(self):
        """A short (is_buy=False) trade winning when price drops below entry."""
        # Short BTC: entry=100, live=90, qty=2
        # Expected PnL = (90 - 100) * 2 * -1 = +20
        trade = _make_trade(
            1, "BTC", instrument_id=1,
            entry_price=100.0, current_price=90.0, quantity=2.0, pnl=20.0,
            is_buy=False,
        )
        broker = FakeBroker(
            rates={1: {"bid": 89.0, "ask": 91.0, "lastExecution": 90.0}},
        )
        metrics = FakeMetrics([trade])
        cache = LiveSnapshotCache(
            metrics=metrics,
            brokers={PROVIDER_ETORO: broker},
            config=_make_config(),
            logger=self.logger,
        )
        snap = cache.get_snapshot()
        pos = snap["positions"][0]
        self.assertIs(pos["is_buy"], False)
        # mid = (89+91)/2 = 90; PnL = (90-100)*2*-1 = +20
        self.assertAlmostEqual(pos["unrealized_pnl"], 20.0)
        # pnl_pct = (90/100 - 1)*100*-1 = +10%
        self.assertAlmostEqual(pos["unrealized_pnl_pct"], 10.0)


if __name__ == "__main__":
    unittest.main()
