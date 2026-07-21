"""Helper condivisi dai nodi: resolver LLM, blocchi system CAG, accesso KB sicuro.

La knowledge base è un'aggiunta, mai un requisito (§9): tutti gli accessi sono
con import LAZY e fallback a vuoto su qualsiasi errore (Qdrant giù, modulo
assente, librerie rag non installate).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from etoro_bot.graph.deps import GraphDeps

logger = logging.getLogger(__name__)


def resolve_llm(deps: GraphDeps) -> Callable[..., str]:
    """call_llm reale, oppure il fake iniettato nei test via deps.llm."""
    if deps.llm is not None:
        return deps.llm
    from etoro_bot.graph.llm import call_llm

    return call_llm


def llm_config(deps: GraphDeps) -> tuple[str, int]:
    cfg = deps.settings.get("llm") or {}
    return str(cfg.get("model", "gpt-5.6-terra")), int(cfg.get("max_tokens", 2048))


def system_blocks(deps: GraphDeps) -> list[dict]:
    """Blocco system statico cacheable (CAG); vuoto se il modulo knowledge manca."""
    try:
        from etoro_bot.knowledge.cag import static_system_block

        block = static_system_block()
        return [block] if block else []
    except Exception as exc:
        logger.debug("CAG non disponibile: %s", exc)
        return []


def _get_kb(deps: GraphDeps) -> Any | None:
    if deps.kb is not None:
        return deps.kb
    try:
        from etoro_bot.knowledge.kb import KnowledgeBase

        return KnowledgeBase()
    except Exception as exc:
        logger.debug("KnowledgeBase non disponibile: %s", exc)
        return None


def kb_search_news(
    deps: GraphDeps, query: str, tickers: list[str] | None = None, limit: int = 5
) -> list[dict]:
    kb = _get_kb(deps)
    if kb is None:
        return []
    try:
        return kb.search_news(query, tickers=tickers or [], limit=limit) or []
    except Exception as exc:
        logger.warning("ricerca news KB fallita (degradazione senza RAG): %s", exc)
        return []


def kb_search_trade_memory(deps: GraphDeps, query: str, limit: int = 3) -> list[dict]:
    kb = _get_kb(deps)
    if kb is None:
        return []
    try:
        return kb.search_trade_memory(query, limit=limit) or []
    except Exception as exc:
        logger.warning("ricerca trade_memory fallita (degradazione senza RAG): %s", exc)
        return []


def kb_add_trade_memory(deps: GraphDeps, text: str, payload: dict) -> None:
    kb = _get_kb(deps)
    if kb is None:
        return
    try:
        kb.add_trade_memory(text, payload)
    except Exception as exc:
        logger.warning("indicizzazione trade_memory fallita: %s", exc)
