"""Dipendenze iniettate nei nodi del grafo (via closure/partial), mockabili nei test."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class GraphDeps:
    client: Any                # etoro.client.EtoroClient (o fake nei test)
    repo: Any                  # db.repo.Repository
    rules: Any                 # config.RiskRules
    settings: dict[str, Any]   # settings effettive (app_settings DB > yaml)
    breaker: Any               # safety.circuit_breaker.CircuitBreaker
    kb: Any | None = None      # knowledge.kb.KnowledgeBase; None → import lazy, opzionale
    llm: Callable[..., str] | None = None  # override di call_llm nei test (stessa firma)
