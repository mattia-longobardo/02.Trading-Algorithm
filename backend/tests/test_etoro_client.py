import logging
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.db import initialize_databases, upsert_instrument_mapping, get_instrument_mapping
from core.utils import AppConfig
from clients.etoro_client import EToroClient, EToroAPIError


def make_config(account_type="demo"):
    return AppConfig(
        openai_api_key="k",
        
        
        
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

    def test_get_rates_by_instruments_sends_literal_commas(self):
        """Regression: eToro's rates endpoint returns 500 for %2C-encoded commas.

        Passing a comma-joined value via requests' ``params`` percent-encodes the
        commas (``instrumentIds=1%2C2%2C3``), which eToro rejects with a 500. A
        live probe confirmed literal commas (``instrumentIds=1,2,3``) return 200.
        The query must therefore reach requests with literal commas (embedded in
        the URL), not as an encodable ``params`` dict.
        """
        client, session = make_client()
        session.request.return_value = make_response(200, {"rates": []})
        client.get_rates_by_instruments([1, 2, 3])
        args, kwargs = session.request.call_args
        url = args[1] if len(args) > 1 else kwargs.get("url", "")
        self.assertIn("instrumentIds=1,2,3", url)
        self.assertNotIn("instrumentIds", str(kwargs.get("params") or ""))

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


class EToroMarketOpenTests(unittest.TestCase):
    def _rates(self, date_iso):
        return make_response(200, {"rates": [
            {"instrumentID": 101, "bid": 10.0, "ask": 10.1, "lastExecution": 10.0, "date": date_iso}
        ]})

    def test_market_open_when_quote_is_fresh(self):
        from core.utils import utc_now, isoformat_utc
        client, session = make_client()
        session.request.return_value = self._rates(isoformat_utc(utc_now()))
        self.assertTrue(client.is_market_open(101))

    def test_market_closed_when_quote_is_stale(self):
        client, session = make_client()
        session.request.return_value = self._rates("2020-01-01T00:00:00Z")
        self.assertFalse(client.is_market_open(101))

    def test_fails_open_on_error(self):
        client, session = make_client()
        session.request.side_effect = EToroAPIError(500, "boom")
        self.assertTrue(client.is_market_open(101))  # don't block trading on a transient error

    def test_fails_open_when_no_rate_row(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"rates": []})
        self.assertTrue(client.is_market_open(101))


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

    def test_resolve_falls_back_to_search_when_direct_route_404s(self):
        # eToro's /instruments/{symbol} route 404s for indices like SPX500;
        # the client must fall back to an exact-match /market-data/search.
        client, session = make_client()

        def fake_request(*args, **kwargs):
            url = "".join(str(a) for a in args) + str(kwargs.get("url", ""))
            if "/market-data/search" in url:
                return make_response(200, {
                    "items": [
                        {
                            "internalSymbolFull": "SPX500.FUT",
                            "instrumentId": 254,
                            "displayname": "SPX500 Future",
                            "isCurrentlyTradable": True,
                            "isBuyEnabled": True,
                        },
                        {
                            "internalSymbolFull": "SPX500",
                            "instrumentId": 27,
                            "displayname": "SPX500 Index (Non Expiry)",
                            "isCurrentlyTradable": True,
                            "isBuyEnabled": True,
                        },
                    ]
                })
            if "/market-data/instrument-types" in url:
                return make_response(200, {
                    "instrumentTypes": [
                        {"instrumentTypeID": 10, "instrumentTypeDescription": "Cryptocurrencies"},
                        {"instrumentTypeID": 4, "instrumentTypeDescription": "Indices"},
                    ]
                })
            if "/market-data/instruments" in url:
                return make_response(200, {
                    "instrumentDisplayDatas": [{"instrumentID": 27, "instrumentTypeID": 4}]
                })
            return make_response(404, {})

        session.request.side_effect = fake_request
        asset = client.resolve_instrument("SPX500")
        self.assertEqual(asset["instrument_id"], 27)
        self.assertEqual(asset["symbol"], "SPX500")
        self.assertEqual(asset["category"], "STOCK")
        self.assertTrue(asset["tradable"])

    def test_resolve_search_fallback_detects_crypto_category(self):
        client, session = make_client()

        def fake_request(*args, **kwargs):
            url = "".join(str(a) for a in args) + str(kwargs.get("url", ""))
            if "/market-data/search" in url:
                return make_response(200, {
                    "items": [{
                        "internalSymbolFull": "NEWCOIN",
                        "instrumentId": 100777,
                        "displayname": "New Coin",
                        "isCurrentlyTradable": True,
                        "isBuyEnabled": True,
                    }]
                })
            if "/market-data/instrument-types" in url:
                return make_response(200, {
                    "instrumentTypes": [
                        {"instrumentTypeID": 10, "instrumentTypeDescription": "Cryptocurrencies"},
                    ]
                })
            if "/market-data/instruments" in url:
                return make_response(200, {
                    "instrumentDisplayDatas": [{"instrumentID": 100777, "instrumentTypeID": 10}]
                })
            return make_response(404, {})

        session.request.side_effect = fake_request
        asset = client.resolve_instrument("NEWCOIN")
        self.assertEqual(asset["category"], "CRYPTO")


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

    def test_account_equity_ignores_null_instrument_id_rate_rows(self):
        """Regression: a rates row with null instrumentID must not crash equity.

        The eToro rates endpoint can return rows without an instrumentID. The
        hardened ``get_rates_by_instruments`` skips them, but ``get_account_equity``
        used to do ``int(None)`` and raise — which ``portfolio_risk_snapshot``
        swallowed into equity=0, zeroing the entire risk score despite open
        positions. Equity must be computed via the same hardened path.
        """
        client, session = make_client()
        session.request.side_effect = [
            self._portfolio_response(),
            make_response(200, {"rates": [
                {"instrumentID": None, "bid": None, "ask": None, "lastExecution": None},
                {"instrumentID": 101, "bid": 55.0, "ask": 55.2, "lastExecution": 55.1},
            ]}),
        ]
        equity = client.get_account_equity()
        # poison row skipped; credit 1000 + 2 units * 55.0 bid = 1110
        self.assertEqual(equity, 1110.0)

    def test_account_equity_falls_back_to_open_rate_when_rates_fail(self):
        """If the rates endpoint fails (e.g. eToro 500), equity must fall back to
        openRate instead of raising — otherwise the failure propagates and the
        risk score is zeroed. Mirrors the live snapshot's rate-failure tolerance.
        """
        client, session = make_client()
        session.request.return_value = self._portfolio_response()
        with patch.object(client, "get_rates_by_instruments", side_effect=EToroAPIError(500, "boom")):
            equity = client.get_account_equity()
        # rates failed → openRate 50.0: credit 1000 + 2 units * 50.0 = 1100
        self.assertEqual(equity, 1100.0)


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
        # eToro rejects orders that supply BOTH symbol and instrumentId
        # ("Exactly one of Symbol or InstrumentID must be provided"); send only
        # the canonical instrumentId.
        self.assertNotIn("symbol", body)
        self.assertEqual(body["settlementType"], "real")
        self.assertEqual(body["orderType"], "mkt")
        self.assertEqual(body["amount"], 250.0)
        self.assertEqual(body["orderCurrency"], "usd")
        self.assertEqual(body["leverage"], 1)
        self.assertEqual(body["stopLossRate"], 90.0)
        self.assertEqual(body["takeProfitRate"], 130.0)
        self.assertEqual(body["stopLossType"], "fixed")
        self.assertEqual(result["order_id"], "o1")
        self.assertEqual(result["reference_id"], "ref-1")

    def test_close_position_market_uses_market_close_endpoint(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {"orderForClose": {"orderID": 42}})
        result = client.close_position_market("p1", instrument_id=100000)
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/api/v1/trading/execution/demo/market-close-orders/positions/p1"))
        body = kwargs["json"]
        self.assertEqual(body["InstrumentID"], 100000)
        self.assertNotIn("UnitsToDeduct", body)
        self.assertEqual(result["raw"]["orderForClose"]["orderID"], 42)
        self.assertEqual(result["order_id"], "42")

    def test_close_position_market_partial_sends_units(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {"orderForClose": {"orderID": 43}})
        client.close_position_market("p2", instrument_id=100000, units=0.5)
        body = session.request.call_args.kwargs["json"]
        self.assertEqual(body["UnitsToDeduct"], 0.5)

    def test_cancel_order_deletes(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {"token": "t1"})
        client.cancel_order("999")
        args, _ = session.request.call_args
        self.assertEqual(args[0], "DELETE")
        self.assertTrue(args[1].endswith("/api/v2/trading/execution/demo/orders/999"))

    def test_open_uses_request_id_as_idempotency_key(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"orderId": "o1"})
        result = client.open_market_position(
            instrument_id=101, symbol="AAPL", amount_usd=100.0,
            stop_loss_rate=90.0, take_profit_rate=130.0, leverage=1,
        )
        sent_request_id = session.request.call_args.kwargs["headers"]["x-request-id"]
        self.assertEqual(result["request_id"], sent_request_id)

    def test_get_order_status_filled(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {
            "orderId": 555, "status": {"id": 3, "name": "Filled", "errorCode": 0, "errorMessage": None},
            "positionExecutions": [{"positionId": 9001, "state": "open"}],
        })
        st = client.get_order_status("555")
        self.assertTrue(st["executed"])
        self.assertFalse(st["rejected"])
        self.assertFalse(st["waiting"])
        self.assertFalse(st["canceled"])
        self.assertEqual(st["position_id"], "9001")
        params = session.request.call_args.kwargs["params"]
        self.assertEqual(params["orderId"], "555")
        self.assertTrue(session.request.call_args.args[1].endswith("/api/v2/trading/info/demo/orders:lookup"))

    def test_get_order_status_rejected(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {
            "orderId": 7, "status": {"id": 4, "name": "Rejected", "errorCode": 759,
                                     "errorMessage": "manual Trading is disallowed for this instrument type(10:CRYPTO)"},
            "positionExecutions": [],
        })
        st = client.get_order_status("7")
        self.assertTrue(st["rejected"])
        self.assertFalse(st["executed"])
        self.assertEqual(st["error_code"], 759)
        self.assertIn("disallowed", st["error_message"])
        self.assertIsNone(st["position_id"])

    def test_get_order_status_waiting(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {
            "orderId": 8, "status": {"id": 11, "name": "WaitingForMarket", "errorCode": 0, "errorMessage": None},
            "positionExecutions": [],
        })
        st = client.get_order_status("8")
        self.assertTrue(st["waiting"])
        self.assertFalse(st["executed"])
        self.assertFalse(st["rejected"])

    def test_get_order_status_not_found(self):
        client, session = make_client("demo")
        session.request.side_effect = EToroAPIError(404, "no operation")
        self.assertIsNone(client.get_order_status("404ref"))

    def test_get_order_status_unknown_name_waits(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {
            "orderId": 9, "status": {"id": 3, "name": "SomethingNew", "errorCode": 0, "errorMessage": None},
            "positionExecutions": [],
        })
        st = client.get_order_status("9")
        self.assertTrue(st["waiting"])
        self.assertFalse(st["executed"])
        self.assertFalse(st["rejected"])

    def test_get_order_status_reraises_non_404(self):
        client, session = make_client("demo")
        session.request.side_effect = EToroAPIError(500, "boom")
        with self.assertRaises(EToroAPIError):
            client.get_order_status("x")


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



class EToroDiscoverTests(unittest.TestCase):
    def test_list_exchanges_maps_id_to_description(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"exchangeInfo": [
            {"exchangeID": 4, "exchangeDescription": "NASDAQ"},
            {"exchangeID": 5, "exchangeDescription": "NYSE"},
            {"exchangeID": None, "exchangeDescription": "ignored"},
        ]})
        out = client.list_exchanges()
        self.assertEqual(out[4], "NASDAQ")
        self.assertEqual(out[5], "NYSE")
        self.assertNotIn(None, out)

    def test_list_exchanges_is_cached(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"exchangeInfo": [
            {"exchangeID": 4, "exchangeDescription": "NASDAQ"},
        ]})
        client.list_exchanges()
        client.list_exchanges()
        self.assertEqual(session.request.call_count, 1)

    # -- popularity-search discovery ----------------------------------------
    #
    # eToro has no fundamentals-discovery endpoint, so discover_instruments
    # ranks candidates via /market-data/search (popularityUniques sort, which
    # returns ONLY instrumentId per item) and resolves them to symbols/types
    # via a batch /market-data/instruments lookup.

    def _types(self, *pairs):
        return make_response(200, {"instrumentTypes": [
            {"instrumentTypeID": tid, "instrumentTypeDescription": desc} for tid, desc in pairs
        ]})

    def _search(self, *ids):
        return make_response(200, {"items": [{"instrumentId": i} for i in ids]})

    def _meta(self, rows):
        return make_response(200, {"instrumentDisplayDatas": rows})

    def _row(self, iid, symbol, type_id, **over):
        row = {
            "instrumentID": iid, "symbolFull": symbol,
            "instrumentDisplayName": symbol.title(), "instrumentTypeID": type_id,
            "exchangeID": 4, "isInternalInstrument": False,
        }
        row.update(over)
        return row

    def test_discover_instruments_ranks_by_popularity_and_resolves_metadata(self):
        client, session = make_client()
        session.request.side_effect = [
            self._types((10, "Crypto"), (5, "Stocks")),
            self._search(100000, 1001),  # popularity order: BTC then a stock
            self._meta([
                self._row(100000, "BTC", 10, exchangeID=8, instrumentDisplayName="Bitcoin"),
                self._row(1001, "AAPL", 5),
            ]),
        ]
        rows = client.discover_instruments("CRYPTO")
        # only the crypto-type row survives the asset-class filter
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "BTC")
        self.assertEqual(rows[0]["instrument_id"], 100000)
        self.assertEqual(rows[0]["name"], "Bitcoin")
        self.assertTrue(rows[0]["tradable"])
        calls = session.request.call_args_list
        # no fictional /instruments/discover call anymore; straight to search
        self.assertEqual(calls[0].args[1], "https://public-api.etoro.com/api/v1/market-data/instrument-types")
        self.assertEqual(calls[1].args[1], "https://public-api.etoro.com/api/v1/market-data/search")
        search_params = calls[1].kwargs["params"]
        self.assertEqual(search_params["sort"], "popularityUniques")
        self.assertEqual(search_params["pageNumber"], 1)
        self.assertIn("instrumentId", search_params["fields"])
        # metadata lookup must reach eToro with LITERAL commas (the gateway 500s
        # on %2C-encoded commas), in popularity order, not via encodable params
        lookup_url = calls[2].args[1]
        self.assertIn("instrumentIds=100000,1001", lookup_url)
        self.assertNotIn("instrumentIds", str(calls[2].kwargs.get("params") or ""))

    def test_discover_instruments_keeps_only_requested_asset_types(self):
        client, session = make_client()
        session.request.side_effect = [
            self._types((10, "Crypto"), (5, "Stocks")),
            self._search(1001, 100000),
            self._meta([self._row(1001, "AAPL", 5), self._row(100000, "BTC", 10)]),
        ]
        rows = client.discover_instruments("STOCK")
        self.assertEqual([r["symbol"] for r in rows], ["AAPL"])

    def test_discover_instruments_skips_internal(self):
        client, session = make_client()
        session.request.side_effect = [
            self._types((10, "Crypto")),
            self._search(100000, 222),
            self._meta([
                self._row(100000, "BTC", 10),
                self._row(222, "INT", 10, isInternalInstrument=True),
            ]),
        ]
        rows = client.discover_instruments("CRYPTO")
        self.assertEqual([r["symbol"] for r in rows], ["BTC"])

    def test_discover_instruments_skips_non_positive_ids(self):
        client, session = make_client()
        session.request.side_effect = [
            self._types((10, "Crypto")),
            self._search(-100000, 100000),  # synthetic aggregate id dropped
            self._meta([self._row(100000, "BTC", 10)]),
        ]
        rows = client.discover_instruments("CRYPTO")
        self.assertEqual([r["symbol"] for r in rows], ["BTC"])
        lookup_url = session.request.call_args_list[2].args[1]
        self.assertIn("instrumentIds=100000", lookup_url)
        self.assertNotIn("-100000", lookup_url)

    def test_discover_instruments_paginates_until_short_page(self):
        client, session = make_client()
        client.DISCOVER_PAGE_SIZE = 2  # force a second page
        session.request.side_effect = [
            self._types((10, "Crypto")),
            self._search(100000, 100001),                 # full page -> keep paging
            self._meta([self._row(100000, "BTC", 10), self._row(100001, "ETH", 10)]),
            self._search(100002),                          # short page -> stop
            self._meta([self._row(100002, "XRP", 10)]),
        ]
        rows = client.discover_instruments("CRYPTO")
        self.assertEqual([r["symbol"] for r in rows], ["BTC", "ETH", "XRP"])
        search_calls = [c for c in session.request.call_args_list
                        if c.args[1].endswith("/market-data/search")]
        self.assertEqual([c.kwargs["params"]["pageNumber"] for c in search_calls], [1, 2])

    def test_discover_instruments_respects_cap(self):
        client, session = make_client()
        client._DISCOVER_CAPS = {"CRYPTO": 1}
        session.request.side_effect = [
            self._types((10, "Crypto")),
            self._search(100000, 100001),
            self._meta([self._row(100000, "BTC", 10), self._row(100001, "ETH", 10)]),
        ]
        rows = client.discover_instruments("CRYPTO")
        self.assertEqual([r["symbol"] for r in rows], ["BTC"])  # capped at 1
        # cap reached -> no second search page
        self.assertEqual(session.request.call_count, 3)

    def test_discover_instruments_empty_when_no_instrument_types(self):
        client, session = make_client()
        session.request.side_effect = [
            make_response(404, {"errorCode": "RouteNotFound"}),  # instrument-types unavailable
        ]
        self.assertEqual(client.discover_instruments("CRYPTO"), [])
        self.assertEqual(session.request.call_count, 1)

    def test_discover_instruments_empty_when_search_404(self):
        client, session = make_client()
        session.request.side_effect = [
            self._types((10, "Crypto")),
            make_response(404, {"message": "An error has occurred."}),
        ]
        rows = client.discover_instruments("CRYPTO")
        self.assertEqual(rows, [])
        self.assertEqual(session.request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
