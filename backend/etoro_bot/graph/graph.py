"""Costruzione del grafo LangGraph.

reconcile → screener → fan-out 4 analisti in parallelo → join su debate →
portfolio_manager → risk_gate → executor → journal → END.

Le dipendenze (GraphDeps) sono iniettate nei nodi via functools.partial: i nodi
restano funzioni pure (state, deps) → update, testabili senza grafo.
"""

from __future__ import annotations

import logging
from functools import partial

from langgraph.graph import END, START, StateGraph

from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.nodes.analysts import ANALYSTS, run_analyst
from etoro_bot.graph.nodes.debate import debate
from etoro_bot.graph.nodes.executor import executor
from etoro_bot.graph.nodes.journal import journal
from etoro_bot.graph.nodes.portfolio_manager import portfolio_manager
from etoro_bot.graph.nodes.reconcile import reconcile
from etoro_bot.graph.nodes.risk_gate import risk_gate
from etoro_bot.graph.nodes.screener import screener
from etoro_bot.graph.state import BotState

logger = logging.getLogger(__name__)


def build_graph(deps: GraphDeps, checkpointer=None):
    graph = StateGraph(BotState)
    graph.add_node("reconcile", partial(reconcile, deps=deps))
    graph.add_node("screener", partial(screener, deps=deps))
    for analyst in ANALYSTS:
        graph.add_node(f"analyst_{analyst}", partial(run_analyst, deps=deps, analyst=analyst))
    graph.add_node("debate", partial(debate, deps=deps))
    graph.add_node("portfolio_manager", partial(portfolio_manager, deps=deps))
    graph.add_node("risk_gate", partial(risk_gate, deps=deps))
    graph.add_node("executor", partial(executor, deps=deps))
    graph.add_node("journal", partial(journal, deps=deps))

    graph.add_edge(START, "reconcile")
    graph.add_edge("reconcile", "screener")
    for analyst in ANALYSTS:
        graph.add_edge("screener", f"analyst_{analyst}")
    graph.add_edge([f"analyst_{a}" for a in ANALYSTS], "debate")  # join (barriera)
    graph.add_edge("debate", "portfolio_manager")
    graph.add_edge("portfolio_manager", "risk_gate")
    graph.add_edge("risk_gate", "executor")
    graph.add_edge("executor", "journal")
    graph.add_edge("journal", END)
    return graph.compile(checkpointer=checkpointer)


def make_checkpointer():
    """PostgresSaver (langgraph-checkpoint-postgres) se DATABASE_URL è
    raggiungibile, altrimenti None: il grafo compila e gira comunque."""
    try:
        import psycopg
        from langgraph.checkpoint.postgres import PostgresSaver

        from etoro_bot.config import database_url

        url = database_url().replace("postgresql+psycopg://", "postgresql://")
        conn = psycopg.connect(url, autocommit=True, connect_timeout=5)
        saver = PostgresSaver(conn)
        saver.setup()
        return saver
    except Exception as exc:
        logger.warning("checkpointer Postgres non disponibile (%s): grafo senza checkpoint", exc)
        return None
