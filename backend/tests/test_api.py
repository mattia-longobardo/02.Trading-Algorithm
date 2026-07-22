"""Smoke test dell'API FastAPI (§12.3) con TestClient su Postgres effimero."""

import importlib

import pytest


@pytest.fixture()
def client(repo, pg_url, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("KILL_SWITCH_DIR", str(tmp_path))
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path / "knowledge_base"))
    monkeypatch.setenv("DISABLE_SCHEDULER", "1")
    monkeypatch.delenv("ETORO_BOT_KILL", raising=False)

    from fastapi.testclient import TestClient

    from etoro_bot.api import server

    importlib.reload(server)  # ricostruisce app e cache col nuovo env
    server.get_repo.cache_clear()
    with TestClient(server.app) as tc:
        yield tc


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_status_shape(client):
    body = client.get("/status").json()
    assert body["environment"] == "demo"
    assert body["kill_switch_active"] is False
    assert body["circuit_breaker"]["tripped"] is False
    assert body["run_in_progress"] is False


def test_settings_get_and_guardrail(client):
    body = client.get("/settings").json()
    assert body["environment"] == "demo"
    assert body["api_keys_configured"] is False
    assert body["risk_limits"]["max_open_positions"] == 10
    assert body["timezone"] == "Europe/Rome"

    # verso real senza conferma → 422
    resp = client.put("/settings", json={"environment": "real"})
    assert resp.status_code == 422

    # verso demo sempre permesso; un cambio finisce nell'audit
    resp = client.put("/settings", json={"timezone": "UTC"})
    assert resp.status_code == 200
    assert client.get("/settings").json()["timezone"] == "UTC"

    audit = client.get("/settings/audit").json()
    assert len(audit["entries"]) >= 1


def test_kill_switch_roundtrip(client):
    assert client.post("/kill-switch").json()["kill_switch_active"] is True
    assert client.get("/status").json()["kill_switch_active"] is True
    assert client.delete("/kill-switch").json()["kill_switch_active"] is False


def test_empty_journal_endpoints(client):
    assert client.get("/runs").json() == {"runs": []}
    assert client.get("/executions").json() == {"executions": []}
    assert client.get("/runs/nope/decisions").status_code == 404


def test_backtest_endpoints_empty(client):
    summary = client.get("/backtest/summary").json()
    assert summary["n_closed_trades"] == 0
    assert summary["insufficient_sample"] is True
    assert summary["metrics"]["cagr_pct"] is None

    curve = client.get("/backtest/equity-curve").json()
    assert curve["points"] == []
    assert "dividendi" in curve["note_dividends"]

    assert client.get("/backtest/trades").json() == {"trades": []}
    assert client.get("/backtest/monthly-returns").status_code == 200


def test_risk_score_empty_portfolio(client):
    body = client.get("/risk/score").json()
    assert 1.0 <= body["score"] <= 10.0
    assert body["band"] in {"low", "medium", "high", "extreme"}
    assert len(body["components"]) == 8
    history = client.get("/risk/score/history").json()
    assert len(history["points"]) == 1  # lo snapshot appena persistito


def test_knowledge_status_degraded(client, monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "http://localhost:1")  # niente Qdrant
    body = client.get("/knowledge/status").json()
    assert body["qdrant_up"] is False
    assert isinstance(body["rss_feeds"], list) and body["rss_feeds"]


def test_portfolio_empty(client, monkeypatch):
    from etoro_bot.api import server

    class FakeEtoro:
        def get_portfolio(self):
            return {"credit": 51_073.77}

    monkeypatch.setattr(server, "_make_client", lambda *_: FakeEtoro())
    body = client.get("/portfolio").json()
    assert body["positions"] == []
    assert body["equity_usd"] == body["cash_usd"] == 51_073.77
    assert body["max_trade_amount_usd"] == pytest.approx(5_107.377)
    assert body["capital_source"] == "etoro"


def test_delete_run_endpoint(client, repo):
    repo.create_run("run-api-del", environment="demo")
    assert client.delete("/runs/run-api-del").json() == {
        "deleted": True, "run_id": "run-api-del",
    }
    assert client.get("/runs").json()["runs"] == []


def test_delete_unknown_run_is_404(client):
    assert client.delete("/runs/inesistente").status_code == 404


def test_universe_view_includes_yaml_watchlist(client):
    """Regressione: /universe deve vedere i settings COMPLETI (yaml + runtime),
    non solo le chiavi runtime di get_effective() — altrimenti watchlist vuota."""
    body = client.get("/universe").json()
    assert "AAPL" in body["watchlist"]
    assert body["enabled"] is True
    assert body["discovered"] == []


def test_ticker_memory_endpoint_empty(client):
    assert client.get("/knowledge/ticker-memory").json() == {"memories": []}
