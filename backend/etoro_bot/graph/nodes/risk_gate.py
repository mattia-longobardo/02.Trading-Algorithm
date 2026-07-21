"""Nodo risk gate (codice puro): unica autorità che approva o respinge ordini.

Delega a risk.rules.evaluate_orders (funzioni pure, testate) con il conteggio
degli ordini già filled oggi dal journal. Ogni verdetto è persistito con
stage="risk" e le motivazioni complete.
"""

from __future__ import annotations

from etoro_bot.domain import DecisionStage, PortfolioSnapshot, ProposedOrder
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.state import BotState
from etoro_bot.risk.rules import evaluate_orders


def risk_gate(state: BotState, deps: GraphDeps) -> dict:
    orders = [ProposedOrder.model_validate(o) for o in state.get("proposed_orders") or []]
    snapshot = PortfolioSnapshot.model_validate(state["portfolio"])
    verdicts = evaluate_orders(
        orders,
        snapshot,
        deps.rules,
        orders_filled_today=deps.repo.count_filled_today(),
    )
    for verdict in verdicts:
        deps.repo.add_decision(
            state["run_id"],
            verdict.order.symbol,
            DecisionStage.RISK,
            {
                "approved": verdict.approved,
                "reasons": verdict.reasons,
                "order": verdict.order.model_dump(mode="json"),
            },
        )
    return {"risk_verdicts": [v.model_dump(mode="json") for v in verdicts]}
