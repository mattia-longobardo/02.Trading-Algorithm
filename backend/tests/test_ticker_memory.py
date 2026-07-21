"""Test della memoria evolutiva per ticker: filesystem isolato, LLM fake."""

from datetime import datetime, timedelta, timezone

import pytest

from etoro_bot.knowledge import ticker_memory as tm

NO_LLM = {"knowledge": {"ticker_memory": {"use_llm": False}}}


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    yield tmp_path


def _item(text, tickers, published_at="", source="feed"):
    return {"text": text, "tickers": tickers, "published_at": published_at,
            "source": source, "kind": "news"}


def test_update_creates_memory_with_fallback_summary():
    updated = tm.update_memories(
        [_item("Apple presenta il nuovo iPhone", ["AAPL"])], NO_LLM
    )
    assert updated == {"AAPL": 1}
    memory = tm.load_memory("AAPL")
    assert memory["ticker"] == "AAPL"
    assert len(memory["entries"]) == 1
    assert "nuovo iPhone" in memory["summary"]
    assert memory["summary_source"] == "headline"
    assert "nuovo iPhone" in tm.memory_context("AAPL")


def test_update_deduplicates_and_appends():
    items = [_item("Apple presenta il nuovo iPhone", ["AAPL"])]
    tm.update_memories(items, NO_LLM)
    assert tm.update_memories(items, NO_LLM) == {}  # stesso testo: nessuna novità
    tm.update_memories([_item("Apple batte le stime sugli utili", ["AAPL"])], NO_LLM)
    memory = tm.load_memory("AAPL")
    assert [len(memory["entries"])] == [2]


def test_retention_drops_old_entries():
    old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    tm.update_memories([_item("Notizia vecchissima su Apple", ["AAPL"], published_at=old)], NO_LLM)
    assert tm.load_memory("AAPL") is None or tm.load_memory("AAPL")["entries"] == []
    # una notizia fresca entra e quella oltre retention non ricompare
    tm.update_memories(
        [_item("Notizia fresca su Apple", ["AAPL"]),
         _item("Altra notizia vecchissima", ["AAPL"], published_at=old)],
        NO_LLM,
    )
    memory = tm.load_memory("AAPL")
    assert [e["text"] for e in memory["entries"]] == ["Notizia fresca su Apple"]


def test_llm_summary_updates_memory():
    def fake_llm(system_blocks, user_prompt, model, max_tokens):
        assert "Memoria attuale" in user_prompt and "AAPL" in user_prompt
        return "Tema persistente: cicli iPhone. Rischio: domanda Cina."

    tm.update_memories(
        [_item("iPhone forte in Cina", ["AAPL"])],
        {"knowledge": {"ticker_memory": {"use_llm": True}}},
        llm=fake_llm,
    )
    memory = tm.load_memory("AAPL")
    assert memory["summary"].startswith("Tema persistente")
    assert memory["summary_source"] == "llm"


def test_llm_failure_falls_back_to_headlines():
    def broken_llm(**kwargs):
        raise RuntimeError("niente chiave API")

    tm.update_memories([_item("Apple lancia un buyback", ["AAPL"])], llm=broken_llm,
                       settings={"knowledge": {"ticker_memory": {"use_llm": True}}})
    memory = tm.load_memory("AAPL")
    assert memory["summary_source"] == "headline"
    assert "buyback" in memory["summary"]


def test_documents_and_unsafe_tickers_are_ignored(tmp_path):
    doc = {"text": "analisi caricata", "tickers": ["AAPL"], "kind": "document",
           "published_at": "", "source": "upload"}
    assert tm.update_memories([doc], NO_LLM) == {}
    assert tm.update_memories([_item("exploit", ["../EVIL"])], NO_LLM) == {}
    assert list(tmp_path.rglob("*.json")) == []


def test_disabled_memory_is_noop():
    settings = {"knowledge": {"ticker_memory": {"enabled": False}}}
    assert tm.update_memories([_item("news", ["AAPL"])], settings) == {}
    assert tm.load_memory("AAPL") is None


def test_all_memories_sorted():
    tm.update_memories(
        [_item("news su Microsoft", ["MSFT"]), _item("news su Apple", ["AAPL"])], NO_LLM
    )
    assert [m["ticker"] for m in tm.all_memories()] == ["AAPL", "MSFT"]
