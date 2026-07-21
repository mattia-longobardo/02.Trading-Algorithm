"""Test della scoperta dinamica dell'universo: nessuna rete, client fake.

Lo stato è isolato per-test via STATE_DIR → tmp_path.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from etoro_bot.services import universe as uni


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    yield tmp_path


def _candles(n, close=100.0, volume=1_000_000.0):
    return [{"fromDate": f"d{i}", "open": close, "high": close, "low": close,
             "close": close, "volume": volume} for i in range(n)]


class FakeClient:
    """Catalogo, prezzi e candele in memoria, nella forma dell'API eToro."""

    def __init__(self, stocks, rates, candles):
        self._stocks = stocks
        self._rates = rates
        self._candles = candles

    def get_instruments_by_type(self, type_id):
        return list(self._stocks) if type_id == 5 else []

    def get_rates(self, instrument_ids):
        return {i: self._rates[i] for i in instrument_ids if i in self._rates}

    def get_candles(self, instrument_id, interval="OneDay", count=250, direction="asc"):
        return self._candles.get(instrument_id, [])[-count:]


CATALOGUE = [
    {"instrumentID": 1, "symbolFull": "PLTR", "instrumentDisplayName": "Palantir Technologies Inc"},
    {"instrumentID": 2, "symbolFull": "SNOW", "instrumentDisplayName": "Snowflake Inc"},
    {"instrumentID": 3, "symbolFull": "PENN", "instrumentDisplayName": "Penny Stock Corp"},
    {"instrumentID": 4, "symbolFull": "FRSH", "instrumentDisplayName": "Freshly Listed Inc"},
    {"instrumentID": 5, "symbolFull": "AAPL", "instrumentDisplayName": "Apple Inc"},
]

RATE_OK = {"lastExecution": 100.0, "bid": 99.9, "ask": 100.1}

SETTINGS = {
    "watchlist": ["AAPL", "MSFT"],
    "universe_discovery": {"enabled": True, "size": 3, "min_mentions": 2},
}


def _news(*texts, published_at=""):
    return [{"text": t, "source": "test", "tickers": [], "published_at": published_at}
            for t in texts]


def _client():
    return FakeClient(
        CATALOGUE,
        rates={1: RATE_OK, 2: RATE_OK, 3: {"lastExecution": 2.0}, 4: RATE_OK},
        candles={1: _candles(140), 2: _candles(140), 4: _candles(30)},
    )


# -- nomination ---------------------------------------------------------------


def test_nominate_explicit_marker_and_company_name():
    catalogue = {str(r["symbolFull"]): r for r in CATALOGUE}
    scores = uni.nominate(
        _news(
            "Rally di $PLTR dopo la trimestrale",
            "Palantir Technologies vince un contratto",
            "Snowflake (SNOW) delude le attese",
        ),
        catalogue, half_life_days=3.0, exclude=set(),
    )
    assert scores["PLTR"]["mentions"] == 2  # $PLTR + nome societario
    assert scores["SNOW"]["mentions"] == 1


def test_nominate_bare_symbol_does_not_count():
    catalogue = {str(r["symbolFull"]): r for r in CATALOGUE}
    scores = uni.nominate(
        _news("PLTR sale ancora senza marcatore"),
        catalogue, half_life_days=3.0, exclude=set(),
    )
    assert "PLTR" not in scores  # citazione nuda: troppo ambigua su tutto il catalogo


def test_nominate_excludes_watchlist_and_decays_old_news():
    catalogue = {str(r["symbolFull"]): r for r in CATALOGUE}
    old = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
    scores = uni.nominate(
        _news("Apple ($AAPL) e $PLTR in evidenza")
        + _news("Ancora $PLTR sugli scudi", published_at=old),
        catalogue, half_life_days=3.0, exclude={"AAPL"},
    )
    assert "AAPL" not in scores  # già in watchlist
    assert scores["PLTR"]["mentions"] == 2
    assert 1.0 < scores["PLTR"]["buzz"] < 1.5  # 1 + 0.5^(6/3) = 1.25


# -- refresh e screening ------------------------------------------------------


def test_refresh_selects_reliable_only(tmp_path):
    news = _news(
        "$PLTR vola", "Palantir Technologies firma un contratto",   # affidabile
        "$PENN raddoppia", "Penny Stock Corp sotto i riflettori",   # penny → fuori
        "$FRSH debutta", "Freshly Listed Inc in rally post IPO",    # storico corto → fuori
    )
    state = uni.refresh_universe(_client(), SETTINGS, news)
    symbols = [t["symbol"] for t in state["tickers"]]
    assert symbols == ["PLTR"]
    assert state["tickers"][0]["mentions"] == 2
    # persistito e riletto dall'universo effettivo
    assert uni.state_file().exists()
    assert uni.effective_universe(SETTINGS) == ["AAPL", "MSFT", "PLTR"]


def test_refresh_min_mentions_gate():
    state = uni.refresh_universe(_client(), SETTINGS, _news("$PLTR citato una volta sola"))
    assert state["tickers"] == []


def test_refresh_disabled_is_noop():
    settings = {**SETTINGS, "universe_discovery": {"enabled": False}}
    state = uni.refresh_universe(_client(), settings, _news("$PLTR ovunque", "$PLTR ancora"))
    assert state == {"enabled": False, "tickers": []}
    assert not uni.state_file().exists()
    assert uni.effective_universe(settings) == ["AAPL", "MSFT"]


def test_refresh_client_failure_degrades_without_raising():
    class BrokenClient:
        def get_instruments_by_type(self, type_id):
            raise RuntimeError("API giù")

    state = uni.refresh_universe(BrokenClient(), SETTINGS, _news("$PLTR", "$PLTR bis"))
    assert state["tickers"] == []
    assert "error" in state
    assert uni.effective_universe(SETTINGS) == ["AAPL", "MSFT"]  # watchlist intatta


def test_stale_state_is_ignored():
    uni.refresh_universe(
        _client(), SETTINGS,
        _news("$PLTR su", "Palantir Technologies giù"),
    )
    path = uni.state_file()
    state = json.loads(path.read_text(encoding="utf-8"))
    state["generated_at"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    path.write_text(json.dumps(state), encoding="utf-8")
    assert uni.load_discovery_state(SETTINGS) is None
    assert uni.effective_universe(SETTINGS) == ["AAPL", "MSFT"]


# -- integrazione col rilevamento ticker --------------------------------------


def test_detect_tickers_sees_discovered_symbols_and_names():
    from etoro_bot.knowledge.tickers import detect_tickers

    uni.refresh_universe(
        _client(), SETTINGS, _news("$PLTR sale", "Palantir Technologies vince"),
    )
    assert uni.discovered_aliases(SETTINGS)["PLTR"] == (
        "palantir technologies inc", "palantir technologies",
    )
    assert detect_tickers("Palantir Technologies annuncia utili record") == ["PLTR"]
    assert detect_tickers("Maxi contratto per $PLTR nel settore difesa") == ["PLTR"]
