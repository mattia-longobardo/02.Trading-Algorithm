"""Modelli di dominio condivisi da pipeline, risk manager, executor e API.

Tutti i modelli sono serializzabili (model_dump) perché lo stato del grafo
LangGraph è un TypedDict di dump pydantic salvato nel checkpointer Postgres.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class AssetType(str, enum.Enum):
    STOCK = "stock"
    ETF = "etf"


class Environment(str, enum.Enum):
    DEMO = "demo"
    REAL = "real"


class Side(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class ExecutionStatus(str, enum.Enum):
    FILLED = "filled"
    FAILED = "failed"
    SKIPPED = "skipped"
    REJECTED = "rejected"


class DecisionStage(str, enum.Enum):
    ANALYST = "analyst"
    DEBATE = "debate"
    PORTFOLIO = "portfolio"
    RISK = "risk"
    RECONCILE_ANOMALY = "reconcile_anomaly"


class Instrument(BaseModel):
    instrument_id: int
    symbol: str
    display_name: str = ""
    asset_type: AssetType
    sector: str = "unknown"
    current_rate: float | None = None


class Position(BaseModel):
    """Posizione bot aperta (già filtrata sul registry, mai il conto grezzo)."""

    etoro_position_id: int
    symbol: str
    instrument_id: int
    amount_usd: float
    entry_price: float
    opened_at: datetime
    current_price: float | None = None
    sector: str = "unknown"

    @property
    def unrealized_pnl_usd(self) -> float | None:
        if self.current_price is None or self.entry_price <= 0:
            return None
        return self.amount_usd * (self.current_price - self.entry_price) / self.entry_price


class PortfolioSnapshot(BaseModel):
    """Vista del solo capitale bot: cash allocato + posizioni del registry."""

    as_of: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cash_usd: float
    positions: list[Position] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)

    @property
    def exposure_usd(self) -> float:
        return sum(p.amount_usd for p in self.positions)

    @property
    def equity_usd(self) -> float:
        return self.cash_usd + self.exposure_usd


class AnalystReport(BaseModel):
    analyst: str
    symbol: str
    score: float = Field(ge=-1.0, le=1.0)
    summary: str


class DebateDecision(str, enum.Enum):
    OPEN_LONG = "open_long"
    CLOSE = "close"
    AVOID = "avoid"


class DebateVerdict(BaseModel):
    symbol: str
    decision: DebateDecision
    conviction: float = Field(ge=0.0, le=1.0)
    rationale: str
    transcript: list[dict] = Field(default_factory=list)


class ProposedOrder(BaseModel):
    """Ordine proposto dal portfolio manager. NON è autorizzato: passa dal risk gate."""

    symbol: str
    instrument_id: int
    side: Side
    amount_usd: float = Field(ge=0)
    asset_type: AssetType
    sector: str = "unknown"
    rationale: str = ""
    conviction: float = Field(default=0.0, ge=0.0, le=1.0)
    position_id: int | None = None  # richiesto per le chiusure


class RiskVerdict(BaseModel):
    order: ProposedOrder
    approved: bool
    reasons: list[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    symbol: str
    side: Side
    amount_usd: float
    status: ExecutionStatus
    detail: str = ""
    execution_price: float | None = None
    etoro_position_id: int | None = None


def order_request_id(run_id: str, symbol: str, side: Side) -> str:
    """UUID5 deterministico: una run ritentata dopo un crash non duplica ordini."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"etoro-bot:{run_id}:{symbol}:{side.value}"))
