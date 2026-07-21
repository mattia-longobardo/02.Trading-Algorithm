"""Rilevamento automatico dei ticker impattati da un documento."""

from etoro_bot.knowledge.ingest import _build_items
from etoro_bot.knowledge.tickers import detect_tickers

UNIVERSE = ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "JPM", "V", "XOM", "SPY")


def test_detects_bare_symbol():
    assert detect_tickers("Trimestrale sopra le attese per AAPL.", UNIVERSE) == ["AAPL"]


def test_detects_dollar_and_parenthesis_markers():
    text = "Occhio a $NVDA e a Microsoft (MSFT) dopo la guidance."
    assert set(detect_tickers(text, UNIVERSE)) == {"NVDA", "MSFT"}


def test_detects_exchange_prefix():
    assert detect_tickers("Il titolo NASDAQ: TSLA scivola.", UNIVERSE) == ["TSLA"]


def test_detects_company_names_case_insensitive():
    text = "amazon e Alphabet crescono, exxon mobil arretra."
    assert set(detect_tickers(text, UNIVERSE)) == {"AMZN", "GOOGL", "XOM"}


def test_short_symbols_need_an_explicit_marker():
    # "V" isolata in una frase non basta a marcare Visa…
    assert detect_tickers("Il piano V prevede tagli.", UNIVERSE) == []
    # …ma con marcatore esplicito sì.
    assert detect_tickers("Comprato $V ieri.", UNIVERSE) == ["V"]


def test_symbols_outside_the_universe_are_ignored():
    assert detect_tickers("Report su $IBM e su ORCL.", UNIVERSE) == []


def test_words_that_look_like_symbols_are_ignored():
    assert detect_tickers("IL MERCATO CHIUDE IN RIALZO", UNIVERSE) == []


def test_order_follows_first_appearance():
    assert detect_tickers("Prima Tesla, poi Apple, poi ancora Tesla.", UNIVERSE) == [
        "TSLA",
        "AAPL",
    ]


def test_no_universe_means_no_detection():
    assert detect_tickers("Apple vola, $AAPL su del 5%.", ()) == []


def test_chunks_carry_only_their_own_tickers(monkeypatch):
    monkeypatch.setattr(
        "etoro_bot.knowledge.ingest.detect_tickers",
        lambda text: detect_tickers(text, UNIVERSE),
    )
    body = "Apple accelera nei servizi.\n\n" + "x" * 1600 + "\n\nTesla taglia i prezzi."
    items, document = _build_items(body, "report.md", None)

    assert len(items) >= 2
    assert items[0]["tickers"] == ["AAPL"]
    assert items[-1]["tickers"] == ["TSLA"]
    # Il documento aggrega l'unione, i chunk restano specifici.
    assert set(document) == {"AAPL", "TSLA"}


def test_manual_tickers_add_to_detected_ones_without_replacing(monkeypatch):
    monkeypatch.setattr(
        "etoro_bot.knowledge.ingest.detect_tickers",
        lambda text: detect_tickers(text, UNIVERSE),
    )
    items, document = _build_items("Apple presenta i risultati.", "nota.md", ["SPY"])
    assert items[0]["tickers"] == ["SPY", "AAPL"]
    assert document == ["SPY", "AAPL"]
