import logging
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases, upsert_instrument_mapping, get_instrument_mapping
from core.utils import AppConfig
from clients.etoro_client import EToroClient, EToroAPIError


def make_config(account_type="demo"):
    return AppConfig(
        openai_api_key="k",
        alpaca_api_key="",
        alpaca_secret_key="",
        alpaca_base_url="x",
        etoro_api_key="app-key",
        etoro_user_key="user-key",
        etoro_account_type=account_type,
    )


def make_response(status_code=200, json_body=None):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = "" if json_body is None else str(json_body)
    return resp


def make_client(account_type="demo"):
    session = Mock()
    client = EToroClient(
        make_config(account_type),
        logging.getLogger("test"),
        session=session,
        rate_limiter=Mock(),  # no-op limiter in tests
    )
    return client, session


class EToroFoundationTests(unittest.TestCase):
    def test_headers_include_auth_and_request_id(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"ok": True})
        client._request("GET", "/api/v1/me")
        _, kwargs = session.request.call_args
        headers = kwargs["headers"]
        self.assertEqual(headers["x-api-key"], "app-key")
        self.assertEqual(headers["x-user-key"], "user-key")
        self.assertTrue(headers["x-request-id"])  # non-empty GUID

    def test_each_request_gets_a_unique_request_id(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {})
        client._request("GET", "/a")
        client._request("GET", "/b")
        first = session.request.call_args_list[0].kwargs["headers"]["x-request-id"]
        second = session.request.call_args_list[1].kwargs["headers"]["x-request-id"]
        self.assertNotEqual(first, second)

    def test_4xx_raises_and_is_not_retried(self):
        client, session = make_client()
        session.request.return_value = make_response(400, {"error": "bad"})
        with self.assertRaises(EToroAPIError):
            client._request("POST", "/x", json_body={"a": 1})
        self.assertEqual(session.request.call_count, 1)  # fail-fast, no retry

    def test_demo_vs_real_mode(self):
        demo, _ = make_client("demo")
        real, _ = make_client("real")
        self.assertEqual(demo._mode_segment(), "demo/")
        self.assertEqual(real._mode_segment(), "")


class EToroMarketDataTests(unittest.TestCase):
    def test_get_rate_returns_bid_ask(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {
            "rates": [{"instrumentID": 101, "ask": 10.5, "bid": 10.4, "lastExecution": 10.45}]
        })
        quote = client.get_rate_by_instrument(101)
        self.assertEqual(quote["ask_price"], 10.5)
        self.assertEqual(quote["bid_price"], 10.4)
        self.assertEqual(quote["last_price"], 10.45)

    def test_get_candles_normalizes_bars(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {
            "candles": [{
                "instrumentId": 101,
                "candles": [
                    {"fromDate": "2026-01-01T00:00:00Z", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
                    {"fromDate": "2026-01-02T00:00:00Z", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 200.0},
                ],
            }]
        })
        bars = client.get_candles_by_instrument(101, "AAPL", count=2)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["symbol"], "AAPL")
        self.assertEqual(bars[0]["close"], 1.5)
        self.assertTrue(bars[0]["timestamp"].startswith("2026-01-01"))
        self.assertLess(bars[0]["timestamp"], bars[1]["timestamp"])


class EToroInstrumentTests(unittest.TestCase):
    def test_resolve_instrument_by_symbol(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {
            "instrumentId": 101,
            "symbol": "AAPL",
            "instrumentType": "Stocks",
            "displayname": "Apple Inc",
            "isCurrentlyTradable": True,
            "isBuyEnabled": True,
        })
        asset = client.resolve_instrument("aapl")
        self.assertEqual(asset["instrument_id"], 101)
        self.assertEqual(asset["symbol"], "AAPL")
        self.assertEqual(asset["category"], "STOCK")
        self.assertTrue(asset["tradable"])

    def test_resolve_instrument_crypto_category(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {
            "instrumentId": 100000, "symbol": "BTC", "instrumentType": "Crypto",
            "displayname": "Bitcoin", "isCurrentlyTradable": True, "isBuyEnabled": True,
        })
        asset = client.resolve_instrument("BTC")
        self.assertEqual(asset["category"], "CRYPTO")

    def test_resolve_missing_returns_none(self):
        client, session = make_client()
        session.request.return_value = make_response(404, {})
        self.assertIsNone(client.resolve_instrument("NOPE"))


class EToroAccountTests(unittest.TestCase):
    def _portfolio_response(self):
        return make_response(200, {
            "clientPortfolio": {
                "credit": 1000.0,
                "orders": [],
                "positions": [
                    {"positionID": "p1", "instrumentID": 101, "units": 2.0,
                     "openRate": 50.0, "amount": 100.0, "isBuy": True, "leverage": 1,
                     "stopLossRate": 45.0, "takeProfitRate": 60.0},
                ],
            }
        })

    def test_get_available_cash(self):
        client, session = make_client()
        session.request.return_value = self._portfolio_response()
        self.assertEqual(client.get_available_cash(), 1000.0)

    def test_list_open_positions_normalizes(self):
        client, session = make_client()
        session.request.return_value = self._portfolio_response()
        positions = client.list_open_positions()
        self.assertEqual(len(positions), 1)
        p = positions[0]
        self.assertEqual(p["position_id"], "p1")
        self.assertEqual(p["instrument_id"], 101)
        self.assertEqual(p["units"], 2.0)
        self.assertEqual(p["open_rate"], 50.0)
        self.assertTrue(p["is_buy"])

    def test_account_equity_adds_market_value(self):
        client, session = make_client()
        session.request.side_effect = [
            self._portfolio_response(),
            make_response(200, {"rates": [{"instrumentID": 101, "bid": 55.0, "ask": 55.2, "lastExecution": 55.1}]}),
        ]
        equity = client.get_account_equity()
        # credit 1000 + 2 units * 55.0 bid = 1110
        self.assertEqual(equity, 1110.0)


class EToroOrderTests(unittest.TestCase):
    def test_open_market_position_builds_correct_body(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {"orderId": "o1", "referenceId": "ref-1"})
        result = client.open_market_position(
            instrument_id=101, symbol="AAPL", amount_usd=250.0,
            stop_loss_rate=90.0, take_profit_rate=130.0, leverage=1,
        )
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/api/v2/trading/execution/demo/orders"))
        body = kwargs["json"]
        self.assertEqual(body["action"], "open")
        self.assertEqual(body["transaction"], "buy")
        self.assertEqual(body["instrumentId"], 101)
        self.assertEqual(body["orderType"], "mkt")
        self.assertEqual(body["amount"], 250.0)
        self.assertEqual(body["orderCurrency"], "usd")
        self.assertEqual(body["leverage"], 1)
        self.assertEqual(body["stopLossRate"], 90.0)
        self.assertEqual(body["takeProfitRate"], 130.0)
        self.assertEqual(body["stopLossType"], "fixed")
        self.assertEqual(result["order_id"], "o1")
        self.assertEqual(result["reference_id"], "ref-1")

    def test_close_position_market_builds_body(self):
        client, session = make_client("real")
        session.request.return_value = make_response(200, {"orderId": "c1"})
        result = client.close_position_market("p1")
        args, kwargs = session.request.call_args
        self.assertTrue(args[1].endswith("/api/v2/trading/execution/orders"))
        body = kwargs["json"]
        self.assertEqual(body["action"], "close")
        self.assertEqual(body["positionIds"], ["p1"])
        self.assertEqual(result["order_id"], "c1")

    def test_open_uses_request_id_as_idempotency_key(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"orderId": "o1"})
        result = client.open_market_position(
            instrument_id=101, symbol="AAPL", amount_usd=100.0,
            stop_loss_rate=90.0, take_profit_rate=130.0, leverage=1,
        )
        sent_request_id = session.request.call_args.kwargs["headers"]["x-request-id"]
        self.assertEqual(result["request_id"], sent_request_id)


class EToroResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "trades.sqlite")
        initialize_databases(self.market_db, self.trades_db)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def test_resolution_cache_hit_skips_http(self):
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple", True)
        client, session = self._client()
        self.assertEqual(client.instrument_id_for_symbol("AAPL"), 101)
        session.request.assert_not_called()

    def test_resolution_miss_calls_api_and_caches(self):
        client, session = self._client()
        session.request.return_value = make_response(200, {
            "instrumentId": 100000, "symbol": "BTC", "instrumentType": "Crypto",
            "displayname": "Bitcoin", "isCurrentlyTradable": True, "isBuyEnabled": True,
        })
        self.assertEqual(client.instrument_id_for_symbol("BTC"), 100000)
        cached = get_instrument_mapping(self.market_db, "BTC")
        self.assertEqual(cached["instrument_id"], 100000)
        self.assertEqual(cached["category"], "CRYPTO")

    def test_resolution_unknown_returns_none(self):
        client, session = self._client()
        session.request.return_value = make_response(404, {})
        self.assertIsNone(client.instrument_id_for_symbol("NOPE"))


class EToroBarsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        initialize_databases(self.market_db, str(Path(self.tmp.name) / "t.sqlite"))
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple", True)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def _candles_response(self):
        return make_response(200, {"candles": [{"instrumentId": 101, "candles": [
            {"fromDate": "2026-01-01T00:00:00Z", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
            {"fromDate": "2026-06-01T00:00:00Z", "open": 2, "high": 3, "low": 1.5, "close": 2.5, "volume": 20},
        ]}]})

    def test_get_bars_filters_by_start(self):
        client, session = self._client()
        session.request.return_value = self._candles_response()
        start = datetime(2026, 3, 1, tzinfo=UTC)
        bars = client.get_bars(symbol="AAPL", category="STOCK", start=start)
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0]["close"], 2.5)
        self.assertEqual(bars[0]["symbol"], "AAPL")

    def test_get_bars_unknown_symbol_returns_empty(self):
        client, session = self._client()
        session.request.return_value = make_response(404, {})
        bars = client.get_bars(symbol="NOPE", category="STOCK", start=datetime(2026, 1, 1, tzinfo=UTC))
        self.assertEqual(bars, [])

    def test_get_multi_bars_keys_every_requested_symbol(self):
        client, session = self._client()
        session.request.return_value = self._candles_response()
        out = client.get_multi_bars(["AAPL"], "STOCK", datetime(2025, 1, 1, tzinfo=UTC))
        self.assertIn("AAPL", out)
        self.assertEqual(len(out["AAPL"]), 2)


class EToroPriceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        initialize_databases(self.market_db, str(Path(self.tmp.name) / "t.sqlite"))
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple", True)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def _rate(self):
        return make_response(200, {"rates": [{"instrumentID": 101, "ask": 10.5, "bid": 10.4, "lastExecution": 10.45}]})

    def test_get_latest_price_uses_last_execution(self):
        client, session = self._client()
        session.request.return_value = self._rate()
        self.assertEqual(client.get_latest_price("AAPL", "STOCK"), 10.45)

    def test_get_latest_quote_maps_bid_ask(self):
        client, session = self._client()
        session.request.return_value = self._rate()
        quote = client.get_latest_quote("AAPL", "STOCK")
        self.assertEqual(quote["bid_price"], 10.4)
        self.assertEqual(quote["ask_price"], 10.5)
        self.assertIsNone(quote["bid_size"])
        self.assertIsNone(quote["ask_size"])

    def test_get_latest_price_unknown_symbol_raises(self):
        client, session = self._client()
        session.request.return_value = make_response(404, {})
        with self.assertRaises(EToroAPIError):
            client.get_latest_price("NOPE", "STOCK")


class EToroPositionLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        initialize_databases(self.market_db, str(Path(self.tmp.name) / "t.sqlite"))
        upsert_instrument_mapping(self.market_db, "AAPL", 101, "STOCK", "Apple", True)

    def tearDown(self):
        self.tmp.cleanup()

    def _client(self):
        client, session = make_client()
        client.config.db_market_data = self.market_db
        return client, session

    def _portfolio(self, instrument_id):
        return make_response(200, {"clientPortfolio": {"credit": 100.0, "orders": [], "positions": [
            {"positionID": "p1", "instrumentID": instrument_id, "units": 2.0, "openRate": 50.0,
             "amount": 100.0, "isBuy": True, "leverage": 1, "stopLossRate": 45.0, "takeProfitRate": 60.0},
        ]}})

    def test_get_open_position_match(self):
        client, session = self._client()
        session.request.return_value = self._portfolio(101)
        pos = client.get_open_position("AAPL")
        self.assertIsNotNone(pos)
        self.assertEqual(pos["position_id"], "p1")
        self.assertEqual(pos["symbol"], "AAPL")

    def test_get_open_position_no_match(self):
        client, session = self._client()
        session.request.return_value = self._portfolio(999)
        self.assertIsNone(client.get_open_position("AAPL"))


if __name__ == "__main__":
    unittest.main()
