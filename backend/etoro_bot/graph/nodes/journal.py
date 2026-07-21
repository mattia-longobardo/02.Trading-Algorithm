"""Nodo journal (codice): persiste tutto ciò che non è già a DB e chiude la run.

Stage "risk" e "reconcile_anomaly" sono già scritti dai rispettivi nodi; qui si
persistono analyst/debate/portfolio, l'equity snapshot del giorno, i trade
chiusi in questa run nella trade_memory (RAG) e il summary finale della run.
"""

from __future__ import annotations

from datetime import datetime, timezone

from etoro_bot.domain import DecisionStage, ExecutionStatus, PortfolioSnapshot, Side
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.nodes.common import kb_add_trade_memory
from etoro_bot.graph.state import BotState


def journal(state: BotState, deps: GraphDeps) -> dict:
    run_id = state["run_id"]

    for report in state.get("analyst_reports") or []:
        deps.repo.add_decision(run_id, report.get("symbol", "?"), DecisionStage.ANALYST, report)
    for verdict in state.get("verdicts") or []:
        deps.repo.add_decision(run_id, verdict.get("symbol", "?"), DecisionStage.DEBATE, verdict)
    for order in state.get("proposed_orders") or []:
        deps.repo.add_decision(run_id, order.get("symbol", "?"), DecisionStage.PORTFOLIO, order)

    if state.get("portfolio"):
        snapshot = PortfolioSnapshot.model_validate(state["portfolio"])
        deps.repo.record_equity_snapshot(
            datetime.now(timezone.utc).date(),
            equity_usd=snapshot.equity_usd,
            cash_usd=snapshot.cash_usd,
            exposure_usd=snapshot.exposure_usd,
        )

    _index_closed_trades(state, deps)

    executions = state.get("executions") or []
    risk_verdicts = state.get("risk_verdicts") or []
    summary = {
        "candidates": len(state.get("candidates") or []),
        "proposed": len(state.get("proposed_orders") or []),
        "approved": sum(1 for v in risk_verdicts if v.get("approved")),
        "rejected": sum(1 for v in risk_verdicts if not v.get("approved")),
        "executed": sum(
            1 for e in executions if e.get("status") == ExecutionStatus.FILLED.value
        ),
        "skipped": sum(
            1 for e in executions if e.get("status") == ExecutionStatus.SKIPPED.value
        ),
        "failed": sum(1 for e in executions if e.get("status") == ExecutionStatus.FAILED.value),
        "anomalies": len((state.get("portfolio") or {}).get("anomalies") or []),
        "errors": list(state.get("errors") or []),
    }
    deps.repo.finish_run(run_id, summary)
    return {}


def _index_closed_trades(state: BotState, deps: GraphDeps) -> None:
    """Indicizza in trade_memory (tesi + esito + pnl) i trade CHIUSI in questa run."""
    closed_executions = [
        e
        for e in state.get("executions") or []
        if e.get("side") == Side.SELL.value
        and e.get("status") == ExecutionStatus.FILLED.value
    ]
    if not closed_executions:
        return
    rationale_by_symbol = {
        v.get("symbol"): v.get("rationale", "") for v in state.get("verdicts") or []
    }
    closed_by_id = {p.etoro_position_id: p for p in deps.repo.closed_positions()}
    for execution in closed_executions:
        position = closed_by_id.get(execution.get("etoro_position_id"))
        pnl = position.realized_pnl_usd if position is not None else None
        symbol = execution.get("symbol", "?")
        text = (
            f"Trade chiuso su {symbol}. Tesi: {rationale_by_symbol.get(symbol, 'n/d')}. "
            f"Esito: PnL realizzato {pnl if pnl is not None else 'n/d'} USD."
        )
        kb_add_trade_memory(
            deps,
            text,
            {
                "symbol": symbol,
                "run_id": state["run_id"],
                "etoro_position_id": execution.get("etoro_position_id"),
                "realized_pnl_usd": pnl,
                "closed_at": (
                    position.closed_at.isoformat()
                    if position is not None and position.closed_at is not None
                    else None
                ),
            },
        )
