"""Pipeline news completa: fetch → indicizza → pota → memorie → universo.

Unico punto d'ingresso per il job schedulato e per il fetch manuale dall'API,
così i quattro effetti restano sempre allineati:

  1. indicizzazione delle news in `news_kb` (con timestamp per il decadimento);
  2. purge delle news più vecchie di `knowledge.news_max_age_days`;
  3. aggiornamento delle memorie per ticker (`ticker_memory`);
  4. refresh dell'universo dinamico (solo se un client eToro è disponibile).

Ogni passo degrada indipendentemente: un fallimento logga e non blocca gli
altri. Ritorna un riepilogo con i contatori di ogni passo.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_NEWS_MAX_AGE_DAYS = 45.0


def run_news_pipeline(
    kb: Any | None = None,
    settings: dict[str, Any] | None = None,
    *,
    items: list[dict] | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    from etoro_bot.config import load_settings
    from etoro_bot.knowledge.fetch_news import fetch_all
    from etoro_bot.knowledge.kb import KnowledgeBase

    settings = settings if settings is not None else load_settings()
    kb = kb or KnowledgeBase()
    if items is None:
        items = fetch_all(settings)

    summary: dict[str, Any] = {"fetched": len(items), "indexed": 0, "purged": 0,
                               "memories_updated": 0, "universe": None}

    if items:
        kb.ensure_collections()
        summary["indexed"] = kb.add_news(items)

    knowledge_cfg = settings.get("knowledge") or {}
    try:
        summary["purged"] = kb.purge_old_news(
            float(knowledge_cfg.get("news_max_age_days", DEFAULT_NEWS_MAX_AGE_DAYS))
        )
    except Exception as exc:
        logger.warning("purge news fallita, continuo: %s", exc)

    try:
        from etoro_bot.knowledge.ticker_memory import update_memories

        summary["memories_updated"] = len(update_memories(items, settings))
    except Exception as exc:
        logger.warning("aggiornamento memorie ticker fallito, continuo: %s", exc)

    if client is not None:
        try:
            from etoro_bot.services.universe import refresh_universe

            state = refresh_universe(client, settings, items)
            summary["universe"] = [t["symbol"] for t in state.get("tickers") or []]
        except Exception as exc:
            logger.warning("refresh universo dinamico fallito, continuo: %s", exc)

    logger.info(
        "news pipeline: %(fetched)d scaricate, %(indexed)d indicizzate, "
        "%(purged)d eliminate per età, %(memories_updated)d memorie aggiornate",
        summary,
    )
    return summary
