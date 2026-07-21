"""Stato del grafo: TypedDict di soli valori serializzabili (dump pydantic).

`analyst_reports` ed `errors` hanno il reducer `operator.add` perché i quattro
analisti girano in parallelo (fan-out dallo screener): i loro update vengono
concatenati, non sovrascritti.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class BotState(TypedDict, total=False):
    run_id: str
    environment: str               # demo | real
    portfolio: dict                # PortfolioSnapshot.model_dump(mode="json")
    candidates: list[dict]         # Instrument dump
    analyst_reports: Annotated[list[dict], operator.add]  # AnalystReport dump
    verdicts: list[dict]           # DebateVerdict dump
    proposed_orders: list[dict]    # ProposedOrder dump
    risk_verdicts: list[dict]      # RiskVerdict dump
    executions: list[dict]         # ExecutionResult dump
    errors: Annotated[list[str], operator.add]
