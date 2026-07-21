"""Modelli SQLAlchemy 2 del journal (PostgreSQL 18).

Le PK surrogate delle righe append-only usano uuidv7() nativo di PG18:
ordinabili temporalmente, ideali per decisions/executions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    environment: Mapped[str] = mapped_column(String(16))     # demo | real
    summary_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_run_id", "run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    symbol: Mapped[str] = mapped_column(String(32))
    stage: Mapped[str] = mapped_column(String(32))  # analyst|debate|portfolio|risk|reconcile_anomaly
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_run_id", "run_id"),
        Index("ix_executions_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))             # buy | sell
    amount_usd: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))          # filled|failed|skipped|rejected
    detail: Mapped[str] = mapped_column(Text, default="")
    execution_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    etoro_position_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class BotPosition(Base):
    """Registry delle SOLE posizioni aperte dal bot (§7): l'unica fonte per
    dashboard, backtest e risk score. Le posizioni manuali non entrano mai."""

    __tablename__ = "bot_positions"
    __table_args__ = (Index("ix_bot_positions_closed_at", "closed_at"),)

    etoro_position_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"))
    symbol: Mapped[str] = mapped_column(String(32))
    instrument_id: Mapped[int] = mapped_column(Integer)
    amount_usd: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sector: Mapped[str] = mapped_column(String(64), default="unknown")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    equity_usd: Mapped[float] = mapped_column(Float)
    cash_usd: Mapped[float] = mapped_column(Float)
    exposure_usd: Mapped[float] = mapped_column(Float)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )


class SettingsAudit(Base):
    __tablename__ = "settings_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    key: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="api")


class RiskScoreSnapshot(Base):
    """Storico del risk score per la pagina /risk (non in §8: aggiunta necessaria
    per GET /risk/score/history senza ricalcoli retroattivi)."""

    __tablename__ = "risk_scores"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    score: Mapped[float] = mapped_column(Float)
    breakdown: Mapped[dict] = mapped_column(JSONB)


class UserCredential(Base):
    """Credenziali broker/LLM cifrate e isolate per identità Authentik."""

    __tablename__ = "user_credentials"

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    etoro_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    etoro_user_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    openai_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), onupdate=text("now()")
    )
