"""Nodi analisti (LLM): quattro prospettive in fan-out parallelo, runner comune.

Output richiesto al modello: array JSON [{"symbol", "score" ∈ [-1,1],
"summary" ≤60 parole}], validato con AnalystReport (item malformati scartati).
Un analista che fallisce logga, scrive errors e ritorna lista vuota: non ferma
mai la run.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from etoro_bot.domain import AnalystReport
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.llm import extract_json
from etoro_bot.graph.nodes.common import (
    kb_search_news,
    llm_config,
    resolve_llm,
    system_blocks,
    ticker_memory_context,
)
from etoro_bot.graph.state import BotState

logger = logging.getLogger(__name__)

ANALYSTS = ("fundamental", "technical", "sentiment", "macro")

_ROLE_PROMPTS = {
    "fundamental": "Sei l'ANALISTA FUNDAMENTAL: utili, multipli, guidance, qualità del business.",
    "technical": "Sei l'ANALISTA TECHNICAL: trend, momentum, medie mobili, supporti/resistenze.",
    "sentiment": "Sei l'ANALISTA SENTIMENT: news recenti, narrativa di mercato, social sentiment.",
    "macro": "Sei l'ANALISTA MACRO: tassi, rotazione settoriale, regime risk-on/risk-off.",
}


def _sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def _fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/d"


def _technical_context(candidate: dict, deps: GraphDeps) -> str:
    """Candele giornaliere ~60 con SMA 20/50 calcolate in codice (mai dall'LLM)."""
    try:
        candles = deps.client.get_candles(
            candidate["instrument_id"], interval="OneDay", count=60
        )
    except Exception as exc:
        return f"candele non disponibili ({exc})"
    closes = [c.get("close") for c in candles if c.get("close") is not None]
    if not closes:
        return "nessuna candela disponibile"
    return (
        f"ultimo close {_fmt(closes[-1])}, SMA20 {_fmt(_sma(closes, 20))}, "
        f"SMA50 {_fmt(_sma(closes, 50))}, min/max 60g {_fmt(min(closes))}/{_fmt(max(closes))}"
    )


def _sentiment_context(candidate: dict, deps: GraphDeps) -> str:
    """Memoria evolutiva del titolo + news recenti dalla KB (già pesate per età)."""
    parts: list[str] = []
    memory = ticker_memory_context(candidate["symbol"])
    if memory:
        parts.append(f"memoria del titolo: {memory}")
    news = kb_search_news(
        deps, f"news su {candidate['symbol']}", tickers=[candidate["symbol"]], limit=5
    )
    if news:
        parts.append(" | ".join(
            f"[{item.get('source', '?')}] {str(item.get('text', ''))[:200]}" for item in news
        ))
    return "\n  ".join(parts) or "nessuna news in knowledge base"


def _candidate_lines(analyst: str, candidates: list[dict], deps: GraphDeps) -> str:
    lines = []
    for cand in candidates:
        line = (
            f"- {cand['symbol']} ({cand.get('display_name', '')}, {cand.get('asset_type')}, "
            f"settore {cand.get('sector')}, prezzo {cand.get('current_rate')})"
        )
        if analyst == "technical":
            line += f"\n  tecnica: {_technical_context(cand, deps)}"
        elif analyst == "sentiment":
            line += f"\n  news: {_sentiment_context(cand, deps)}"
        lines.append(line)
    return "\n".join(lines)


def run_analyst(state: BotState, deps: GraphDeps, analyst: str) -> dict:
    candidates = state.get("candidates") or []
    if not candidates:
        return {"analyst_reports": []}
    try:
        prompt = (
            f"{_ROLE_PROMPTS[analyst]}\n"
            "Bot di swing trading long-only su stock/ETF (orizzonte giorni/settimane).\n"
            "Valuta i candidati dal tuo punto di vista.\n"
            "Candidati:\n"
            f"{_candidate_lines(analyst, candidates, deps)}\n\n"
            "Rispondi SOLO con un array JSON, un item per candidato:\n"
            '[{"symbol": "...", "score": <float in [-1,1]>, "summary": "<max 60 parole>"}]'
        )
        model, max_tokens = llm_config(deps)
        raw = resolve_llm(deps)(
            system_blocks=system_blocks(deps),
            user_prompt=prompt,
            model=model,
            max_tokens=max_tokens,
        )
        data = extract_json(raw)
        allowed = {c["symbol"] for c in candidates}
        reports: list[dict] = []
        for item in data if isinstance(data, list) else []:
            try:
                report = AnalystReport(
                    analyst=analyst,
                    symbol=str(item["symbol"]).upper(),
                    score=float(item["score"]),
                    summary=str(item.get("summary", "")),
                )
            except (ValidationError, KeyError, TypeError, ValueError):
                continue  # item malformato: scartato
            if report.symbol in allowed:
                reports.append(report.model_dump(mode="json"))
        return {"analyst_reports": reports}
    except Exception as exc:
        logger.warning("analista %s fallito (la run prosegue): %s", analyst, exc)
        return {"analyst_reports": [], "errors": [f"analyst_{analyst}: {exc}"]}
