"""API REST del bot (FastAPI) — contratto §12.3.

Nessuna autenticazione: pensata per girare solo dietro la rete interna del
compose / localhost. Le chiavi API non sono mai esposte (solo configured sì/no).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from etoro_bot.config import load_settings
from etoro_bot.db.repo import Repository, make_engine, make_session_factory
from etoro_bot.safety.circuit_breaker import CircuitBreaker
from etoro_bot.safety.kill_switch import (
    engage_kill_switch,
    kill_switch_active,
    release_kill_switch,
)

log = logging.getLogger("etoro_bot.api")

from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _start_scheduler()
    yield


app = FastAPI(title="Trading Bot API", version="3.0.0", lifespan=_lifespan)


@dataclass(frozen=True)
class UserIdentity:
    user_id: str
    email: str | None = None
    name: str | None = None


def current_user(
    x_trading_user_id: str = Header("system"),
    x_trading_user_email: str | None = Header(None),
    x_trading_user_name: str | None = Header(None),
) -> UserIdentity:
    return UserIdentity(
        user_id=x_trading_user_id.strip() or "system",
        email=x_trading_user_email,
        name=x_trading_user_name,
    )


def _user_keys(identity: UserIdentity):
    from etoro_bot.services.user_credentials import get_user_keys

    return get_user_keys(get_repo(), identity.user_id)


def _start_scheduler() -> None:
    if os.environ.get("DISABLE_SCHEDULER") == "1":
        return
    try:
        from etoro_bot.services.scheduler import start_scheduler

        def _run_job() -> None:
            from etoro_bot.graph.runner import RunInProgressError, run_pipeline

            try:
                run_pipeline()
            except RunInProgressError:
                log.warning("run schedulata saltata: run già in corso")

        def _news_job() -> None:
            from etoro_bot.knowledge.pipeline import run_news_pipeline

            run_news_pipeline(
                kb=_kb(),
                settings=_full_settings(),
                client=_system_etoro_client(),
                llm=_system_llm(),
            )
            _mark_fetch(UserIdentity("system"))

        start_scheduler(
            get_settings=lambda: get_settings_service().get_effective(),
            run_job=_run_job,
            news_job=_news_job,
        )
    except Exception:
        log.exception("scheduler non avviato")


@lru_cache(maxsize=1)
def get_repo() -> Repository:
    return Repository(make_session_factory(make_engine()))


def get_breaker() -> CircuitBreaker:
    from etoro_bot.services.app_settings import effective_risk_rules

    return CircuitBreaker(effective_risk_rules(get_repo()).circuit_breaker)


def get_settings_service():
    from etoro_bot.services.app_settings import AppSettingsService

    return AppSettingsService(get_repo())


def _full_settings() -> dict[str, Any]:
    """Settings completi: default yaml + override runtime (DB > yaml).

    get_effective() restituisce SOLO le chiavi runtime gestite dal DB
    (environment, orari, valuta, risk_limits): per watchlist, news_feeds,
    universe_discovery, knowledge e llm serve la base yaml — stesso pattern
    di graph.runner._effective_settings.
    """
    return {**load_settings(), **get_settings_service().get_effective()}


# --- health & status --------------------------------------------------------


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
def status() -> dict[str, Any]:
    from etoro_bot.graph.runner import is_run_in_progress

    settings = get_settings_service().get_effective()
    breaker = get_breaker()
    repo = get_repo()

    equity_usd = None
    equity_change_day_pct = None
    try:
        series = repo.equity_series()
        if series:
            equity_usd = series[-1].equity_usd
            if len(series) >= 2 and series[-2].equity_usd:
                equity_change_day_pct = (
                    (series[-1].equity_usd - series[-2].equity_usd)
                    / series[-2].equity_usd * 100
                )
    except Exception:  # DB giù: lo status resta consultabile
        log.warning("equity series non disponibile", exc_info=True)

    return {
        "environment": settings["environment"],
        "kill_switch_active": kill_switch_active(),
        "circuit_breaker": {
            "tripped": breaker.blocks_openings(),
            "reason": breaker.state.reason,
            "until": breaker.state.cooloff_until,
        },
        "run_in_progress": is_run_in_progress(),
        "next_run_at": _next_run_at(settings),
        "equity_usd": equity_usd,
        "equity_change_day_pct": equity_change_day_pct,
    }


def _next_run_at(settings: dict[str, Any]) -> str | None:
    try:
        from etoro_bot.services.scheduler import next_run_at

        return next_run_at(settings)
    except Exception:
        return None


# --- runs / executions ------------------------------------------------------


@app.get("/runs")
def list_runs(limit: int = Query(50, le=500)) -> dict[str, Any]:
    runs = get_repo().list_runs(limit=limit)
    return {
        "runs": [
            {
                "run_id": r.run_id,
                "started_at": r.started_at.isoformat(),
                "environment": r.environment,
                "summary": r.summary_json,
            }
            for r in runs
        ]
    }


@app.delete("/runs/{run_id}")
def delete_run(run_id: str) -> dict[str, Any]:
    """Cancella una run e tutto ciò che ne discende (decisioni, esecuzioni,
    posizioni registrate). Serve a ripulire le prove: il journal deve
    contenere solo run vere."""
    if not get_repo().delete_run(run_id):
        raise HTTPException(404, "run non trovata")
    return {"deleted": True, "run_id": run_id}


@app.get("/runs/{run_id}/decisions")
def run_decisions(run_id: str) -> dict[str, Any]:
    run = get_repo().get_run(run_id)
    if run is None:
        raise HTTPException(404, "run non trovata")
    decisions = get_repo().get_run_decisions(run_id)
    return {
        "run_id": run_id,
        # Anagrafica della run insieme alle decisioni: la pagina di dettaglio
        # deve poter dire quando è partita e come è finita senza rileggere
        # l'elenco (che tiene solo le ultime N run).
        "run": {
            "run_id": run.run_id,
            "started_at": run.started_at.isoformat(),
            "environment": run.environment,
            "summary": run.summary_json,
        },
        "decisions": [
            {
                "id": str(d.id),
                "symbol": d.symbol,
                "stage": d.stage,
                "payload": d.payload,
                "created_at": d.created_at.isoformat(),
            }
            for d in decisions
        ],
    }


@app.get("/executions")
def list_executions(limit: int = Query(50, le=500)) -> dict[str, Any]:
    rows = get_repo().list_executions(limit=limit)
    return {
        "executions": [
            {
                "id": str(e.id),
                "run_id": e.run_id,
                "symbol": e.symbol,
                "side": e.side,
                "amount_usd": e.amount_usd,
                "status": e.status,
                "detail": e.detail,
                "execution_price": e.execution_price,
                "etoro_position_id": e.etoro_position_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in rows
        ]
    }


# --- portfolio (solo posizioni bot, §7) -------------------------------------


@app.get("/portfolio")
def portfolio(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    repo = get_repo()
    settings = get_settings_service().get_effective()
    positions = repo.open_positions()

    rates: dict[int, float] = {}
    try:
        client = _make_client(settings, identity)
        account_portfolio = client.get_portfolio()
        if account_portfolio.get("credit") is None:
            raise ValueError("portfolio eToro senza campo credit")
        cash_usd = max(float(account_portfolio["credit"]), 0.0)
        raw = client.get_rates([p.instrument_id for p in positions]) if positions else {}
        for iid, r in raw.items():
            price = r.get("lastExecution") or r.get("bid")
            if price:
                rates[int(iid)] = float(price)
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("portafoglio eToro non disponibile", exc_info=True)
        raise HTTPException(502, f"Capitale eToro non disponibile: {exc}") from exc

    invested = sum(p.amount_usd for p in positions)

    out = []
    for p in positions:
        cur = rates.get(p.instrument_id)
        pnl = None
        pnl_pct = None
        if cur is not None and p.entry_price > 0:
            pnl = p.amount_usd * (cur - p.entry_price) / p.entry_price
            pnl_pct = (cur - p.entry_price) / p.entry_price * 100
        out.append(
            {
                "etoro_position_id": p.etoro_position_id,
                "symbol": p.symbol,
                "instrument_id": p.instrument_id,
                "amount_usd": p.amount_usd,
                "entry_price": p.entry_price,
                "current_price": cur,
                "unrealized_pnl_usd": pnl,
                "unrealized_pnl_pct": pnl_pct,
                "sector": p.sector,
                "opened_at": p.opened_at.isoformat(),
            }
        )

    anomalies = []
    try:
        for d in _recent_anomalies(repo):
            anomalies.append(d)
    except Exception:
        pass

    from etoro_bot.services.app_settings import effective_risk_rules

    rules = effective_risk_rules(repo)
    return {
        "positions": out,
        "cash_usd": cash_usd,
        "equity_usd": cash_usd + invested,
        "exposure_usd": invested,
        "max_trade_amount_usd": cash_usd / rules.max_open_positions,
        "capital_source": "etoro",
        "anomalies": anomalies,
    }


def _recent_anomalies(repo: Repository, limit: int = 20) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for r in repo.list_runs(limit=10):
        for d in repo.get_run_decisions(r.run_id):
            if d.stage == "reconcile_anomaly":
                anomalies.append(
                    {
                        "symbol": d.symbol,
                        "detail": d.payload.get("detail", str(d.payload)),
                        "detected_at": d.created_at.isoformat(),
                    }
                )
    return anomalies[:limit]


def _make_client(settings: dict[str, Any], identity: UserIdentity):
    from etoro_bot.etoro.client import EtoroClient

    keys = _user_keys(identity)
    if not keys.etoro_configured:
        raise HTTPException(422, "Configura le chiavi eToro personali in Impostazioni")
    return EtoroClient(
        api_key=keys.etoro_api_key,
        user_key=keys.etoro_user_key,
        environment=settings["environment"],
    )


# --- backtest ---------------------------------------------------------------


def _backtest_service(identity: UserIdentity):
    from etoro_bot.services.backtest import BacktestService

    def price_fetcher(symbol: str, start_date):
        from datetime import date as _date

        settings = get_settings_service().get_effective()
        client = _make_client(settings, identity)
        found = client.search_instruments(
            {"internalSymbolFull": symbol},
            fields=["instrumentId", "internalSymbolFull"],
        )
        if not found:
            return {}
        iid = int(found[0]["instrumentId"])
        days = max((datetime.now(timezone.utc).date() - start_date).days + 5, 30)
        candles = client.get_candles(iid, interval="OneDay", count=min(days, 1000))
        out: dict[_date, float] = {}
        for c in candles:
            day = datetime.fromisoformat(c["fromDate"].replace("Z", "+00:00")).date()
            out[day] = float(c["close"])
        return out

    return BacktestService(get_repo(), price_fetcher)


def _pct(value: float | None) -> float | None:
    return None if value is None else value * 100.0


@app.get("/backtest/summary")
def backtest_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    identity: UserIdentity = Depends(current_user),
) -> dict[str, Any]:
    s = _backtest_service(identity).summary(date_from=date_from, date_to=date_to)
    return {
        "metrics": {
            "total_return_pct": _pct(s["total_return"]),
            "cagr_pct": _pct(s["cagr"]),
            "volatility_pct": _pct(s["annualized_volatility"]),
            "sharpe": s["sharpe"],
            "sortino": s["sortino"],
            "max_drawdown_pct": _pct(s["max_drawdown"]),
            "calmar": s["calmar"],
            "alpha": s["alpha"],
            "beta": s["beta"],
            "information_ratio": s["information_ratio"],
            "win_rate_pct": _pct(s["win_rate"]),
            "profit_factor": s["profit_factor"],
            "recovery_factor": s["recovery_factor"],
            "expectancy_usd": s["expectancy"],
            "exposure_pct": s["exposure_pct"],
            "max_win_usd": s["max_win_usd"],
            "max_loss_usd": s["max_loss_usd"],
            "std_win_usd": s["std_win_usd"],
            "std_loss_usd": s["std_loss_usd"],
        },
        "n_closed_trades": s["n_closed_trades"],
        "n_days": s["n_days"],
        "insufficient_sample": s["insufficient_sample"],
        "annualization_available": s["annualization_available"],
        "risk_free_rate_pct": s["risk_free_rate_pct"],
    }


SPY_DIVIDEND_NOTE = (
    "Il prezzo SPY non include i dividendi (~1.3-1.5%/anno di total return in più): "
    "il confronto sottostima leggermente il benchmark."
)


@app.get("/backtest/equity-curve")
def backtest_equity_curve(
    benchmark: str = "spy",
    date_from: date | None = None,
    date_to: date | None = None,
    identity: UserIdentity = Depends(current_user),
) -> dict[str, Any]:
    return {
        "points": _backtest_service(identity).equity_curve(
            benchmark=benchmark, date_from=date_from, date_to=date_to
        ),
        "note_dividends": SPY_DIVIDEND_NOTE,
    }


@app.get("/backtest/trades")
def backtest_trades(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    return {"trades": _backtest_service(identity).trades()}


@app.get("/backtest/monthly-returns")
def backtest_monthly_returns(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    return {"rows": _backtest_service(identity).monthly_returns()}


# --- risk score -------------------------------------------------------------


@app.get("/risk/score")
def risk_score() -> dict[str, Any]:
    from etoro_bot.services.risk_score import RiskScoreService
    from etoro_bot.services.app_settings import effective_risk_rules

    repo = get_repo()
    result = RiskScoreService(repo, risk_rules=effective_risk_rules(repo)).compute_and_store()
    return {"score": result.score, "band": result.band, "components": result.breakdown}


@app.get("/risk/score/history")
def risk_score_history() -> dict[str, Any]:
    rows = get_repo().risk_score_history()
    return {"points": [{"date": r.date.isoformat(), "score": r.score} for r in rows]}


# --- knowledge --------------------------------------------------------------


def _kb():
    from etoro_bot.knowledge.kb import KnowledgeBase

    return KnowledgeBase()


def _system_etoro_client():
    """Client eToro con le chiavi dell'account proprietario, per i job di
    sistema (discovery universo). None se le chiavi non sono configurate:
    la pipeline news degrada senza refresh dell'universo."""
    try:
        from etoro_bot.etoro.client import EtoroClient
        from etoro_bot.services.user_credentials import get_user_keys

        repo = get_repo()
        user_id = repo.owner_user_id() or "system"
        keys = get_user_keys(repo, user_id)
        if not keys.etoro_api_key or not keys.etoro_user_key:
            return None
        settings = get_settings_service().get_effective()
        return EtoroClient(
            api_key=keys.etoro_api_key,
            user_key=keys.etoro_user_key,
            environment=str(settings.get("environment", "demo")),
        )
    except Exception:
        log.warning("client eToro di sistema non disponibile", exc_info=True)
        return None


def _system_llm():
    """call_llm con la chiave OpenAI del proprietario, per i job di sistema
    (scout universo, sintesi memorie ticker). None se non configurata: i
    consumatori degradano da soli (fallback regex/headline)."""
    try:
        from functools import partial

        from etoro_bot.services.user_credentials import get_user_keys

        repo = get_repo()
        keys = get_user_keys(repo, repo.owner_user_id() or "system")
        if not keys.openai_api_key:
            return None
        import openai

        from etoro_bot.graph.llm import call_llm

        return partial(call_llm, client=openai.OpenAI(api_key=keys.openai_api_key))
    except Exception:
        log.warning("LLM di sistema non disponibile", exc_info=True)
        return None


def _user_setting_key(prefix: str, user_id: str) -> str:
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}:{digest}"


def _rss_feeds(identity: UserIdentity) -> list[str]:
    stored = get_repo().get_setting(_user_setting_key("rss", identity.user_id))
    if isinstance(stored, list):
        return [str(item) for item in stored]
    feeds = load_settings().get("news_feeds", {})
    return list(feeds.get("generic", [])) + list(feeds.get("per_ticker", []))


@app.get("/knowledge/status")
def knowledge_status(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    st = _kb().status()
    st["rss_feeds"] = _rss_feeds(identity)
    st["last_fetch"] = _last_fetch_marker(identity)
    return st


_LAST_FETCH_FILE = "last_news_fetch"


def _user_state_file(identity: UserIdentity, name: str) -> Path:
    digest = hashlib.sha256(identity.user_id.encode("utf-8")).hexdigest()[:24]
    path = Path(os.environ.get("KILL_SWITCH_DIR", ".")) / "users" / digest
    path.mkdir(parents=True, exist_ok=True)
    return path / name


def _last_fetch_marker(identity: UserIdentity) -> str | None:
    path = _user_state_file(identity, _LAST_FETCH_FILE)
    if path.exists():
        return path.read_text(encoding="utf-8").strip() or None
    return None


def _mark_fetch(identity: UserIdentity) -> None:
    path = _user_state_file(identity, _LAST_FETCH_FILE)
    path.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")


class RssFeedsBody(BaseModel):
    feeds: list[str]


@app.put("/knowledge/rss-feeds")
def update_rss_feeds(
    body: RssFeedsBody, identity: UserIdentity = Depends(current_user)
) -> dict[str, Any]:
    from etoro_bot.knowledge.safe_fetch import UnsafeUrlError, assert_public_url

    feeds: list[str] = []
    for raw in body.feeds:
        value = raw.strip()
        if not value:
            continue
        if not value.startswith(("https://", "http://")):
            raise HTTPException(422, f"URL feed non valido: {value}")
        # Il backend scarica questi URL da dentro la rete Docker: un feed che
        # punta a un servizio interno lo trasformerebbe in una sonda, con la
        # risposta indicizzata e poi leggibile dalla pagina News.
        try:
            assert_public_url(value)
        except UnsafeUrlError as exc:
            raise HTTPException(422, f"URL feed non ammesso: {exc}") from exc
        if value not in feeds:
            feeds.append(value)
    if len(feeds) > 50:
        raise HTTPException(422, "Massimo 50 feed RSS")
    get_repo().set_setting(_user_setting_key("rss", identity.user_id), feeds, source="api")
    return {"rss_feeds": feeds}


def _news_file(identity: UserIdentity) -> Path:
    return _user_state_file(identity, "latest_news.json")


@app.get("/news")
def latest_news(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    path = _news_file(identity)
    if not path.exists():
        return {"items": [], "updated_at": None}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"items": [], "updated_at": None}
    return payload


@app.post("/knowledge/fetch-news", status_code=202)
def knowledge_fetch_news(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    def _job() -> None:
        try:
            from etoro_bot.knowledge.fetch_news import fetch_all
            from etoro_bot.knowledge.pipeline import run_news_pipeline

            settings = load_settings()
            settings["news_feeds"] = {"generic": _rss_feeds(identity), "per_ticker": []}
            items = fetch_all(settings)
            run_news_pipeline(
                kb=_kb(), settings=settings, items=items,
                client=_system_etoro_client(), llm=_system_llm(),
            )
            updated_at = datetime.now(timezone.utc).isoformat()
            _news_file(identity).write_text(
                json.dumps({"items": items[:60], "updated_at": updated_at}, ensure_ascii=False),
                encoding="utf-8",
            )
            _mark_fetch(identity)
            log.info("fetch news: %d item indicizzati", len(items))
        except Exception:
            log.exception("fetch news fallito")

    threading.Thread(target=_job, daemon=True).start()
    return {"status": "accepted"}


_UPLOAD_SUFFIXES = (".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt")


@app.post("/knowledge/ingest")
async def knowledge_ingest(
    file: UploadFile = File(...),
    identity: UserIdentity = Depends(current_user),
) -> dict[str, Any]:
    from etoro_bot.knowledge.ingest import ingest_upload
    from etoro_bot.knowledge.parsers import UnsupportedFileTypeError

    filename = file.filename or ""
    if not filename.lower().endswith(_UPLOAD_SUFFIXES):
        raise HTTPException(
            415,
            f"estensione non supportata per '{filename}': estensioni ammesse "
            f"{', '.join(_UPLOAD_SUFFIXES)}",
        )

    content = await file.read()
    try:
        outcome = ingest_upload(filename, content, kb=_kb())
    except (UnsupportedFileTypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    safe_name = Path(filename).name
    upload_dir = Path(os.environ.get("KNOWLEDGE_BASE_DIR", "/app/knowledge_base")) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(identity.user_id.encode("utf-8")).hexdigest()[:12]
    (upload_dir / f"{digest}-{safe_name}").write_bytes(content)
    return {
        "filename": filename,
        "chunks_indexed": outcome.chunks,
        "tickers": outcome.tickers,
    }


@app.get("/knowledge/ticker-memory")
def knowledge_ticker_memory(
    ticker: str | None = Query(None), identity: UserIdentity = Depends(current_user)
) -> dict[str, Any]:
    from etoro_bot.knowledge.ticker_memory import all_memories, load_memory

    if ticker:
        memory = load_memory(ticker)
        return {"memories": [memory] if memory else []}
    return {"memories": all_memories()}


# --- universo dinamico ------------------------------------------------------


@app.get("/universe")
def universe_view(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    from etoro_bot.services.universe import discovery_config, load_discovery_state

    settings = _full_settings()
    state = load_discovery_state(settings)
    return {
        "watchlist": [str(s).upper() for s in settings.get("watchlist") or []],
        "discovered": (state or {}).get("tickers") or [],
        "generated_at": (state or {}).get("generated_at"),
        "enabled": bool(discovery_config(settings)["enabled"]),
    }


@app.post("/universe/refresh", status_code=202)
def universe_refresh(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    """Discovery on-demand (fetch news + screening); gira in background.

    Usa le chiavi eToro del proprietario: se un proprietario esiste, solo lui
    (o il job di sistema) può forzare la discovery. Come per il resto
    dell'API, l'identità arriva dagli header del proxy interno.
    """
    try:
        owner = get_repo().owner_user_id()
    except Exception:
        owner = None
    if owner and identity.user_id not in ("system", owner):
        raise HTTPException(403, "solo il proprietario può forzare la discovery")

    def _job() -> None:
        try:
            from etoro_bot.knowledge.fetch_news import fetch_all
            from etoro_bot.services.universe import refresh_universe

            client = _system_etoro_client()
            if client is None:
                log.warning("refresh universo saltato: chiavi eToro non configurate")
                return
            settings = _full_settings()
            refresh_universe(client, settings, fetch_all(settings), llm=_system_llm())
        except Exception:
            log.exception("refresh universo fallito")

    threading.Thread(target=_job, daemon=True).start()
    return {"status": "accepted"}


# --- trade operativi e storico --------------------------------------------


@app.get("/trades")
def trades(
    statuses: str | None = None,
    symbol: str | None = None,
    identity: UserIdentity = Depends(current_user),
) -> dict[str, Any]:
    repo = get_repo()
    rows: list[dict[str, Any]] = []
    for position in repo.open_positions():
        rows.append(
            {
                "id": f"position:{position.etoro_position_id}",
                "position_id": position.etoro_position_id,
                "execution_id": None,
                "symbol": position.symbol,
                "side": "buy",
                "status": "open",
                "amount_usd": position.amount_usd,
                "entry_price": position.entry_price,
                "current_price": None,
                "pnl_usd": None,
                "created_at": position.opened_at.isoformat(),
                "detail": "Posizione aperta",
                "can_close": True,
                "can_cancel": False,
            }
        )
    for execution in repo.list_executions(limit=500):
        if execution.status == "filled" and execution.etoro_position_id:
            continue
        rows.append(
            {
                "id": f"execution:{execution.id}",
                "position_id": execution.etoro_position_id,
                "execution_id": str(execution.id),
                "symbol": execution.symbol,
                "side": execution.side,
                "status": execution.status,
                "amount_usd": execution.amount_usd,
                "entry_price": execution.execution_price,
                "current_price": None,
                "pnl_usd": None,
                "created_at": execution.created_at.isoformat(),
                "detail": execution.detail,
                "can_close": False,
                "can_cancel": execution.status == "pending",
            }
        )
    selected_statuses = {
        value.strip() for value in (statuses or "").split(",") if value.strip()
    }
    if selected_statuses:
        rows = [row for row in rows if row["status"] in selected_statuses]
    if symbol:
        needle = symbol.strip().upper()
        rows = [row for row in rows if needle in row["symbol"].upper()]
    rows.sort(key=lambda row: row["created_at"], reverse=True)
    return {"trades": rows}


class CloseTradeBody(BaseModel):
    confirmation: str


@app.post("/trades/{position_id}/close")
def close_trade(
    position_id: int,
    body: CloseTradeBody,
    identity: UserIdentity = Depends(current_user),
) -> dict[str, Any]:
    if body.confirmation != "CHIUDI":
        raise HTTPException(422, "Conferma non valida: digita CHIUDI")
    repo = get_repo()
    position = repo.get_open_position(position_id)
    if position is None:
        raise HTTPException(404, "Posizione aperta non trovata")
    client = _make_client(get_settings_service().get_effective(), identity)
    client.close_position(position_id, position.instrument_id)
    close_price = None
    pnl = None
    try:
        for item in client.get_trade_history():
            if int(item.get("positionId") or -1) == position_id:
                close_price = item.get("closeRate")
                pnl = item.get("netProfit")
                break
    except Exception:
        log.warning("chiusura %s eseguita, dettaglio PnL non ancora disponibile", position_id)
    repo.close_position(
        position_id,
        close_price=float(close_price) if close_price is not None else None,
        realized_pnl_usd=float(pnl) if pnl is not None else None,
        close_reason="manual_close",
    )
    return {"status": "closed", "position_id": position_id}


@app.post("/executions/{execution_id}/cancel")
def cancel_execution(execution_id: uuid.UUID) -> dict[str, Any]:
    if not get_repo().cancel_pending_execution(execution_id):
        raise HTTPException(409, "L'ordine non è annullabile: è già terminale o inesistente")
    return {"status": "cancelled", "execution_id": str(execution_id)}


@app.get("/trade-history")
def trade_history(
    statuses: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    symbol: str | None = None,
    identity: UserIdentity = Depends(current_user),
) -> dict[str, Any]:
    repo = get_repo()
    items: list[dict[str, Any]] = []
    for position in repo.open_positions():
        items.append(
            {
                "id": f"position:{position.etoro_position_id}",
                "symbol": position.symbol,
                "side": "buy",
                "status": "open",
                "amount_usd": position.amount_usd,
                "price": position.entry_price,
                "pnl_usd": None,
                "opened_at": position.opened_at.isoformat(),
                "closed_at": None,
                "detail": "Posizione aperta",
            }
        )
    for position in repo.closed_positions():
        items.append(
            {
                "id": f"position:{position.etoro_position_id}",
                "symbol": position.symbol,
                "side": "sell",
                "status": "closed",
                "amount_usd": position.amount_usd,
                "price": position.close_price,
                "pnl_usd": position.realized_pnl_usd,
                "opened_at": position.opened_at.isoformat(),
                "closed_at": position.closed_at.isoformat() if position.closed_at else None,
                "detail": position.close_reason,
            }
        )
    for execution in repo.list_executions(limit=500):
        if execution.status == "filled":
            continue
        items.append(
            {
                "id": f"execution:{execution.id}",
                "symbol": execution.symbol,
                "side": execution.side,
                "status": execution.status,
                "amount_usd": execution.amount_usd,
                "price": execution.execution_price,
                "pnl_usd": None,
                "opened_at": execution.created_at.isoformat(),
                "closed_at": execution.created_at.isoformat(),
                "detail": execution.detail,
            }
        )
    selected_statuses = {
        value.strip() for value in (statuses or "").split(",") if value.strip()
    }
    if selected_statuses:
        items = [item for item in items if item["status"] in selected_statuses]
    if symbol:
        needle = symbol.strip().upper()
        items = [item for item in items if needle in item["symbol"].upper()]
    if date_from or date_to:
        def in_range(item: dict[str, Any]) -> bool:
            raw = item["closed_at"] or item["opened_at"]
            day = datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
            return (date_from is None or day >= date_from) and (
                date_to is None or day <= date_to
            )
        items = [item for item in items if in_range(item)]
    items.sort(key=lambda row: row["closed_at"] or row["opened_at"], reverse=True)
    return {"items": items}


# --- report su filesystem locale ------------------------------------------


def _reports():
    from etoro_bot.services.reports import ReportService

    return ReportService(get_repo())


@app.get("/reports")
def list_reports(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    return {"reports": _reports().list(identity.user_id)}


@app.get("/reports/{cadence}/{filename}")
def read_report(
    cadence: str,
    filename: str,
    download: bool = False,
    identity: UserIdentity = Depends(current_user),
):
    try:
        content, path = _reports().read(identity.user_id, f"{cadence}/{filename}")
    except FileNotFoundError as exc:
        raise HTTPException(404, "Report non trovato") from exc
    if download:
        return FileResponse(path, media_type="text/markdown", filename=path.name)
    return {"id": f"{cadence}/{filename}", "content": content}


# --- settings (§10) ---------------------------------------------------------


class SettingsBody(BaseModel):
    environment: str | None = None
    schedule_utc: str | None = None
    timezone: str | None = None
    currency: str | None = None
    weekdays_only: bool | None = None
    risk_limits: dict[str, float | int] | None = None
    confirmation: bool | None = None


class CredentialsBody(BaseModel):
    etoro_api_key: str | None = None
    etoro_user_key: str | None = None
    openai_api_key: str | None = None


@app.get("/account/credentials")
def account_credentials(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    keys = _user_keys(identity)
    return {
        "user_id": identity.user_id,
        "email": identity.email,
        "display_name": identity.name,
        "etoro_api_key_configured": bool(keys.etoro_api_key),
        "etoro_user_key_configured": bool(keys.etoro_user_key),
        "openai_api_key_configured": bool(keys.openai_api_key),
    }


@app.put("/account/credentials")
def put_account_credentials(
    body: CredentialsBody, identity: UserIdentity = Depends(current_user)
) -> dict[str, Any]:
    from etoro_bot.services.user_credentials import update_user_keys

    keys = update_user_keys(
        get_repo(),
        identity.user_id,
        email=identity.email,
        display_name=identity.name,
        **body.model_dump(),
    )
    return {
        "user_id": identity.user_id,
        "email": identity.email,
        "display_name": identity.name,
        "etoro_api_key_configured": bool(keys.etoro_api_key),
        "etoro_user_key_configured": bool(keys.etoro_user_key),
        "openai_api_key_configured": bool(keys.openai_api_key),
    }


@app.get("/fx/rates")
def fx_rates(refresh: bool = False) -> dict[str, Any]:
    """Tassi USD→valuta + elenco delle valute selezionabili.

    Il journal resta in dollari (eToro ragiona in USD): la conversione è solo
    di presentazione e avviene lato UI con questi tassi.
    """
    from etoro_bot.services.fx import CURRENCY_LABELS, SUPPORTED_CURRENCIES, get_rates

    payload = get_rates(force=refresh)
    payload["currencies"] = [
        {"code": code, "label": CURRENCY_LABELS.get(code, code)}
        for code in SUPPORTED_CURRENCIES
    ]
    return payload


@app.get("/settings")
def get_settings(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    svc = get_settings_service()
    effective = svc.get_effective()
    effective.update(
        {
            "api_keys_configured": _user_keys(identity).etoro_configured,
            "openai_configured": bool(_user_keys(identity).openai_api_key),
        }
    )
    return effective


@app.put("/settings")
def put_settings(
    body: SettingsBody, identity: UserIdentity = Depends(current_user)
) -> dict[str, Any]:
    from etoro_bot.services.app_settings import SettingsValidationError

    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return get_settings_service().update(
            changes,
            source="api",
            etoro_configured=_user_keys(identity).etoro_configured,
        )
    except SettingsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/settings/audit")
def settings_audit() -> dict[str, Any]:
    rows = get_repo().settings_audit()
    return {
        "entries": [
            {
                "id": str(r.id),
                "changed_at": r.changed_at.isoformat(),
                "key": r.key,
                "old_value": r.old_value,
                "new_value": r.new_value,
                "source": r.source,
            }
            for r in rows
        ]
    }


# --- run & kill switch ------------------------------------------------------


@app.post("/run", status_code=202)
def trigger_run(identity: UserIdentity = Depends(current_user)) -> dict[str, Any]:
    from etoro_bot.graph.runner import (
        RunInProgressError,
        is_run_in_progress,
        run_pipeline,
    )

    if is_run_in_progress():
        raise HTTPException(409, "run già in corso")

    result: dict[str, Any] = {}

    def _job() -> None:
        try:
            result.update(run_pipeline(user_id=identity.user_id))
        except RunInProgressError:
            pass
        except Exception:
            log.exception("run fallita")

    thread = threading.Thread(target=_job, daemon=True)
    thread.start()
    return {"status": "accepted"}


@app.post("/kill-switch")
def activate_kill_switch() -> dict[str, Any]:
    engage_kill_switch("api")
    return {"kill_switch_active": True}


@app.delete("/kill-switch")
def deactivate_kill_switch() -> dict[str, Any]:
    release_kill_switch()
    return {"kill_switch_active": kill_switch_active()}
