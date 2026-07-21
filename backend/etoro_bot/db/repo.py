"""Repository: unico punto di accesso al journal per pipeline, servizi e API."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from etoro_bot.config import database_url
from etoro_bot.db.models import (
    AppSetting,
    BotPosition,
    Decision,
    EquitySnapshot,
    Execution,
    RiskScoreSnapshot,
    Run,
    SettingsAudit,
    UserCredential,
)
from etoro_bot.domain import DecisionStage, ExecutionResult, ExecutionStatus


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or database_url(), pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


class Repository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._sf = session_factory

    # --- runs -------------------------------------------------------------
    def create_run(self, run_id: str, environment: str) -> None:
        with self._sf.begin() as s:
            s.add(Run(run_id=run_id, environment=environment))

    def finish_run(self, run_id: str, summary: dict[str, Any]) -> None:
        with self._sf.begin() as s:
            run = s.get(Run, run_id)
            if run is not None:
                run.summary_json = summary

    def list_runs(self, limit: int = 50) -> list[Run]:
        with self._sf() as s:
            return list(
                s.scalars(select(Run).order_by(Run.started_at.desc()).limit(limit))
            )

    def delete_run(self, run_id: str) -> bool:
        """Cancella una run e tutto ciò che vi punta; False se non esiste.

        L'ordine è quello delle foreign key: decisioni ed esecuzioni prima,
        posizioni registrate poi, la run per ultima. Le posizioni del bot
        vengono rimosse insieme alla run che le ha aperte, altrimenti il
        registry conserverebbe righe orfane che il reconcile rileggerebbe.
        """
        with self._sf.begin() as s:
            run = s.get(Run, run_id)
            if run is None:
                return False
            s.query(Decision).filter(Decision.run_id == run_id).delete()
            s.query(Execution).filter(Execution.run_id == run_id).delete()
            s.query(BotPosition).filter(BotPosition.run_id == run_id).delete()
            s.delete(run)
            return True

    def get_run(self, run_id: str) -> Run | None:
        with self._sf() as s:
            return s.get(Run, run_id)

    # --- decisions / executions -------------------------------------------
    def add_decision(
        self, run_id: str, symbol: str, stage: DecisionStage | str, payload: dict[str, Any]
    ) -> None:
        stage_value = stage.value if isinstance(stage, DecisionStage) else stage
        with self._sf.begin() as s:
            s.add(Decision(run_id=run_id, symbol=symbol, stage=stage_value, payload=payload))

    def get_run_decisions(self, run_id: str) -> list[Decision]:
        with self._sf() as s:
            return list(
                s.scalars(
                    select(Decision)
                    .where(Decision.run_id == run_id)
                    .order_by(Decision.created_at)
                )
            )

    def add_execution(self, run_id: str, result: ExecutionResult) -> None:
        with self._sf.begin() as s:
            s.add(
                Execution(
                    run_id=run_id,
                    symbol=result.symbol,
                    side=result.side.value,
                    amount_usd=result.amount_usd,
                    status=result.status.value,
                    detail=result.detail,
                    execution_price=result.execution_price,
                    etoro_position_id=result.etoro_position_id,
                )
            )

    def list_executions(self, limit: int = 50) -> list[Execution]:
        with self._sf() as s:
            return list(
                s.scalars(select(Execution).order_by(Execution.created_at.desc()).limit(limit))
            )

    def get_execution(self, execution_id: uuid.UUID) -> Execution | None:
        with self._sf() as s:
            return s.get(Execution, execution_id)

    def cancel_pending_execution(self, execution_id: uuid.UUID) -> bool:
        with self._sf.begin() as s:
            row = s.get(Execution, execution_id)
            if row is None or row.status != "pending":
                return False
            row.status = "cancelled"
            row.detail = "annullato manualmente"
            return True

    def count_filled_today(self) -> int:
        today = datetime.now(timezone.utc).date()
        with self._sf() as s:
            return int(
                s.scalar(
                    select(func.count())
                    .select_from(Execution)
                    .where(
                        Execution.status == ExecutionStatus.FILLED.value,
                        func.date(Execution.created_at) == today,
                    )
                )
                or 0
            )

    # --- bot positions registry (§7) ---------------------------------------
    def register_open_position(
        self,
        etoro_position_id: int,
        run_id: str,
        symbol: str,
        instrument_id: int,
        amount_usd: float,
        entry_price: float,
        opened_at: datetime,
        sector: str = "unknown",
    ) -> None:
        with self._sf.begin() as s:
            s.merge(
                BotPosition(
                    etoro_position_id=etoro_position_id,
                    run_id=run_id,
                    symbol=symbol,
                    instrument_id=instrument_id,
                    amount_usd=amount_usd,
                    entry_price=entry_price,
                    opened_at=opened_at,
                    sector=sector,
                )
            )

    def close_position(
        self,
        etoro_position_id: int,
        close_price: float | None,
        realized_pnl_usd: float | None,
        close_reason: str,
        closed_at: datetime | None = None,
    ) -> None:
        with self._sf.begin() as s:
            pos = s.get(BotPosition, etoro_position_id)
            if pos is not None and pos.closed_at is None:
                pos.closed_at = closed_at or datetime.now(timezone.utc)
                pos.close_price = close_price
                pos.realized_pnl_usd = realized_pnl_usd
                pos.close_reason = close_reason

    def open_positions(self) -> list[BotPosition]:
        with self._sf() as s:
            return list(
                s.scalars(select(BotPosition).where(BotPosition.closed_at.is_(None)))
            )

    def get_open_position(self, position_id: int) -> BotPosition | None:
        with self._sf() as s:
            return s.scalar(
                select(BotPosition).where(
                    BotPosition.etoro_position_id == position_id,
                    BotPosition.closed_at.is_(None),
                )
            )

    def closed_positions(self) -> list[BotPosition]:
        with self._sf() as s:
            return list(
                s.scalars(
                    select(BotPosition)
                    .where(BotPosition.closed_at.is_not(None))
                    .order_by(BotPosition.closed_at)
                )
            )

    # --- equity & risk score ------------------------------------------------
    def record_equity_snapshot(
        self, day: date, equity_usd: float, cash_usd: float, exposure_usd: float
    ) -> None:
        with self._sf.begin() as s:
            s.merge(
                EquitySnapshot(
                    date=day, equity_usd=equity_usd, cash_usd=cash_usd, exposure_usd=exposure_usd
                )
            )

    def equity_series(self) -> list[EquitySnapshot]:
        with self._sf() as s:
            return list(s.scalars(select(EquitySnapshot).order_by(EquitySnapshot.date)))

    def record_risk_score(self, day: date, score: float, breakdown: dict[str, Any]) -> None:
        with self._sf.begin() as s:
            s.merge(RiskScoreSnapshot(date=day, score=score, breakdown=breakdown))

    def risk_score_history(self) -> list[RiskScoreSnapshot]:
        with self._sf() as s:
            return list(s.scalars(select(RiskScoreSnapshot).order_by(RiskScoreSnapshot.date)))

    # --- app settings (§10) -------------------------------------------------
    def get_setting(self, key: str) -> Any | None:
        with self._sf() as s:
            row = s.get(AppSetting, key)
            return None if row is None else row.value

    def set_setting(self, key: str, value: Any, source: str = "api") -> None:
        with self._sf.begin() as s:
            row = s.get(AppSetting, key)
            old = row.value if row is not None else None
            if row is None:
                s.add(AppSetting(key=key, value=value))
            else:
                row.value = value
                row.updated_at = datetime.now(timezone.utc)
            s.add(
                SettingsAudit(
                    key=key,
                    old_value={"value": old},
                    new_value={"value": value},
                    source=source,
                )
            )

    def settings_audit(self, limit: int = 100) -> list[SettingsAudit]:
        with self._sf() as s:
            return list(
                s.scalars(
                    select(SettingsAudit).order_by(SettingsAudit.changed_at.desc()).limit(limit)
                )
            )

    # --- credenziali per identità Authentik -------------------------------
    def get_user_credentials(self, user_id: str) -> UserCredential | None:
        with self._sf() as s:
            return s.get(UserCredential, user_id)

    def owner_user_id(self) -> str | None:
        """Utente che possiede le chiavi eToro: usato dalle run schedulate.

        L'app è mono-utente (una sola identità Authentik configura le chiavi);
        le run automatiche non hanno una richiesta HTTP da cui dedurre
        l'identità, quindi prendono l'unico account che ha entrambe le chiavi
        eToro salvate — il più recente se per qualche motivo ce n'è più d'uno.
        """
        with self._sf() as s:
            return s.scalars(
                select(UserCredential.user_id)
                .where(
                    UserCredential.etoro_api_key_encrypted.is_not(None),
                    UserCredential.etoro_user_key_encrypted.is_not(None),
                )
                .order_by(UserCredential.updated_at.desc())
                .limit(1)
            ).first()

    def set_user_credentials(
        self,
        user_id: str,
        *,
        email: str | None,
        display_name: str | None,
        etoro_api_key_encrypted: str | None,
        etoro_user_key_encrypted: str | None,
        openai_api_key_encrypted: str | None,
    ) -> None:
        with self._sf.begin() as s:
            row = s.get(UserCredential, user_id)
            if row is None:
                row = UserCredential(user_id=user_id)
                s.add(row)
            row.email = email
            row.display_name = display_name
            row.etoro_api_key_encrypted = etoro_api_key_encrypted
            row.etoro_user_key_encrypted = etoro_user_key_encrypted
            row.openai_api_key_encrypted = openai_api_key_encrypted
            row.updated_at = datetime.now(timezone.utc)
