"""Nodo portfolio manager (LLM): verdetti open_long/close → ordini proposti.

L'LLM riceve i limiti di rischio come CONTESTO e i trade passati simili
(RAG trade_memory), ma NON applica i limiti: quello è compito esclusivo del
risk gate. La size è calcolata IN CODICE, proporzionale alla conviction:
massimo_trade = equity_disponibile / max_open_positions; amount =
conviction * massimo_trade, arrotondato a 2 decimali.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from etoro_bot.domain import (
    AssetType,
    DebateDecision,
    PortfolioSnapshot,
    ProposedOrder,
    Side,
)
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.llm import extract_json
from etoro_bot.graph.nodes.common import (
    kb_search_trade_memory,
    llm_config,
    resolve_llm,
    system_blocks,
)
from etoro_bot.graph.state import BotState

logger = logging.getLogger(__name__)


def _limits_text(rules) -> str:
    return (
        "- max ordine dinamico: equity disponibile / max posizioni aperte\n"
        f"- max {rules.max_position_pct_equity}% equity per posizione\n"
        f"- max {rules.max_total_exposure_pct}% equity di esposizione totale\n"
        f"- max {rules.max_sector_exposure_pct}% equity per settore\n"
        f"- max {rules.max_open_positions} posizioni aperte, "
        f"{rules.max_orders_per_run} ordini/run, {rules.max_orders_per_day} ordini/giorno\n"
        f"- cash buffer minimo {rules.min_cash_buffer_pct}%\n"
        f"- asset ammessi: {', '.join(rules.allowed_asset_types)}"
    )


def portfolio_manager(state: BotState, deps: GraphDeps) -> dict:
    actionable = {
        v["symbol"]: v
        for v in state.get("verdicts") or []
        if v.get("decision") in (DebateDecision.OPEN_LONG.value, DebateDecision.CLOSE.value)
    }
    if not actionable:
        return {"proposed_orders": []}

    snapshot = PortfolioSnapshot.model_validate(state["portfolio"])
    candidates = {c["symbol"]: c for c in state.get("candidates") or []}
    open_by_symbol: dict = {}
    for pos in snapshot.positions:
        open_by_symbol.setdefault(pos.symbol, pos)

    memory = kb_search_trade_memory(
        deps, "setup simili a: " + ", ".join(sorted(actionable)), limit=3
    )
    memory_text = (
        "\n".join(f"- {str(m.get('text', ''))[:200]}" for m in memory)
        or "(nessun trade passato simile in memoria)"
    )
    verdict_lines = "\n".join(
        f"- {symbol}: {v['decision']} (conviction {float(v.get('conviction') or 0.0):.2f}) — "
        f"{v.get('rationale', '')}"
        for symbol, v in actionable.items()
    )
    prompt = (
        "Sei il PORTFOLIO MANAGER del bot (long-only, swing su stock/ETF).\n"
        "Decidi quali verdetti del debate tradurre in ordini; la size la calcola il "
        "codice in proporzione alla conviction e ogni ordine passerà dal risk gate.\n"
        f"Portafoglio bot: equity {snapshot.equity_usd:.2f} USD, cash "
        f"{snapshot.cash_usd:.2f} USD, {len(snapshot.positions)} posizioni aperte.\n"
        f"Limiti di rischio (SOLO contesto: li applica il risk gate, non tu):\n"
        f"{_limits_text(deps.rules)}\n"
        f"Trade passati simili:\n{memory_text}\n"
        f"Verdetti del debate:\n{verdict_lines}\n\n"
        "Rispondi SOLO con un array JSON "
        '[{"symbol": "...", "side": "buy|sell", "rationale": "..."}]: '
        "side=buy per open_long, side=sell per close. Ometti i verdetti che non condividi."
    )
    model, max_tokens = llm_config(deps)
    try:
        raw = resolve_llm(deps)(
            system_blocks=system_blocks(deps),
            user_prompt=prompt,
            model=model,
            max_tokens=max_tokens,
        )
        items = extract_json(raw)
    except Exception as exc:
        logger.warning("portfolio manager fallito: nessun ordine proposto (%s)", exc)
        return {"proposed_orders": [], "errors": [f"portfolio_manager: {exc}"]}

    orders: list[ProposedOrder] = []
    max_trade_amount = snapshot.cash_usd / deps.rules.max_open_positions
    for item in items if isinstance(items, list) else []:
        try:
            symbol = str(item["symbol"]).upper()
            side = Side(str(item["side"]).lower())
            rationale = str(item.get("rationale", ""))
        except (KeyError, TypeError, ValueError):
            continue  # item malformato: scartato
        verdict = actionable.get(symbol)
        if verdict is None:
            continue  # simbolo mai passato dal debate: scartato
        conviction = min(max(float(verdict.get("conviction") or 0.0), 0.0), 1.0)
        cand = candidates.get(symbol)
        position = open_by_symbol.get(symbol)
        try:
            if side is Side.BUY and verdict["decision"] == DebateDecision.OPEN_LONG.value:
                if cand is None:
                    continue
                amount = round(conviction * max_trade_amount, 2)
                orders.append(
                    ProposedOrder(
                        symbol=symbol,
                        instrument_id=int(cand["instrument_id"]),
                        side=Side.BUY,
                        amount_usd=amount,
                        asset_type=AssetType(cand["asset_type"]),
                        sector=cand.get("sector") or "unknown",
                        rationale=rationale or str(verdict.get("rationale", "")),
                        conviction=conviction,
                    )
                )
            elif side is Side.SELL and verdict["decision"] == DebateDecision.CLOSE.value:
                if position is None:
                    continue  # nessuna posizione BOT aperta su quel simbolo
                orders.append(
                    ProposedOrder(
                        symbol=symbol,
                        instrument_id=position.instrument_id,
                        side=Side.SELL,
                        amount_usd=position.amount_usd,
                        asset_type=AssetType(cand["asset_type"]) if cand else AssetType.STOCK,
                        sector=position.sector,
                        rationale=rationale or str(verdict.get("rationale", "")),
                        conviction=conviction,
                        position_id=position.etoro_position_id,
                    )
                )
        except (ValidationError, KeyError, TypeError, ValueError):
            continue  # ordine non costruibile: scartato

    return {"proposed_orders": [o.model_dump(mode="json") for o in orders]}
