"""Test della pipeline LangGraph: SENZA rete e SENZA LLM reale.

EtoroClient fake in-memory, call_llm fake iniettato via GraphDeps.llm, repo =
fixture Postgres effimero di conftest per i test che toccano il journal.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest

from etoro_bot.config import RiskRules
from etoro_bot.domain import (
    AssetType,
    PortfolioSnapshot,
    ProposedOrder,
    RiskVerdict,
    Side,
    order_request_id,
)
from etoro_bot.etoro.client import EtoroError
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.graph import build_graph
from etoro_bot.graph.nodes.analysts import run_analyst
from etoro_bot.graph.nodes.debate import debate
from etoro_bot.graph.nodes.executor import executor
from etoro_bot.graph.nodes.reconcile import ReconcileError, reconcile
from etoro_bot.graph.nodes.screener import screener
from etoro_bot.safety.circuit_breaker import CircuitBreaker

NOW = datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc)


# --------------------------------------------------------------------- fakes


class FakeEtoroClient:
    """Client eToro in-memory: nessuna rete, registra le chiamate che muovono denaro."""

    def __init__(
        self,
        *,
        portfolio=None,
        catalogue=None,
        rates=None,
        candles=None,
        trade_history=None,
        instrument_types=None,
        industries=None,
    ):
        self.portfolio = portfolio if portfolio is not None else {"positions": [], "credit": 10_000.0}
        self.catalogue = catalogue or []    # anagrafiche come le rende l'API
        self.rates = rates or {}            # instrument_id -> rate dict
        self.candles = candles or {}        # instrument_id -> list[candle]
        self.trade_history = trade_history or []
        self.instrument_types = instrument_types or {5: "Stocks", 6: "ETF", 10: "Cryptocurrencies"}
        self.industries = industries or {3: "Technology"}
        self.open_calls: list[tuple] = []
        self.close_calls: list[tuple] = []
        self.orders_by_reference: dict[str, dict] = {}
        self.next_position_id = 1000

    def get_portfolio(self):
        return self.portfolio

    def get_trade_history(self, min_date=None, page_size=100):
        return self.trade_history

    def get_rates(self, instrument_ids):
        return {i: self.rates[i] for i in instrument_ids if i in self.rates}

    def get_candles(self, instrument_id, interval="OneDay", count=250, direction="asc"):
        return self.candles.get(instrument_id, [])[-count:]

    def get_instrument_types(self):
        return self.instrument_types

    def get_stocks_industries(self):
        return self.industries

    def get_instruments_by_type(self, instrument_type_id):
        return [r for r in self.catalogue if r["instrumentTypeID"] == instrument_type_id]

    def search_instruments(self, query_filters, fields, page_size=50):
        """Come l'API vera: filtra ma proietta SOLO instrumentId."""
        symbol = query_filters.get("internalSymbolFull")
        return [
            {"instrumentId": r["instrumentID"]}
            for r in self.catalogue
            if symbol is None or r["symbolFull"] == symbol
        ]

    def lookup_order(self, order_id=None, reference_id=None):
        info = self.orders_by_reference.get(reference_id)
        if info is None:
            raise EtoroError("HTTP 404: ordine inesistente", status_code=404)
        return info

    def open_position(self, instrument_id, amount_usd, request_id):
        self.open_calls.append((instrument_id, amount_usd, request_id))
        position_id = self.next_position_id
        self.next_position_id += 1
        self.orders_by_reference[request_id] = {
            "status": {"id": 3},
            "positionExecutions": [
                {"positionId": position_id, "openingData": {"avgPrice": 100.0}}
            ],
        }
        return {"position_id": position_id, "execution_price": 100.0, "order_id": 1}

    def close_position(self, position_id, instrument_id):
        self.close_calls.append((position_id, instrument_id))
        return {"order_id": 2, "position_id": position_id, "status_id": 3}


class FakeKB:
    """KB fake: ricerche vuote, registra le indicizzazioni in trade_memory."""

    def __init__(self):
        self.added: list[tuple[str, dict]] = []

    def search_news(self, query, tickers=None, limit=5):
        return []

    def search_trade_memory(self, query, limit=3):
        return []

    def add_trade_memory(self, text, payload):
        self.added.append((text, payload))


def make_fake_llm(judgements=None, pm_orders=None, analyst_score=0.6):
    """call_llm fake: JSON predefiniti, smistati sui marker dei prompt."""

    def fake(system_blocks, user_prompt, model, max_tokens, client=None):
        if "ANALISTA" in user_prompt:
            symbols = re.findall(r"^- ([A-Z0-9.]+) ", user_prompt, flags=re.M)
            return json.dumps(
                [{"symbol": s, "score": analyst_score, "summary": "ok"} for s in symbols]
            )
        if "GIUDICE" in user_prompt:
            symbol = re.search(r"dibattito su ([A-Z0-9.]+)", user_prompt).group(1).rstrip(".")
            verdict = (judgements or {}).get(
                symbol, {"decision": "avoid", "conviction": 0.0, "rationale": "non convincente"}
            )
            return json.dumps(verdict)
        if "PORTFOLIO MANAGER" in user_prompt:
            return json.dumps(pm_orders if pm_orders is not None else [])
        return "argomentazione di dibattito"

    return fake


def make_deps(tmp_path, repo=None, client=None, llm=None, settings=None, rules=None):
    rules = rules or RiskRules()
    base_settings = {
        "watchlist": ["AAPL", "SPY"],
        "max_candidates_per_run": 6,
        "debate_rounds": 1,
        "bot_capital_usd": 10_000,
        "llm": {"model": "test-model", "max_tokens": 512},
    }
    base_settings.update(settings or {})
    return GraphDeps(
        client=client or FakeEtoroClient(),
        repo=repo,
        rules=rules,
        settings=base_settings,
        breaker=CircuitBreaker(rules.circuit_breaker, state_dir=tmp_path),
        kb=FakeKB(),
        llm=llm or make_fake_llm(),
    )


def instrument_row(symbol, instrument_id, type_id=5):
    """Anagrafica nella forma resa da /market-data/instruments."""
    return {
        "instrumentID": instrument_id,
        "instrumentDisplayName": f"{symbol} Inc",
        "instrumentTypeID": type_id,
        "exchangeID": 4,
        "symbolFull": symbol,
        "stocksIndustryID": 3,
    }


def flat_candles(last_close, change_pct):
    """6 chiusure con la variazione complessiva richiesta (momentum)."""
    first = last_close / (1 + change_pct / 100)
    step = (last_close - first) / 5
    return [
        {"fromDate": f"2026-07-{10 + i:02d}", "open": first, "high": last_close,
         "low": first, "close": first + step * i, "volume": 1000}
        for i in range(6)
    ]


@pytest.fixture(autouse=True)
def _isolate_safety(tmp_path, monkeypatch):
    """Kill switch isolato per test: mai il file/env dell'ambiente reale."""
    monkeypatch.setenv("KILL_SWITCH_DIR", str(tmp_path))
    monkeypatch.delenv("ETORO_BOT_KILL", raising=False)


# ---------------------------------------------------------------- (a) + (b)


def test_reconcile_filters_non_bot_and_detects_vanished_position(repo, tmp_path):
    repo.create_run("r1", environment="demo")
    repo.register_open_position(100, "r1", "AAPL", 1, 200.0, 150.0, NOW, sector="tech")
    repo.register_open_position(200, "r1", "MSFT", 2, 300.0, 400.0, NOW, sector="tech")
    client = FakeEtoroClient(
        portfolio={
            "positions": [
                {"positionID": 100, "instrumentID": 1},
                {"positionID": 999, "instrumentID": 77},  # aperta a mano: da ignorare
            ],
            "credit": 5000.0,
        },
        rates={1: {"bid": 160.0, "ask": 161.0}},
        trade_history=[{"positionId": 200, "netProfit": -12.5, "closeRate": 380.0}],
    )
    deps = make_deps(tmp_path, repo=repo, client=client)

    update = reconcile({"run_id": "r1"}, deps)
    snapshot = PortfolioSnapshot.model_validate(update["portfolio"])

    # solo la posizione bot presente sull'API; la 999 (manuale) è ignorata
    assert [p.etoro_position_id for p in snapshot.positions] == [100]
    assert snapshot.positions[0].current_price == 160.0
    # la 200 (sparita dall'API) è chiusa esternamente con il PnL dalla history
    closed = repo.closed_positions()
    assert len(closed) == 1
    assert closed[0].etoro_position_id == 200
    assert closed[0].realized_pnl_usd == -12.5
    assert closed[0].close_reason == "closed_externally"
    assert len(snapshot.anomalies) == 1
    assert "reconcile_anomaly" in {d.stage for d in repo.get_run_decisions("r1")}
    # La liquidità disponibile arriva direttamente dal campo credit di eToro.
    assert snapshot.cash_usd == pytest.approx(5000.0)


def test_reconcile_failure_stops_run(repo, tmp_path):
    class BrokenClient(FakeEtoroClient):
        def get_portfolio(self):
            raise RuntimeError("API giù")

    deps = make_deps(tmp_path, repo=repo, client=BrokenClient())
    with pytest.raises(ReconcileError):
        reconcile({"run_id": "r-broken"}, deps)


# ------------------------------------------------------------------------ (c)


def test_screener_keeps_only_tradable_stock_etf_and_caps_candidates(tmp_path):
    client = FakeEtoroClient(
        catalogue=[
            instrument_row("AAPL", 1, type_id=5),
            instrument_row("SPY", 2, type_id=6),
            instrument_row("BTC", 3, type_id=10),    # crypto: fuori dal catalogo stock/ETF
            instrument_row("XOM", 4, type_id=5),     # senza prezzo: non quotabile ora
            instrument_row("MSFT", 5, type_id=5),
            instrument_row("NVDA", 6, type_id=5),
        ],
        # XOM assente: senza prezzo corrente lo strumento viene scartato.
        rates={i: {"instrumentID": i, "lastExecution": 100.0} for i in (1, 2, 3, 5, 6)},
        candles={
            1: flat_candles(100.0, 1.0),
            2: flat_candles(100.0, 4.0),
            3: flat_candles(100.0, 99.0),
            5: flat_candles(100.0, 3.0),
            6: flat_candles(100.0, 2.0),
        },
    )
    deps = make_deps(
        tmp_path,
        client=client,
        settings={
            "watchlist": ["AAPL", "SPY", "BTC", "XOM", "MSFT", "NVDA"],
            "max_candidates_per_run": 3,
        },
    )
    update = screener({"run_id": "r1"}, deps)
    candidates = update["candidates"]
    assert len(candidates) == 3  # max_candidates rispettato
    symbols = [c["symbol"] for c in candidates]
    assert "BTC" not in symbols and "XOM" not in symbols
    assert symbols == ["SPY", "MSFT", "NVDA"]  # ordinati per momentum decrescente
    assert {c["asset_type"] for c in candidates} <= {"stock", "etf"}


# ------------------------------------------------------------------------ (d)


def test_failing_analyst_returns_empty_without_stopping(tmp_path):
    def raising_llm(**kwargs):
        raise RuntimeError("LLM non raggiungibile")

    deps = make_deps(tmp_path, llm=raising_llm)
    state = {
        "run_id": "r1",
        "candidates": [
            {"instrument_id": 1, "symbol": "AAPL", "display_name": "Apple",
             "asset_type": "stock", "sector": "tech", "current_rate": 200.0},
        ],
    }
    update = run_analyst(state, deps, "fundamental")
    assert update["analyst_reports"] == []
    assert any("analyst_fundamental" in e for e in update["errors"])


# ------------------------------------------------------------------------ (e)


def test_malformed_debate_defaults_to_avoid(tmp_path):
    def garbage_llm(**kwargs):
        return "questo non è JSON"

    deps = make_deps(tmp_path, llm=garbage_llm)
    state = {
        "run_id": "r1",
        "candidates": [
            {"instrument_id": 1, "symbol": "AAPL", "display_name": "Apple",
             "asset_type": "stock", "sector": "tech", "current_rate": 200.0},
        ],
        "analyst_reports": [
            {"analyst": "fundamental", "symbol": "AAPL", "score": 0.9, "summary": "forte"},
        ],
    }
    update = debate(state, deps)
    assert len(update["verdicts"]) == 1
    verdict = update["verdicts"][0]
    assert verdict["decision"] == "avoid"
    assert verdict["conviction"] == 0.0
    assert verdict["transcript"]  # il transcript resta comunque tracciato


# ------------------------------------------------- (f) (g) (h) (i) executor


def _buy_verdict(symbol="AAPL", instrument_id=1, amount=200.0):
    return RiskVerdict(
        order=ProposedOrder(
            symbol=symbol, instrument_id=instrument_id, side=Side.BUY,
            amount_usd=amount, asset_type=AssetType.STOCK, sector="tech",
        ),
        approved=True,
        reasons=["entro tutti i limiti"],
    ).model_dump(mode="json")


def _sell_verdict(symbol="MSFT", instrument_id=2, amount=300.0, position_id=200):
    return RiskVerdict(
        order=ProposedOrder(
            symbol=symbol, instrument_id=instrument_id, side=Side.SELL,
            amount_usd=amount, asset_type=AssetType.STOCK, sector="tech",
            position_id=position_id,
        ),
        approved=True,
        reasons=["chiusura: riduce il rischio"],
    ).model_dump(mode="json")


def _executor_state(run_id, verdicts):
    return {
        "run_id": run_id,
        "portfolio": PortfolioSnapshot(cash_usd=10_000.0).model_dump(mode="json"),
        "risk_verdicts": verdicts,
    }


def test_executor_kill_switch_blocks_every_order(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("ETORO_BOT_KILL", "1")
    repo.create_run("r1", environment="demo")
    client = FakeEtoroClient()
    deps = make_deps(tmp_path, repo=repo, client=client)

    update = executor(_executor_state("r1", [_buy_verdict(), _sell_verdict()]), deps)

    assert all(e["status"] == "skipped" and e["detail"] == "kill_switch"
               for e in update["executions"])
    assert client.open_calls == [] and client.close_calls == []


def test_tripped_breaker_blocks_openings_but_not_closings(repo, tmp_path):
    repo.create_run("r1", environment="demo")
    repo.register_open_position(200, "r1", "MSFT", 2, 300.0, 400.0, NOW, sector="tech")
    client = FakeEtoroClient(
        trade_history=[{"positionId": 200, "netProfit": 5.0, "closeRate": 410.0}]
    )
    deps = make_deps(tmp_path, repo=repo, client=client)
    for _ in range(deps.rules.circuit_breaker.max_consecutive_losses):
        deps.breaker.record_closed_trade(-10.0, 10_000.0)
    assert deps.breaker.blocks_openings()

    update = executor(_executor_state("r1", [_buy_verdict(), _sell_verdict()]), deps)

    by_side = {e["side"]: e for e in update["executions"]}
    assert by_side["buy"]["status"] == "skipped"
    assert by_side["buy"]["detail"] == "circuit_breaker"
    assert by_side["sell"]["status"] == "filled"  # le chiusure passano SEMPRE
    assert client.open_calls == []
    assert client.close_calls == [(200, 2)]
    assert repo.closed_positions()[0].close_reason == "bot_close"


def test_executor_idempotency_reuses_existing_order(repo, tmp_path):
    repo.create_run("r1", environment="demo")
    client = FakeEtoroClient()
    deps = make_deps(tmp_path, repo=repo, client=client)
    state = _executor_state("r1", [_buy_verdict()])

    first = executor(state, deps)["executions"][0]
    second = executor(state, deps)["executions"][0]

    # stesso run_id → stesso request_id deterministico
    assert order_request_id("r1", "AAPL", Side.BUY) == order_request_id("r1", "AAPL", Side.BUY)
    assert len(client.open_calls) == 1  # la seconda esecuzione NON riapre
    assert first["status"] == "filled" and second["status"] == "filled"
    assert second["detail"] == "riusato ordine già eseguito (idempotenza)"
    assert second["etoro_position_id"] == first["etoro_position_id"]
    assert len(repo.open_positions()) == 1


# ------------------------------------------------------------------------ (j)


def test_end_to_end_on_compiled_graph(repo, tmp_path):
    repo.create_run("run-e2e", environment="demo")
    candles = [{"fromDate": f"2026-05-{i:02d}", "open": 99.0, "high": 101.0,
                "low": 98.0, "close": 100.0 + i * 0.1, "volume": 1000} for i in range(1, 29)]
    client = FakeEtoroClient(
        catalogue=[instrument_row("AAPL", 1, type_id=5), instrument_row("SPY", 2, type_id=6)],
        rates={i: {"instrumentID": i, "lastExecution": 100.0} for i in (1, 2)},
        candles={1: candles, 2: candles},
    )
    fake_llm = make_fake_llm(
        judgements={
            "AAPL": {"decision": "open_long", "conviction": 0.8,
                     "rationale": "caso bull nettamente più forte"},
        },
        pm_orders=[{"symbol": "AAPL", "side": "buy", "rationale": "trend solido"}],
    )
    deps = make_deps(
        tmp_path, repo=repo, client=client, llm=fake_llm,
        settings={"watchlist": ["AAPL", "SPY"], "max_candidates_per_run": 2},
        rules=RiskRules(
            max_position_pct_equity=100.0,
            max_total_exposure_pct=100.0,
            max_sector_exposure_pct=100.0,
            min_cash_buffer_pct=0.0,
        ),
    )

    graph = build_graph(deps)  # senza checkpointer
    final_state = graph.invoke({"run_id": "run-e2e", "environment": "demo"})

    # 4 analisti × 2 candidati in parallelo, uniti dal reducer
    assert len(final_state["analyst_reports"]) == 8
    # size: 0,8 × (10.000 credit eToro / 10 posizioni massime) = 800.
    assert final_state["proposed_orders"][0]["amount_usd"] == pytest.approx(800.0)

    summary = repo.get_run("run-e2e").summary_json
    assert summary["candidates"] == 2
    assert summary["proposed"] == 1
    assert summary["approved"] == 1
    assert summary["rejected"] == 0
    # non c'è più una modalità dry-run: l'ordine approvato viene eseguito per davvero
    assert summary["executed"] == 1 and summary["skipped"] == 0
    assert client.open_calls and client.close_calls == []

    stages = {d.stage for d in repo.get_run_decisions("run-e2e")}
    assert {"analyst", "debate", "portfolio", "risk"} <= stages
    executions = repo.list_executions()
    assert len(executions) == 1 and executions[0].status == "filled"
    assert repo.equity_series()  # snapshot equity del giorno registrato
    assert len(repo.open_positions()) == 1  # la posizione è registrata nel bot registry
