"""Test del layer knowledge: nessuna rete, nessun Qdrant reale.

La KnowledgeBase gira in modalità degradata (qdrant-client/fastembed sono
extra `rag`, non installati nella venv di sviluppo): i test verificano proprio
che la degradazione sia silenziosa e che parser/chunking/CAG siano puri.
"""


from etoro_bot.knowledge.cag import build_static_context, static_system_block
from etoro_bot.knowledge.fetch_news import (
    MAX_ITEMS_PER_FEED,
    fetch_all,
    parse_feed,
    strip_html,
)
from etoro_bot.knowledge.ingest import chunk_text, ingest_path, parse_document
from etoro_bot.knowledge.kb import KnowledgeBase, point_id_for_text

RSS2_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Feed di test</title>
    <item>
      <title>Apple sale del 3%</title>
      <description>&lt;p&gt;Trimestrale &lt;b&gt;sopra&lt;/b&gt; le attese.&lt;/p&gt;</description>
      <pubDate>Mon, 20 Jul 2026 08:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Microsoft annuncia buyback</title>
      <description>Programma da 60 miliardi.</description>
      <pubDate>Mon, 20 Jul 2026 07:30:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Feed Atom di test</title>
  <entry>
    <title>NVIDIA presenta nuovi chip</title>
    <summary>Annuncio &lt;i&gt;alla&lt;/i&gt; conferenza GTC.</summary>
    <updated>2026-07-20T08:00:00Z</updated>
  </entry>
</feed>
"""


# -- (a) parser RSS/Atom ------------------------------------------------------


def test_parse_feed_rss2():
    items = parse_feed(RSS2_XML, source="test", tickers=["AAPL"])
    assert len(items) == 2
    first = items[0]
    assert first["text"] == "Apple sale del 3%. Trimestrale sopra le attese."
    assert first["source"] == "test"
    assert first["tickers"] == ["AAPL"]
    assert first["published_at"] == "Mon, 20 Jul 2026 08:00:00 GMT"


def test_parse_feed_atom():
    items = parse_feed(ATOM_XML, source="atom-test")
    assert len(items) == 1
    assert items[0]["text"] == "NVIDIA presenta nuovi chip. Annuncio alla conferenza GTC."
    assert items[0]["tickers"] == []
    assert items[0]["published_at"] == "2026-07-20T08:00:00Z"


def test_parse_feed_max_items():
    body = "".join(
        f"<item><title>Notizia {i}</title><description>testo</description></item>"
        for i in range(40)
    )
    xml = f"<rss version='2.0'><channel>{body}</channel></rss>"
    assert len(parse_feed(xml, source="big")) == MAX_ITEMS_PER_FEED


def test_parse_feed_malformed_and_doctype():
    assert parse_feed("non è xml <<<", source="bad") == []
    evil = '<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY x "y">]><rss/>'
    assert parse_feed(evil, source="evil") == []


def test_strip_html():
    assert strip_html("<p>Ciao   <b>mondo</b> &amp; co.</p>") == "Ciao mondo & co."


def test_point_id_stable_dedup():
    a = point_id_for_text("stesso testo")
    b = point_id_for_text("stesso testo")
    c = point_id_for_text("altro testo")
    assert a == b  # id stabile → l'upsert deduplica
    assert a != c


# -- (b) chunking e header tickers -------------------------------------------


def test_parse_document_tickers_header():
    tickers, body = parse_document("tickers: AAPL, msft\n\nParagrafo uno.")
    assert tickers == ["AAPL", "MSFT"]
    assert body == "Paragrafo uno."


def test_parse_document_without_header():
    tickers, body = parse_document("Solo testo, nessun header.")
    assert tickers == []
    assert body == "Solo testo, nessun header."


def test_chunk_text_paragraph_boundaries():
    paragraphs = [f"Paragrafo {i}. " + "x" * 600 for i in range(6)]
    chunks = chunk_text("\n\n".join(paragraphs), max_chars=1500)
    assert len(chunks) > 1
    # nessun paragrafo spezzato: ricomposti, i chunk danno il testo originale
    assert "\n\n".join(chunks) == "\n\n".join(paragraphs)
    # ogni chunk multi-paragrafo resta sotto la soglia
    assert all(len(c) <= 1500 for c in chunks)


def test_ingest_path_degraded(tmp_path):
    doc = tmp_path / "note.md"
    doc.write_text("tickers: AAPL\n\nTesi di esempio.", encoding="utf-8")
    kb = KnowledgeBase(url="http://host-inesistente.invalid:1")
    assert not kb.available
    assert ingest_path(tmp_path, kb) == 0  # degradata: nessuna eccezione, zero indicizzati


# -- (c) CAG deterministico ---------------------------------------------------


def test_build_static_context_deterministic():
    first = build_static_context()
    second = build_static_context()
    assert first == second  # byte-identico → cache hit del prompt caching
    assert "max_open_positions" in first  # risk_rules.yaml raw incluso
    assert "AAPL" in first  # watchlist inclusa


def test_static_system_block_shape():
    block = static_system_block()
    assert block["type"] == "text"
    assert "cache_control" not in block  # OpenAI: caching automatico, niente marker
    assert block["text"] == build_static_context()


# -- (d) modalità degradata ---------------------------------------------------


def test_knowledge_base_degraded_no_exceptions():
    kb = KnowledgeBase(url="http://host-inesistente.invalid:1")
    assert kb.available is False
    kb.ensure_collections()
    assert kb.add_news([{"text": "notizia", "source": "s", "tickers": [], "published_at": ""}]) == 0
    assert kb.search_news("query", tickers=["AAPL"]) == []
    kb.add_trade_memory("trade", {"pnl": 1.0})
    assert kb.search_trade_memory("query") == []
    assert kb.status() == {"qdrant_up": False, "collections": {}}


# -- (e) un feed che fallisce non interrompe gli altri ------------------------


def test_fetch_all_feed_failure_continues(monkeypatch):
    settings = {
        "watchlist": ["AAPL"],
        "news_feeds": {
            "generic": ["http://feed-rotto.invalid/rss"],
            "per_ticker": ["http://feed-ok.invalid/rss?s={ticker}"],
        },
    }

    # Si sostituisce il fetcher, non urlopen: il trasporto passa da
    # safe_fetch.fetch_text (guardia anti-SSRF) e il punto del test è la
    # resilienza di fetch_all, non il modo in cui scarica.
    def fake_fetch(url, *, user_agent, timeout=None):
        if "feed-rotto" in url:
            raise OSError("connessione rifiutata")
        assert "s=AAPL" in url  # template per-ticker applicato alla watchlist
        return RSS2_XML

    monkeypatch.setattr("etoro_bot.knowledge.fetch_news.fetch_text", fake_fetch)
    items = fetch_all(settings)
    assert len(items) == 2  # solo il feed sano; quello rotto non ha interrotto
    assert all(item["tickers"] == ["AAPL"] for item in items)
    assert all(item["source"] == "feed-ok.invalid" for item in items)
