"""Test del client eToro: requests mockato a livello di session, zero rete."""

from __future__ import annotations

import json
import uuid

import pytest

from etoro_bot.etoro import EtoroClient, EtoroError, RateLimiter


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None, text=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = headers or {}
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        return self._payload


class FakeSession:
    """Session finta: ogni elemento di `responses` è una FakeResponse o una
    callable(call_dict) -> FakeResponse. Registra tutte le chiamate."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        call = {"method": method, "url": url, "params": params, "json": json, "headers": headers}
        self.calls.append(call)
        item = self.responses.pop(0)
        return item(call) if callable(item) else item


def make_client(responses, environment="demo"):
    """Client con session finta, rate limiter senza sleep e sleep registrato."""
    session = FakeSession(responses)
    client = EtoroClient(
        "test-api-key", "test-user-key", environment=environment, session=session,
        rate_limiter=RateLimiter(sleep=lambda s: None),
    )
    sleeps: list[float] = []
    client._sleep = sleeps.append
    return client, session, sleeps


PORTFOLIO_OK = FakeResponse(payload={"clientPortfolio": {"positions": [], "credit": 1000.0}})


def lookup_payload(status_id, position_id=999, avg_price=123.45, name="Filled"):
    return {
        "orderId": 555,
        "status": {"id": status_id, "name": name, "errorCode": None, "errorMessage": None},
        "positionExecutions": [
            {"positionId": position_id, "state": "open", "openingData": {"avgPrice": avg_price}}
        ]
        if status_id == 3
        else [],
    }


# ------------------------------------------------------------------ (a) header

def test_headers_present_and_random_request_id_on_get():
    client, session, _ = make_client([PORTFOLIO_OK, FakeResponse(payload={"clientPortfolio": {}})])
    client.get_portfolio()
    client.get_portfolio()
    first, second = session.calls
    for call in (first, second):
        assert call["headers"]["x-api-key"] == "test-api-key"
        assert call["headers"]["x-user-key"] == "test-user-key"
        uuid.UUID(call["headers"]["x-request-id"])  # UUID valido
    # request id casuale: cambia tra le GET
    assert first["headers"]["x-request-id"] != second["headers"]["x-request-id"]


def test_open_position_uses_caller_request_id_for_idempotency():
    client, session, _ = make_client([
        FakeResponse(payload={"orderId": 555, "referenceId": "idem-key-1", "token": "t"}),
        FakeResponse(payload=lookup_payload(3)),
    ])
    result = client.open_position(instrument_id=1001, amount_usd=250.0, request_id="idem-key-1")
    order_call = session.calls[0]
    assert order_call["headers"]["x-request-id"] == "idem-key-1"
    assert order_call["json"] == {
        "action": "open",
        "transaction": "buy",
        "instrumentId": 1001,
        "settlementType": "real",
        "orderType": "mkt",
        "leverage": 1,
        "amount": 250.0,
        "orderCurrency": "usd",
    }
    assert result["order_id"] == 555


# ------------------------------------------------------------------ (b) 429

def test_429_respects_retry_after_then_succeeds():
    client, session, sleeps = make_client([
        FakeResponse(status_code=429, headers={"Retry-After": "7"}),
        PORTFOLIO_OK,
    ])
    portfolio = client.get_portfolio()
    assert portfolio["credit"] == 1000.0
    assert sleeps == [7.0]
    assert len(session.calls) == 2
    # stesso x-request-id sul retry: la richiesta è la stessa
    assert session.calls[0]["headers"]["x-request-id"] == session.calls[1]["headers"]["x-request-id"]


def test_429_gives_up_after_three_attempts():
    client, session, sleeps = make_client([
        FakeResponse(status_code=429, headers={"Retry-After": "1"}),
        FakeResponse(status_code=429, headers={"Retry-After": "1"}),
        FakeResponse(status_code=429, headers={"Retry-After": "1"}),
    ])
    with pytest.raises(EtoroError) as excinfo:
        client.get_portfolio()
    assert excinfo.value.status_code == 429
    assert len(session.calls) == 3
    assert sleeps == [1.0, 1.0]


# ------------------------------------------------------------------ (c) 5xx

def test_5xx_exponential_backoff_then_success():
    client, session, sleeps = make_client([
        FakeResponse(status_code=500, text="boom"),
        FakeResponse(status_code=502, text="bad gateway"),
        PORTFOLIO_OK,
    ])
    portfolio = client.get_portfolio()
    assert portfolio["credit"] == 1000.0
    assert sleeps == [1.0, 2.0]
    assert len(session.calls) == 3


# ------------------------------------------------------------------ (d) 4xx

def test_4xx_raises_without_retry():
    client, session, sleeps = make_client([FakeResponse(status_code=404, text="not found")])
    with pytest.raises(EtoroError) as excinfo:
        client.lookup_order(order_id=42)
    assert excinfo.value.status_code == 404
    assert len(session.calls) == 1
    assert sleeps == []
    # mai le chiavi nei messaggi d'errore
    assert "test-api-key" not in str(excinfo.value)
    assert "test-user-key" not in str(excinfo.value)


# ------------------------------------------------------------------ (e) polling

def test_open_position_polls_until_filled():
    client, session, _ = make_client([
        FakeResponse(payload={"orderId": 555, "referenceId": "r", "token": "t"}),
        FakeResponse(payload=lookup_payload(1, name="Received")),
        FakeResponse(payload=lookup_payload(2, name="Placed")),
        FakeResponse(payload=lookup_payload(3)),
    ])
    result = client.open_position(instrument_id=1001, amount_usd=100.0, request_id="r")
    assert result == {"position_id": 999, "execution_price": 123.45, "order_id": 555}
    assert len(session.calls) == 4  # 1 POST + 3 lookup
    lookups = session.calls[1:]
    assert all(c["params"] == {"orderId": 555} for c in lookups)
    assert all("orders:lookup" in c["url"] for c in lookups)


def test_open_position_rejected_raises_with_error_details():
    payload = lookup_payload(4, name="Rejected")
    payload["status"]["errorCode"] = "E42"
    payload["status"]["errorMessage"] = "insufficient funds"
    client, _, _ = make_client([
        FakeResponse(payload={"orderId": 555, "referenceId": "r", "token": "t"}),
        FakeResponse(payload=payload),
    ])
    with pytest.raises(EtoroError, match="insufficient funds"):
        client.open_position(instrument_id=1001, amount_usd=100.0, request_id="r")


def test_open_position_timeout_raises_with_order_id():
    client, _, _ = make_client([
        FakeResponse(payload={"orderId": 555, "referenceId": "r", "token": "t"}),
        FakeResponse(payload=lookup_payload(1, name="Received")),
    ])
    clock_values = iter([0.0, 40.0])  # deadline a 30s, poi il tempo è scaduto
    client._clock = lambda: next(clock_values)
    with pytest.raises(EtoroError, match="orderId=555"):
        client.open_position(instrument_id=1001, amount_usd=100.0, request_id="r")


# ------------------------------------------------------------------ (f) chunking

def test_get_rates_sends_one_request_per_instrument():
    """`instrumentIds` accetta un intero singolo: con una lista separata da
    virgole l'API risponde 400 «is not a valid integer»."""

    def echo_rate(call):
        instrument_id = call["params"]["instrumentIds"]
        assert isinstance(instrument_id, int)  # mai una stringa con virgole
        return FakeResponse(
            payload={"rates": [{"instrumentID": instrument_id, "ask": 1.0, "bid": 0.9}]}
        )

    client, session, _ = make_client([echo_rate, echo_rate, echo_rate])
    rates = client.get_rates([7, 8, 9])
    assert len(session.calls) == 3
    assert [c["params"]["instrumentIds"] for c in session.calls] == [7, 8, 9]
    assert set(rates) == {7, 8, 9}
    assert rates[9]["ask"] == 1.0


def test_get_rates_skips_instruments_without_a_quote():
    """Uno strumento non quotato non deve far fallire l'intera run."""
    client, session, _ = make_client([
        FakeResponse(status_code=400, payload={"detail": "no quote"}),
        FakeResponse(payload={"rates": [{"instrumentID": 8, "ask": 2.0, "bid": 1.9}]}),
    ])
    rates = client.get_rates([7, 8])
    assert set(rates) == {8}


def test_get_candles_reads_the_real_payload_shape():
    """Il payload è {"interval", "candles":[{"instrumentId", "candles":[…]}]}:
    non esiste nessun involucro `candlesResponse`."""
    client, _, _ = make_client([
        FakeResponse(payload={
            "interval": "OneDay",
            "candles": [{
                "instrumentId": 1001,
                "candles": [
                    {"fromDate": "2026-07-20T00:00:00Z", "open": 1.0, "high": 2.0,
                     "low": 0.5, "close": 1.5, "volume": 10.0},
                ],
            }],
        })
    ])
    candles = client.get_candles(1001, interval="OneDay", count=1)
    assert len(candles) == 1
    assert candles[0]["close"] == 1.5


def test_get_instruments_sends_one_request_per_id():
    """Con più id separati da virgola l'endpoint risponde 500: si itera."""
    def echo(call):
        instrument_id = call["params"]["instrumentIds"]
        return FakeResponse(payload={"instrumentDisplayDatas": [
            {"instrumentID": instrument_id, "symbolFull": f"S{instrument_id}", "exchangeID": 4}
        ]})

    client, session, _ = make_client([echo, echo])
    rows = client.get_instruments([1, 2], fields=["instrumentID", "symbolFull"])
    assert len(session.calls) == 2
    assert [r["instrumentID"] for r in rows] == [1, 2]
    assert "exchangeID" not in rows[0]  # proiezione client-side applicata


def test_get_instruments_by_type_loads_the_whole_catalogue_in_one_call():
    client, session, _ = make_client([
        FakeResponse(payload={"instrumentDisplayDatas": [
            {"instrumentID": 1001, "symbolFull": "AAPL", "instrumentTypeID": 5},
            {"instrumentID": 14254, "symbolFull": "AAPL.EUR", "instrumentTypeID": 5},
        ]})
    ])
    rows = client.get_instruments_by_type(5)
    assert len(session.calls) == 1
    assert session.calls[0]["params"] == {"instrumentTypeIds": 5}
    assert [r["symbolFull"] for r in rows] == ["AAPL", "AAPL.EUR"]


# ------------------------------------------------------------------ (g) demo/real

def test_demo_prefix_only_on_trading_routes():
    client, session, _ = make_client([
        PORTFOLIO_OK,
        FakeResponse(payload=[]),  # trade history
        FakeResponse(payload={"rates": []}),  # market data: nessun prefisso
        FakeResponse(payload={"orderForClose": {"orderID": 77, "statusID": 1}}),
    ])
    client.get_portfolio()
    client.get_trade_history()
    client.get_rates([1])
    client.close_position(position_id=12, instrument_id=1001)
    urls = [c["url"] for c in session.calls]
    assert urls[0].endswith("/api/v1/trading/info/demo/portfolio")
    assert urls[1].endswith("/api/v1/trading/info/trade/demo/history")
    assert urls[2].endswith("/api/v1/market-data/instruments/rates")
    assert "demo" not in urls[2]
    assert urls[3].endswith("/api/v1/trading/execution/demo/market-close-orders/positions/12")


def test_real_environment_has_no_demo_segment():
    client, session, _ = make_client(
        [
            PORTFOLIO_OK,
            FakeResponse(payload={"orderId": 555, "token": "t"}),
            FakeResponse(payload=lookup_payload(3)),
        ],
        environment="real",
    )
    client.get_portfolio()
    client.open_position(instrument_id=1001, amount_usd=50.0, request_id="r")
    urls = [c["url"] for c in session.calls]
    assert urls[0].endswith("/api/v1/trading/info/portfolio")
    assert urls[1].endswith("/api/v2/trading/execution/orders")
    assert urls[2].endswith("/api/v2/trading/info/orders:lookup")
    assert all("demo" not in u for u in urls)


# ------------------------------------------------------------------ extra

def test_close_position_returns_close_order_id():
    client, session, _ = make_client(
        [FakeResponse(payload={"orderForClose": {"orderID": 88, "statusID": 1}, "token": "t"})]
    )
    result = client.close_position(position_id=999, instrument_id=1001)
    assert result == {"order_id": 88, "position_id": 999, "status_id": 1}
    assert session.calls[0]["json"] == {"InstrumentID": 1001, "UnitsToDeduct": None}


def test_lookup_order_requires_exactly_one_key():
    client, _, _ = make_client([])
    with pytest.raises(ValueError):
        client.lookup_order()
    with pytest.raises(ValueError):
        client.lookup_order(order_id=1, reference_id="r")


def test_lookup_order_by_reference_id_for_recovery():
    client, session, _ = make_client([FakeResponse(payload=lookup_payload(3))])
    info = client.lookup_order(reference_id="idem-key-1")
    assert session.calls[0]["params"] == {"referenceId": "idem-key-1"}
    assert info["status"]["id"] == 3


def test_static_lookups_are_cached():
    client, session, _ = make_client([
        FakeResponse(payload={"instrumentTypes": [
            {"instrumentTypeID": 5, "instrumentTypeDescription": "Stocks"},
            {"instrumentTypeID": 6, "instrumentTypeDescription": "ETF"},
        ]}),
        FakeResponse(payload={"stocksIndustries": [{"industryID": 7, "industryName": "Technology"}]}),
    ])
    assert client.get_instrument_types() == {5: "Stocks", 6: "ETF"}
    assert client.get_instrument_types() == {5: "Stocks", 6: "ETF"}  # cache: nessuna nuova chiamata
    assert client.get_stocks_industries() == {7: "Technology"}
    assert client.get_stocks_industries() == {7: "Technology"}
    assert len(session.calls) == 2


def test_get_candles_flattens_response():
    client, session, _ = make_client([
        FakeResponse(payload={"candlesResponse": {"interval": "OneDay", "candles": [
            {"instrumentId": 1001, "candles": [
                {"instrumentId": 1001, "fromDate": "2026-07-17T00:00:00Z",
                 "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100},
            ]}
        ]}}),
    ])
    candles = client.get_candles(1001, interval="OneDay", count=250, direction="asc")
    assert candles == [{"fromDate": "2026-07-17T00:00:00Z", "open": 1.0, "high": 2.0,
                        "low": 0.5, "close": 1.5, "volume": 100}]
    assert session.calls[0]["url"].endswith(
        "/api/v1/market-data/instruments/1001/history/candles/asc/OneDay/250"
    )


def test_search_instruments_paginates_and_requires_fields():
    page1 = FakeResponse(payload={"page": 1, "pageSize": 2, "totalItems": 3,
                                  "items": [{"instrumentId": 1}, {"instrumentId": 2}]})
    page2 = FakeResponse(payload={"page": 2, "pageSize": 2, "totalItems": 3,
                                  "items": [{"instrumentId": 3}]})
    client, session, _ = make_client([page1, page2])
    items = client.search_instruments(
        {"instrumentTypeID": 5}, fields=["instrumentId", "displayname"], page_size=2
    )
    assert [i["instrumentId"] for i in items] == [1, 2, 3]
    assert session.calls[0]["params"]["fields"] == "instrumentId,displayname"
    assert session.calls[0]["params"]["instrumentTypeID"] == 5
    assert session.calls[1]["params"]["pageNumber"] == 2


def test_rate_limiter_uses_safety_margin():
    now = {"t": 0.0}
    waits: list[float] = []

    def clock():
        return now["t"]

    def sleep(seconds):
        waits.append(seconds)
        now["t"] += seconds

    limiter = RateLimiter(clock=clock, sleep=sleep)
    for _ in range(16):  # 80% di 20 = 16 slot execution senza attese
        limiter.acquire("execution")
    assert waits == []
    limiter.acquire("execution")  # il 17° deve attendere la finestra
    assert waits == [60.0]


def test_invalid_environment_rejected():
    with pytest.raises(ValueError):
        EtoroClient("k", "u", environment="staging")
