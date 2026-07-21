"""Nodo executor: UNICO punto della pipeline che tocca denaro.

Ogni ordine approvato dal risk gate viene eseguito per davvero, nell'ambiente
scelto (demo o real): l'unico modo per non muovere denaro reale è l'ambiente
demo di eToro stesso, oppure i due guardrail di sicurezza qui sotto. Prima di
OGNI singolo ordine: kill switch (blocca tutto), poi circuit breaker (blocca
SOLO le aperture, mai le chiusure). Idempotenza: request_id = UUID5
deterministico di (run_id, symbol, side); prima di aprire si tenta
lookup_order(reference_id): se l'ordine esiste già Filled, il risultato viene
riusato senza duplicare. Errori per-ordine → FAILED, la coda prosegue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from etoro_bot.domain import (
    ExecutionResult,
    ExecutionStatus,
    PortfolioSnapshot,
    ProposedOrder,
    RiskVerdict,
    Side,
    order_request_id,
)
from etoro_bot.etoro.client import ORDER_STATUS_FILLED
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.state import BotState
from etoro_bot.safety.kill_switch import kill_switch_active

logger = logging.getLogger(__name__)


def executor(state: BotState, deps: GraphDeps) -> dict:
    run_id = state["run_id"]
    equity = (
        PortfolioSnapshot.model_validate(state["portfolio"]).equity_usd
        if state.get("portfolio")
        else 0.0
    )
    results: list[dict] = []
    for raw in state.get("risk_verdicts") or []:
        verdict = RiskVerdict.model_validate(raw)
        if not verdict.approved:
            continue
        result = _execute_one(verdict.order, run_id, equity, deps)
        deps.repo.add_execution(run_id, result)
        results.append(result.model_dump(mode="json"))
    return {"executions": results}


def _skipped(order: ProposedOrder, detail: str) -> ExecutionResult:
    return ExecutionResult(
        symbol=order.symbol,
        side=order.side,
        amount_usd=order.amount_usd,
        status=ExecutionStatus.SKIPPED,
        detail=detail,
        etoro_position_id=order.position_id,
    )


def _execute_one(
    order: ProposedOrder, run_id: str, equity: float, deps: GraphDeps
) -> ExecutionResult:
    if kill_switch_active():
        return _skipped(order, "kill_switch")
    if order.side is Side.BUY and deps.breaker.blocks_openings():
        return _skipped(order, "circuit_breaker")  # le chiusure passano sempre

    try:
        if order.side is Side.BUY:
            request_id = order_request_id(run_id, order.symbol, order.side)
            return _open(order, run_id, request_id, deps)
        return _close(order, equity, deps)
    except Exception as exc:
        logger.warning("esecuzione %s %s fallita: %s", order.side.value, order.symbol, exc)
        return ExecutionResult(
            symbol=order.symbol,
            side=order.side,
            amount_usd=order.amount_usd,
            status=ExecutionStatus.FAILED,
            detail=str(exc),
            etoro_position_id=order.position_id,
        )


def _existing_fill(request_id: str, deps: GraphDeps) -> dict | None:
    """Recovery idempotente: se l'ordine con questo referenceId è già Filled, riusalo."""
    try:
        info = deps.client.lookup_order(reference_id=request_id)
    except Exception:
        return None  # ordine mai inviato (404 o lookup non disponibile): si procede
    if not isinstance(info, dict) or (info.get("status") or {}).get("id") != ORDER_STATUS_FILLED:
        return None
    executions = info.get("positionExecutions") or []
    if not executions:
        return None
    opening = executions[0].get("openingData") or {}
    return {
        "position_id": executions[0].get("positionId"),
        "execution_price": opening.get("avgPrice"),
    }


def _open(order: ProposedOrder, run_id: str, request_id: str, deps: GraphDeps) -> ExecutionResult:
    existing = _existing_fill(request_id, deps)
    if existing is not None:
        fill, detail = existing, "riusato ordine già eseguito (idempotenza)"
    else:
        fill = deps.client.open_position(order.instrument_id, order.amount_usd, request_id)
        detail = "posizione aperta"
    position_id = fill.get("position_id")
    if position_id is not None:
        deps.repo.register_open_position(  # merge sul registry: idempotente
            etoro_position_id=int(position_id),
            run_id=run_id,
            symbol=order.symbol,
            instrument_id=order.instrument_id,
            amount_usd=order.amount_usd,
            entry_price=float(fill.get("execution_price") or 0.0),
            opened_at=datetime.now(timezone.utc),
            sector=order.sector,
        )
    return ExecutionResult(
        symbol=order.symbol,
        side=order.side,
        amount_usd=order.amount_usd,
        status=ExecutionStatus.FILLED,
        detail=detail,
        execution_price=fill.get("execution_price"),
        etoro_position_id=int(position_id) if position_id is not None else None,
    )


def _close(order: ProposedOrder, equity: float, deps: GraphDeps) -> ExecutionResult:
    deps.client.close_position(order.position_id, order.instrument_id)
    pnl = close_price = None
    try:
        recent = datetime.now(timezone.utc) - timedelta(days=3)
        for trade in deps.client.get_trade_history(min_date=recent):
            if trade.get("positionId") == order.position_id:
                pnl = trade.get("netProfit")
                close_price = trade.get("closeRate")
                break
    except Exception as exc:
        logger.warning("PnL non recuperabile per posizione %s: %s", order.position_id, exc)
    deps.repo.close_position(
        order.position_id,
        close_price=close_price,
        realized_pnl_usd=pnl,
        close_reason="bot_close",
    )
    if pnl is not None:
        deps.breaker.record_closed_trade(float(pnl), equity)
    return ExecutionResult(
        symbol=order.symbol,
        side=order.side,
        amount_usd=order.amount_usd,
        status=ExecutionStatus.FILLED,
        detail="posizione chiusa",
        execution_price=close_price,
        etoro_position_id=order.position_id,
    )
