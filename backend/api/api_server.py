"""FastAPI application — auth, dashboard data, and operator endpoints.

The historical manual trigger endpoints (`/api/universe/generate`,
`/api/orders/generate`, `/api/report/...`, `/api/scheduler/reset`,
`/api/logs`, `/api/logs/stream`) are kept under exactly the same paths
they used in the v1 BaseHTTPRequestHandler version. They are now
authenticated and `/api/scheduler/reset` plus the manual generation
endpoints are admin-only.

Everything else (auth, users, trades CRUD, dashboard metrics, reports
+ folders, prompts + versions, settings, audit log) is new and follows
the contract documented in the project spec.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    HTTPException,
    Path as PathParam,
    Query,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from clients.gpt_client import get_default_prompts
from core import app_db, auth as auth_lib, fx, prompt_store
from core.utils import (
    ALL_PROVIDERS,
    PROVIDER_ETORO,
    SETTINGS_OVERRIDABLE_KEYS,
    SETTINGS_RESTART_REQUIRED_KEYS,
    AppConfig,
    apply_settings_overlay,
    isoformat_utc,
    parse_datetime,
    utc_now,
)
from services.equity_snapshots import equity_curve_for_api, record_snapshots_all
from services.live_snapshot import LiveSnapshotCache
from services.metrics_service import MetricsService, parse_named_window, parse_window
from services.universe_admin import (
    UniverseValidationError,
    add_symbol as universe_add_symbol,
    get_universe_with_metadata,
    remove_symbol as universe_remove_symbol,
)
from services.report_index import (
    create_folder,
    delete_folder,
    get_report,
    list_folders,
    list_reports,
    report_path_for,
    search_reports_full_text,
    sync_reports,
    update_folder,
    update_report,
)
from services.scheduler import JobExecutionLockedError, TradingScheduler
from services.trade_admin import (
    EDITABLE_TRADE_FIELDS,
    TradeValidationError,
    manual_close_or_cancel,
    update_trade,
)


# ----- Pydantic models -----------------------------------------------------


class LoginPayload(BaseModel):
    username: str
    password: str


class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6)


class UpdateProfilePayload(BaseModel):
    current_password: str
    username: str | None = None
    display_name: str | None = None


class CreateUserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6)
    display_name: str = Field(min_length=1, max_length=128)
    role: str

    @field_validator("role")
    @classmethod
    def _role_in_set(cls, v: str) -> str:
        if v not in ("admin", "user"):
            raise ValueError("role must be admin or user")
        return v


class UpdateUserPayload(BaseModel):
    display_name: str | None = None
    role: str | None = None
    disabled: bool | None = None

    @field_validator("role")
    @classmethod
    def _role_in_set(cls, v: str | None) -> str | None:
        if v is not None and v not in ("admin", "user"):
            raise ValueError("role must be admin or user")
        return v


class ResetPasswordPayload(BaseModel):
    new_password: str = Field(min_length=6)


class TradePatchPayload(BaseModel):
    target_entry_price: float | None = None
    quantity: float | None = None
    take_profit: float | None = None
    trailing_take_profit_distance: float | None = None
    trailing_take_profit_activation_pct: float | None = None
    stop_loss: float | None = None
    trailing_stop_distance: float | None = None
    high_water_mark: float | None = None


class RiskProjectPayload(BaseModel):
    symbol: str | None = None
    category: str = "STOCK"
    value: float | None = None
    close_symbols: list[str] | None = None

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        up = str(v or "STOCK").upper()
        if up not in {"STOCK", "CRYPTO"}:
            raise ValueError("category must be STOCK or CRYPTO")
        return up

    @field_validator("value")
    @classmethod
    def _positive_value(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("value must be > 0")
        return v


class PromptSavePayload(BaseModel):
    content: str = Field(min_length=1)
    comment: str | None = None


class PromptRollbackPayload(BaseModel):
    version_id: int


class FolderCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    parent_id: int | None = None


class FolderUpdatePayload(BaseModel):
    name: str | None = None
    parent_id: int | None = None


class ReportPatchPayload(BaseModel):
    folder_id: int | None = None
    tags: list[str] | None = None
    clear_folder: bool = False


class UniverseSymbolPayload(BaseModel):
    category: str
    symbol: str
    provider: str | None = None


# ----- SSE helpers ---------------------------------------------------------

_LIVE_STREAM_INTERVAL_SECONDS = 5


def _format_event(event_name: str, data: str) -> bytes:
    """Encode a single Server-Sent-Event frame as UTF-8 bytes.

    Multi-line data is split so each line is prefixed with ``data: `` per
    the SSE specification. An empty trailing line terminates the event.
    """
    payload_lines = data.splitlines() or [""]
    chunks = [f"event: {event_name}"]
    for line in payload_lines:
        chunks.append(f"data: {line}")
    chunks.append("")
    chunks.append("")
    return "\n".join(chunks).encode("utf-8")


# ----- error helper --------------------------------------------------------


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"error": {"code": code, "message": message}},
    )


# ----- candle mapping helper -----------------------------------------------


def _candle_to_dict(bar: dict[str, Any]) -> dict[str, Any]:
    """Map an eToro bar dict to the compact OHLC wire shape.

    Input keys (from ``EToroClient.get_candles_by_instrument``):
        symbol, timestamp, open, high, low, close, volume

    Output shape::

        {"t": <iso-utc str>, "o": float, "h": float, "l": float,
         "c": float, "v": float | None}
    """
    ts_raw: str = str(bar.get("timestamp") or "")
    # Normalise to ISO-8601 UTC; keep raw string as fallback so callers
    # always get a non-null "t" field even if the timestamp is unusual.
    parsed = parse_datetime(ts_raw) if ts_raw else None
    t = isoformat_utc(parsed) if parsed is not None else ts_raw
    vol_raw = bar.get("volume")
    v: float | None = float(vol_raw) if vol_raw is not None else None
    return {
        "t": t,
        "o": float(bar["open"]),
        "h": float(bar["high"]),
        "l": float(bar["low"]),
        "c": float(bar["close"]),
        "v": v,
    }


# ----- factory -------------------------------------------------------------


def create_app(scheduler: TradingScheduler, logger: logging.Logger) -> FastAPI:
    config: AppConfig = scheduler.config
    api_logger = logger.getChild("api")

    brokers: dict[str, Any] = dict(getattr(scheduler.trade_manager, "brokers", {}) or {})
    metrics = MetricsService(config, api_logger, broker_clients=brokers)
    live_cache = LiveSnapshotCache(metrics, brokers, config, api_logger)

    # Snapshot the restart-only settings as they were when this process booted
    # (main() applies the overlay before constructing the API). A restart is
    # "required" only when the persisted overlay later DIVERGES from this
    # snapshot — i.e. an operator changed a restart-only setting that won't take
    # effect until the next process start. After a real restart this snapshot
    # reflects the new values, so the banner clears on its own.
    _boot_restart_settings = {
        key: app_db.read_all_settings(config.db_app).get(key)
        for key in SETTINGS_RESTART_REQUIRED_KEYS
    }

    def _restart_pending(current_overlay: dict[str, Any]) -> bool:
        return any(
            current_overlay.get(key) != _boot_restart_settings.get(key)
            for key in SETTINGS_RESTART_REQUIRED_KEYS
        )

    def _resolve_brokers() -> dict[str, Any]:
        # The scheduler holds the live broker registry; resolve it lazily so
        # add/remove of providers via settings (future) can be picked up.
        return dict(getattr(scheduler.trade_manager, "brokers", {}) or {})

    def _active_provider_descriptors() -> list[dict[str, Any]]:
        live = _resolve_brokers()
        out: list[dict[str, Any]] = []
        for provider in ALL_PROVIDERS:
            broker = live.get(provider)
            if broker is None:
                continue
            account_currency = config.provider_account_currency(provider)
            descriptor: dict[str, Any] = {
                "provider": provider,
                "active": True,
                "account_currency": account_currency,
                "display_currency": config.currency,
                "categories": ["STOCK", "CRYPTO"],
            }
            out.append(descriptor)
        return out

    app = FastAPI(title="Trading Backend", version="2.0.0")

    # CORS — when Next.js Route Handlers are the only client (server-side
    # proxy), this is effectively unused. We still allow the listed origins
    # because the spec keeps option 2 (direct browser calls) supported by
    # configuration only.
    if config.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_allowed_origins),
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # ----- helpers --------------------------------------------------------

    def _get_session_cookie_name() -> str:
        return auth_lib.SESSION_COOKIE_NAME

    def _set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            key=auth_lib.SESSION_COOKIE_NAME,
            value=token,
            httponly=True,
            secure=bool(config.session_cookie_secure),
            samesite=str(config.session_cookie_samesite or "lax"),
            path="/",
            max_age=auth_lib.SESSION_TTL_DAYS * 24 * 3600,
        )

    def _clear_session_cookie(response: Response) -> None:
        response.delete_cookie(key=auth_lib.SESSION_COOKIE_NAME, path="/")

    def _audit(
        actor: auth_lib.AuthenticatedUser | None,
        *,
        entity: str,
        entity_id: Any,
        action: str,
        before: Any = None,
        after: Any = None,
    ) -> None:
        try:
            app_db.write_audit_entry(
                config.db_app,
                actor_id=actor.id if actor else None,
                actor_name=actor.username if actor else "system",
                entity=entity,
                entity_id=entity_id,
                action=action,
                before=before,
                after=after,
            )
        except Exception:
            api_logger.exception("Failed to write audit entry %s/%s/%s", entity, entity_id, action)

    # ----- auth dependency -----------------------------------------------

    def get_current_user(
        trading_session: str | None = Cookie(default=None, alias=auth_lib.SESSION_COOKIE_NAME),
    ) -> auth_lib.AuthenticatedUser:
        user = auth_lib.resolve_session(config.db_app, trading_session)
        if user is None:
            raise _error(HTTPStatus.UNAUTHORIZED, "unauthorized", "Authentication required")
        return user

    def require_admin(user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> auth_lib.AuthenticatedUser:
        if not user.is_admin:
            raise _error(HTTPStatus.FORBIDDEN, "forbidden", "Admin role required")
        return user

    # ----- public / health ------------------------------------------------

    @app.get("/")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "trading-backend"}

    @app.get("/api/providers")
    def list_providers(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Active broker providers detected at startup.

        Frontend uses this to decide which surfaces (universe tab, prompts
        tab, settings card) to render. Inactive providers are simply omitted.
        """

        return {
            "active": [entry["provider"] for entry in _active_provider_descriptors()],
            "providers": _active_provider_descriptors(),
        }

    # ----- auth ----------------------------------------------------------

    @app.post("/api/auth/login")
    def login(payload: LoginPayload, response: Response) -> dict[str, Any]:
        user_row = auth_lib.authenticate(config.db_app, payload.username.strip(), payload.password)
        if not user_row:
            raise _error(HTTPStatus.UNAUTHORIZED, "invalid_credentials", "Invalid username or password")
        token = auth_lib.create_session(config.db_app, int(user_row["id"]))
        _set_session_cookie(response, token)
        actor = auth_lib.AuthenticatedUser(
            id=int(user_row["id"]),
            username=str(user_row["username"]),
            display_name=str(user_row["display_name"]),
            role=str(user_row["role"]),
            disabled=bool(user_row.get("disabled") or 0),
            session_id=token,
        )
        _audit(actor, entity="auth", entity_id=user_row["id"], action="login")
        return {"user": actor.public_dict()}

    @app.post("/api/auth/logout")
    def logout(
        response: Response,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, bool]:
        auth_lib.revoke_session(config.db_app, user.session_id)
        _clear_session_cookie(response)
        _audit(user, entity="auth", entity_id=user.id, action="logout")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        return {"user": user.public_dict()}

    @app.post("/api/auth/change-password")
    def change_own_password(
        payload: ChangePasswordPayload,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, bool]:
        try:
            auth_lib.change_own_password(
                config.db_app, user.id, payload.current_password, payload.new_password
            )
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_password", str(exc)) from exc
        _audit(user, entity="user", entity_id=user.id, action="change_own_password")
        return {"ok": True}

    @app.post("/api/auth/profile")
    def update_own_profile(
        payload: UpdateProfilePayload,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            updated = auth_lib.update_own_profile(
                config.db_app,
                user.id,
                current_password=payload.current_password,
                new_username=payload.username,
                new_display_name=payload.display_name,
            )
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_profile_update", str(exc)) from exc
        _audit(
            user,
            entity="user",
            entity_id=user.id,
            action="update_profile",
            after={"username": updated["username"], "display_name": updated["display_name"]},
        )
        return {
            "user": {
                "id": int(updated["id"]),
                "username": str(updated["username"]),
                "display_name": str(updated["display_name"]),
                "role": str(updated["role"]),
            }
        }

    # ----- users (admin only except /me already exposed above) -----------

    @app.get("/api/users")
    def get_users(_admin: auth_lib.AuthenticatedUser = Depends(require_admin)) -> dict[str, Any]:
        users = auth_lib.list_users(config.db_app)
        return {"users": users}

    @app.post("/api/users")
    def create_new_user(
        payload: CreateUserPayload,
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            user = auth_lib.create_user(
                config.db_app,
                username=payload.username.strip(),
                password=payload.password,
                display_name=payload.display_name.strip(),
                role=payload.role,
            )
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_user", str(exc)) from exc
        _audit(
            admin,
            entity="user",
            entity_id=user["id"],
            action="create",
            after={k: v for k, v in user.items() if k != "password_hash"},
        )
        return {"user": {k: v for k, v in user.items() if k != "password_hash"}}

    @app.patch("/api/users/{user_id}")
    def patch_user(
        user_id: int,
        payload: UpdateUserPayload,
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        before = auth_lib.get_user_by_id(config.db_app, user_id)
        if not before:
            raise _error(HTTPStatus.NOT_FOUND, "user_not_found", "User not found")
        try:
            user = auth_lib.update_user(
                config.db_app,
                user_id,
                display_name=payload.display_name,
                role=payload.role,
                disabled=payload.disabled,
            )
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_user_update", str(exc)) from exc
        _audit(
            admin,
            entity="user",
            entity_id=user_id,
            action="update",
            before={k: v for k, v in before.items() if k != "password_hash"},
            after={k: v for k, v in user.items() if k != "password_hash"},
        )
        return {"user": {k: v for k, v in user.items() if k != "password_hash"}}

    @app.post("/api/users/{user_id}/reset-password")
    def reset_password(
        user_id: int,
        payload: ResetPasswordPayload,
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, bool]:
        before = auth_lib.get_user_by_id(config.db_app, user_id)
        if not before:
            raise _error(HTTPStatus.NOT_FOUND, "user_not_found", "User not found")
        try:
            auth_lib.reset_user_password(config.db_app, user_id, payload.new_password)
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_password", str(exc)) from exc
        _audit(admin, entity="user", entity_id=user_id, action="reset_password")
        return {"ok": True}

    @app.delete("/api/users/{user_id}")
    def remove_user(
        user_id: int,
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, bool]:
        if user_id == admin.id:
            raise _error(HTTPStatus.BAD_REQUEST, "cannot_delete_self", "Cannot delete yourself")
        before = auth_lib.get_user_by_id(config.db_app, user_id)
        if not before:
            raise _error(HTTPStatus.NOT_FOUND, "user_not_found", "User not found")
        auth_lib.delete_user(config.db_app, user_id)
        _audit(
            admin,
            entity="user",
            entity_id=user_id,
            action="delete",
            before={k: v for k, v in before.items() if k != "password_hash"},
        )
        return {"ok": True}

    # ----- trades --------------------------------------------------------

    @app.get("/api/trades")
    def get_trades(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        status_filter: str | None = Query(default=None, alias="status"),
        category: str | None = Query(default=None),
        symbol: str | None = Query(default=None),
        from_iso: str | None = Query(default=None, alias="from"),
        to_iso: str | None = Query(default=None, alias="to"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=500),
        sort: str = Query(default="-created_at"),
    ) -> dict[str, Any]:
        from_dt, to_dt = parse_window(from_iso, to_iso)
        return metrics.list_trades(
            status=status_filter,
            category=category,
            symbol=symbol,
            from_dt=from_dt,
            to_dt=to_dt,
            page=page,
            page_size=page_size,
            sort=sort,
        )

    @app.get("/api/trades/{trade_id}")
    def get_trade(
        trade_id: int,
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        trade = metrics.get_trade(trade_id)
        if not trade:
            raise _error(HTTPStatus.NOT_FOUND, "trade_not_found", "Trade not found")
        return {"trade": trade}

    @app.patch("/api/trades/{trade_id}")
    def patch_trade(
        trade_id: int,
        payload: TradePatchPayload,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        provided = payload.model_dump(exclude_unset=True)
        try:
            before, after = update_trade(config, trade_id, provided)
        except TradeValidationError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_trade_update", str(exc)) from exc
        # Limit audit payload to the whitelisted editable fields.
        before_subset = {k: before.get(k) for k in EDITABLE_TRADE_FIELDS}
        after_subset = {k: after.get(k) for k in EDITABLE_TRADE_FIELDS}
        _audit(
            user,
            entity="trade",
            entity_id=trade_id,
            action="update",
            before=before_subset,
            after=after_subset,
        )
        return {"trade": metrics.get_trade(trade_id) or after}

    @app.post("/api/trades/{trade_id}/close")
    def close_trade(
        trade_id: int,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            before, after = manual_close_or_cancel(scheduler.trade_manager, trade_id)
        except TradeValidationError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_trade_close", str(exc)) from exc
        action = "cancel" if str(before.get("status", "")).upper() == "PENDING" else "close"
        _audit(
            user,
            entity="trade",
            entity_id=trade_id,
            action=action,
            before={"status": before.get("status"), "close_reason": before.get("close_reason")},
            after={
                "status": after.get("status"),
                "close_reason": after.get("close_reason"),
                "pending_close_reason": after.get("pending_close_reason"),
            },
        )
        return {"trade": metrics.get_trade(trade_id) or after}

    # ----- metrics & charts ---------------------------------------------

    @app.get("/api/metrics")
    def get_metrics(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        window: str | None = Query(default=None),
        from_iso: str | None = Query(default=None, alias="from"),
        to_iso: str | None = Query(default=None, alias="to"),
    ) -> dict[str, Any]:
        if window:
            from_dt, to_dt = parse_named_window(window)
        else:
            from_dt, to_dt = parse_window(from_iso, to_iso)
        return metrics.compute_metrics(from_dt, to_dt)

    @app.get("/api/equity-curve")
    def get_equity_curve(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        window: str | None = Query(default=None),
        from_iso: str | None = Query(default=None, alias="from"),
        to_iso: str | None = Query(default=None, alias="to"),
        granularity: str = Query(default="daily"),
    ) -> dict[str, Any]:
        if window:
            from_dt, to_dt = parse_named_window(window)
        else:
            from_dt, to_dt = parse_window(from_iso, to_iso)
        return metrics.equity_curve(from_dt, to_dt, granularity=granularity)

    @app.get("/api/pnl-by-symbol")
    def get_pnl_by_symbol(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        window: str | None = Query(default=None),
        from_iso: str | None = Query(default=None, alias="from"),
        to_iso: str | None = Query(default=None, alias="to"),
    ) -> dict[str, Any]:
        if window:
            from_dt, to_dt = parse_named_window(window)
        else:
            from_dt, to_dt = parse_window(from_iso, to_iso)
        return metrics.pnl_by_symbol(from_dt, to_dt)

    @app.get("/api/allocation")
    def get_allocation(_user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        return metrics.allocation()

    @app.get("/api/risk")
    def get_risk(_user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        return scheduler.trade_manager.portfolio_risk_snapshot()

    @app.post("/api/risk/project")
    def post_risk_project(
        payload: RiskProjectPayload,
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        if not payload.symbol and not payload.close_symbols:
            raise HTTPException(status_code=400, detail="symbol or close_symbols required")
        return scheduler.trade_manager.portfolio_risk_projection(
            symbol=payload.symbol,
            category=payload.category,
            value=payload.value,
            close_symbols=payload.close_symbols,
        )

    @app.get("/api/fx/rate")
    def get_fx_rate(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        return fx.get_rate_with_status(config.account_currency, config.currency)

    @app.get("/api/account-equity-curve")
    def get_account_equity_curve(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        window: str | None = Query(default=None),
        from_iso: str | None = Query(default=None, alias="from"),
        to_iso: str | None = Query(default=None, alias="to"),
        granularity: str = Query(default="hourly"),
        provider: str | None = Query(default=None),
    ) -> dict[str, Any]:
        if window:
            from_dt, to_dt = parse_named_window(window)
        else:
            from_dt, to_dt = parse_window(from_iso, to_iso)
        return equity_curve_for_api(
            config.db_app,
            from_dt=from_dt,
            to_dt=to_dt,
            granularity=granularity,
            target_currency=config.currency,
            provider=provider,
        )

    @app.post("/api/account-equity-curve/snapshot")
    def force_equity_snapshot(
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        live_brokers = _resolve_brokers()
        if not live_brokers:
            raise _error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "no_provider_configured",
                "No broker is configured; cannot snapshot equity",
            )
        snapshots = record_snapshots_all(config, live_brokers, api_logger)
        if not any(snapshots.values()):
            raise _error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "snapshot_failed",
                "Could not read account equity from any configured broker",
            )
        _audit(admin, entity="equity_snapshot", entity_id=None, action="manual_snapshot")
        return {"snapshots": snapshots}

    @app.get("/api/returns-distribution")
    def get_returns_distribution(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        window: str | None = Query(default=None),
        from_iso: str | None = Query(default=None, alias="from"),
        to_iso: str | None = Query(default=None, alias="to"),
        bins: int = Query(default=12, ge=2, le=50),
    ) -> dict[str, Any]:
        if window:
            from_dt, to_dt = parse_named_window(window)
        else:
            from_dt, to_dt = parse_window(from_iso, to_iso)
        return metrics.returns_distribution(from_dt, to_dt, bins=bins)

    @app.get("/api/candles")
    def get_candles(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        symbol: str = Query(...),
        category: str = Query(default="CRYPTO"),
        granularity: str = Query(default="OneDay"),
        count: int = Query(default=120, ge=1, le=1000),
    ) -> dict[str, Any]:
        """Return the most-recent *count* OHLC bars for *symbol* at *granularity*.

        Granularity values accepted by eToro: ``OneMinute``, ``FiveMinutes``,
        ``FifteenMinutes``, ``ThirtyMinutes``, ``OneHour``, ``FourHours``,
        ``OneDay``, ``OneWeek``, ``OneMonth``.  Bars are returned oldest-first.

        Response shape::

            {
                "symbol": "BTC",
                "category": "CRYPTO",
                "granularity": "OneDay",
                "candles": [{"t": ..., "o": ..., "h": ..., "l": ..., "c": ..., "v": ...}, ...]
            }
        """
        live_brokers = _resolve_brokers()
        broker = live_brokers.get(PROVIDER_ETORO)
        if broker is None:
            raise _error(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "no_broker_configured",
                "eToro broker is not configured or not connected",
            )
        normalized = str(symbol).upper().strip()
        try:
            instrument_id = broker.instrument_id_for_symbol(normalized)
            if instrument_id is None:
                raise _error(
                    HTTPStatus.NOT_FOUND,
                    "unknown_symbol",
                    f"Symbol {normalized!r} could not be resolved to an eToro instrument",
                )
            bars = broker.get_candles_by_instrument(
                instrument_id,
                normalized,
                count=count,
                interval=granularity,
            )
        except HTTPException:
            raise
        except Exception as exc:
            api_logger.warning("eToro candles fetch failed for %s: %s", normalized, exc)
            raise _error(
                HTTPStatus.BAD_GATEWAY,
                "broker_error",
                f"eToro API error while fetching candles for {normalized}: {exc}",
            ) from exc
        return {
            "symbol": normalized,
            "category": str(category).upper().strip(),
            "granularity": granularity,
            "candles": [_candle_to_dict(bar) for bar in bars],
        }

    # ----- reports & folders --------------------------------------------

    @app.get("/api/reports")
    def get_reports(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        folder_id: int | None = Query(default=None),
        type_filter: str | None = Query(default=None, alias="type"),
        format_filter: str | None = Query(default=None, alias="format"),
        q: str | None = Query(default=None),
        from_iso: str | None = Query(default=None, alias="from"),
        to_iso: str | None = Query(default=None, alias="to"),
        full_text: bool = Query(default=False, alias="full_text"),
    ) -> dict[str, Any]:
        # Re-sync index in case scheduled jobs added new files since last call.
        try:
            sync_reports(config.db_app, config.report_dir, api_logger)
        except Exception:
            api_logger.exception("Report index sync failed")
        if full_text and q:
            matches = search_reports_full_text(config.db_app, config.report_dir, q)
            return {"items": matches}
        items = list_reports(
            config.db_app,
            folder_id=folder_id,
            rtype=type_filter,
            fmt=format_filter,
            q=q,
            from_iso=from_iso,
            to_iso=to_iso,
        )
        return {"items": items}

    @app.get("/api/reports/{report_id}")
    def get_report_meta(
        report_id: int,
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        row = get_report(config.db_app, report_id)
        if not row:
            raise _error(HTTPStatus.NOT_FOUND, "report_not_found", "Report not found")
        return {"report": row}

    @app.get("/api/reports/{report_id}/file")
    def get_report_file(
        report_id: int,
        download: bool = Query(default=False),
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> FileResponse:
        row = get_report(config.db_app, report_id)
        if not row:
            raise _error(HTTPStatus.NOT_FOUND, "report_not_found", "Report not found")
        path = report_path_for(config.report_dir, str(row["filename"]))
        if path is None:
            raise _error(HTTPStatus.NOT_FOUND, "file_missing", "Report file missing on disk")
        media_type = "application/pdf" if row["format"] == "pdf" else "application/json"
        # Default to ``inline`` so the frontend's <iframe> preview renders the
        # PDF instead of triggering a download. Pass ``?download=true`` when
        # the user clicks the explicit download button to force the
        # ``attachment`` disposition.
        return FileResponse(
            path,
            media_type=media_type,
            filename=str(row["filename"]),
            content_disposition_type="attachment" if download else "inline",
        )

    @app.get("/api/reports/{report_id}/json")
    def get_report_json(
        report_id: int,
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        row = get_report(config.db_app, report_id)
        if not row:
            raise _error(HTTPStatus.NOT_FOUND, "report_not_found", "Report not found")
        if row["format"] != "json":
            raise _error(HTTPStatus.BAD_REQUEST, "not_json", "Only JSON reports can be read here")
        path = report_path_for(config.report_dir, str(row["filename"]))
        if path is None:
            raise _error(HTTPStatus.NOT_FOUND, "file_missing", "Report file missing on disk")
        try:
            content = path.read_text(encoding="utf-8")
            return {"report": row, "content": json.loads(content)}
        except (OSError, json.JSONDecodeError) as exc:
            raise _error(HTTPStatus.INTERNAL_SERVER_ERROR, "read_failed", str(exc)) from exc

    @app.patch("/api/reports/{report_id}")
    def patch_report(
        report_id: int,
        payload: ReportPatchPayload,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        before = get_report(config.db_app, report_id)
        if not before:
            raise _error(HTTPStatus.NOT_FOUND, "report_not_found", "Report not found")
        after = update_report(
            config.db_app,
            report_id,
            folder_id=payload.folder_id,
            tags=payload.tags,
            clear_folder=payload.clear_folder,
        )
        _audit(user, entity="report", entity_id=report_id, action="update", before=before, after=after)
        return {"report": after}

    @app.get("/api/report-folders")
    def get_report_folders(_user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        return {"folders": list_folders(config.db_app)}

    @app.post("/api/report-folders")
    def create_report_folder(
        payload: FolderCreatePayload,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            folder = create_folder(
                config.db_app, name=payload.name, parent_id=payload.parent_id, created_by=user.id
            )
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_folder", str(exc)) from exc
        _audit(user, entity="report_folder", entity_id=folder["id"], action="create", after=folder)
        return {"folder": folder}

    @app.patch("/api/report-folders/{folder_id}")
    def patch_report_folder(
        folder_id: int,
        payload: FolderUpdatePayload,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        try:
            folder = update_folder(config.db_app, folder_id, name=payload.name, parent_id=payload.parent_id)
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_folder", str(exc)) from exc
        if not folder:
            raise _error(HTTPStatus.NOT_FOUND, "folder_not_found", "Folder not found")
        _audit(user, entity="report_folder", entity_id=folder_id, action="update", after=folder)
        return {"folder": folder}

    @app.delete("/api/report-folders/{folder_id}")
    def delete_report_folder(
        folder_id: int,
        user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, bool]:
        delete_folder(config.db_app, folder_id)
        _audit(user, entity="report_folder", entity_id=folder_id, action="delete")
        return {"ok": True}

    # ----- prompts (admin only) -----------------------------------------

    @app.get("/api/prompts")
    def get_prompts(_admin: auth_lib.AuthenticatedUser = Depends(require_admin)) -> dict[str, Any]:
        rows = prompt_store.list_prompts(config.db_app)
        items = [
            {
                "key": r["key"],
                "current_version_id": r["current_version_id"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
        return {"items": items}

    @app.get("/api/prompts/{key}")
    def get_prompt_endpoint(
        key: str = PathParam(...),
        _admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        if key not in app_db.PROMPT_KEYS:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_prompt_key", "Unknown prompt key")
        row = prompt_store.get_prompt_with_version(config.db_app, key)
        if not row:
            raise _error(HTTPStatus.NOT_FOUND, "prompt_not_found", "Prompt not yet seeded")
        return {
            "key": row["key"],
            "content": row["content"],
            "version_id": row["version_id"],
            "updated_at": row["updated_at"],
        }

    @app.get("/api/prompts/{key}/versions")
    def get_prompt_versions(
        key: str = PathParam(...),
        _admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        if key not in app_db.PROMPT_KEYS:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_prompt_key", "Unknown prompt key")
        return {"versions": prompt_store.list_versions(config.db_app, key)}

    @app.post("/api/prompts/{key}")
    def post_prompt_version(
        payload: PromptSavePayload,
        key: str = PathParam(...),
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        if key not in app_db.PROMPT_KEYS:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_prompt_key", "Unknown prompt key")
        try:
            version = prompt_store.save_new_version(
                config.db_app,
                key=key,
                content=payload.content,
                comment=payload.comment,
                saved_by=admin.id,
            )
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_prompt_content", str(exc)) from exc
        _audit(
            admin,
            entity="prompt",
            entity_id=key,
            action="save_version",
            after={"version_id": version["id"], "comment": payload.comment},
        )
        return {"version": version}

    @app.post("/api/prompts/{key}/rollback")
    def rollback_prompt(
        payload: PromptRollbackPayload,
        key: str = PathParam(...),
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        if key not in app_db.PROMPT_KEYS:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_prompt_key", "Unknown prompt key")
        try:
            version = prompt_store.rollback_to_version(
                config.db_app, key=key, version_id=payload.version_id
            )
        except ValueError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_version", str(exc)) from exc
        _audit(
            admin,
            entity="prompt",
            entity_id=key,
            action="rollback",
            after={"version_id": version["id"]},
        )
        return {"version": version}

    # ----- settings ------------------------------------------------------

    @app.get("/api/settings")
    def get_settings(_user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        overlay = app_db.read_all_settings(config.db_app)
        # Also surface the currently-effective values from config (post-overlay).
        # Apply the latest overlay so the UI reflects what the bot would actually use.
        apply_settings_overlay(config, overlay)
        values: dict[str, Any] = {}
        for key in SETTINGS_OVERRIDABLE_KEYS:
            values[key] = getattr(config, key, None)
        # Mask secrets explicitly so the UI never has to know real values.
        for secret_key in (
            "openai_api_key",
            "etoro_api_key",
            "etoro_user_key",
        ):
            values[secret_key] = "********" if getattr(config, secret_key, "") else ""
        # Expose the account currency label read-only so the settings tab can
        # render it as an informational field.
        values["account_currency"] = config.account_currency
        restart_required = _restart_pending(overlay)
        return {
            "values": values,
            "restart_required": restart_required,
            "active_providers": [entry["provider"] for entry in _active_provider_descriptors()],
        }

    @app.patch("/api/settings")
    def patch_settings(
        payload: dict[str, Any],
        user: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        before = app_db.read_all_settings(config.db_app)
        accepted: dict[str, Any] = {}
        for key, value in payload.items():
            if key not in SETTINGS_OVERRIDABLE_KEYS:
                continue
            app_db.write_setting(config.db_app, key, value, updated_by=user.id)
            accepted[key] = value
        if accepted:
            apply_settings_overlay(config, accepted)
        _audit(
            user,
            entity="settings",
            entity_id=None,
            action="update",
            before=before,
            after=app_db.read_all_settings(config.db_app),
        )
        restart_required = _restart_pending(app_db.read_all_settings(config.db_app))
        return {
            "values": {key: getattr(config, key, None) for key in SETTINGS_OVERRIDABLE_KEYS},
            "restart_required": restart_required,
        }

    # ----- audit log -----------------------------------------------------

    @app.get("/api/audit")
    def get_audit(
        _admin: auth_lib.AuthenticatedUser = Depends(require_admin),
        actor: str | None = Query(default=None),
        entity: str | None = Query(default=None),
        from_iso: str | None = Query(default=None, alias="from"),
        to_iso: str | None = Query(default=None, alias="to"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        sql = ["SELECT * FROM audit_log WHERE 1=1"]
        params: list[Any] = []
        if actor:
            sql.append("AND actor_name LIKE ?")
            params.append(f"%{actor}%")
        if entity:
            sql.append("AND entity = ?")
            params.append(entity)
        if from_iso:
            sql.append("AND created_at >= ?")
            params.append(from_iso)
        if to_iso:
            sql.append("AND created_at < ?")
            params.append(to_iso)
        sql.append("ORDER BY created_at DESC, id DESC")
        sql.append("LIMIT ? OFFSET ?")
        params.extend([page_size, (page - 1) * page_size])
        items = app_db.app_fetch_all(config.db_app, " ".join(sql), tuple(params))
        return {"items": items, "page": page, "page_size": page_size}

    # ----- existing manual generation endpoints (now auth-gated) ---------

    # Manual triggers (universe regen, GPT order generation, weekly/quarterly
    # PDF reports) can take minutes. Running them inline blocks the HTTP
    # response for that whole time, which from the operator's point of view
    # looks frozen. We run them in a small dedicated pool and only wait long
    # enough on the request thread to surface fast outcomes (lock conflicts,
    # immediate failures, instant jobs). Anything still running after the
    # short wait keeps going in the background and the operator can follow
    # progress in the logs.
    _manual_jobs_executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="manual-job"
    )
    _MANUAL_FAST_OUTCOME_SECONDS = 3.0

    def _run_manual(action: str, handler: Any) -> dict[str, Any]:
        future = _manual_jobs_executor.submit(handler)
        try:
            future.result(timeout=_MANUAL_FAST_OUTCOME_SECONDS)
        except concurrent.futures.TimeoutError:
            api_logger.info(
                "Manual API request for %s started; job continues in background",
                action,
            )
            return {
                "status": "ok",
                "action": action,
                "message": f"{action} job avviato in background",
                "background": True,
            }
        except JobExecutionLockedError as exc:
            api_logger.warning("Manual API request for %s skipped: %s", action, exc)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"status": "error", "action": action, "message": str(exc)},
            ) from exc
        except Exception as exc:
            api_logger.exception("Manual API request for %s failed", action)
            raise HTTPException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                detail={"status": "error", "action": action, "message": f"Failed to start {action} job"},
            ) from exc
        return {"status": "ok", "action": action, "message": f"{action} job completed successfully"}

    @app.get("/api/universe/generate")
    def manual_universe(
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        result = _run_manual("universe", scheduler.run_manual_refresh_universe)
        _audit(admin, entity="job", entity_id="universe", action="manual_run")
        return result

    @app.get("/api/universe")
    def get_universe(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        live_brokers = _resolve_brokers()
        return {
            "universe": get_universe_with_metadata(live_brokers, api_logger),
            "active_providers": [entry["provider"] for entry in _active_provider_descriptors()],
        }

    @app.post("/api/universe/symbols")
    def add_universe_symbol(
        payload: UniverseSymbolPayload,
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        live_brokers = _resolve_brokers()
        provider = (payload.provider or PROVIDER_ETORO).lower()
        try:
            result = universe_add_symbol(
                config,
                live_brokers,
                api_logger,
                provider=provider,
                category=payload.category,
                symbol=payload.symbol,
            )
        except UniverseValidationError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_symbol", str(exc)) from exc
        _audit(
            admin,
            entity="universe",
            entity_id=f"{result['provider']}:{result['category']}:{result['symbol']}",
            action="add",
            after=result,
        )
        return result

    @app.delete("/api/universe/symbols/{provider}/{category}/{symbol:path}")
    def delete_universe_symbol(
        provider: str,
        category: str,
        symbol: str,
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            result = universe_remove_symbol(
                config,
                api_logger,
                provider=provider,
                category=category,
                symbol=symbol,
            )
        except UniverseValidationError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_symbol", str(exc)) from exc
        _audit(
            admin,
            entity="universe",
            entity_id=f"{result['provider']}:{result['category']}:{result['symbol']}",
            action="remove",
            after=result,
        )
        return result

    # Legacy two-segment route (no explicit provider): kept for backwards
    # compatibility with older frontends; defaults to eToro.
    @app.delete("/api/universe/symbols/{category}/{symbol:path}")
    def delete_universe_symbol_legacy(
        category: str,
        symbol: str,
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        try:
            result = universe_remove_symbol(
                config,
                api_logger,
                provider=PROVIDER_ETORO,
                category=category,
                symbol=symbol,
            )
        except UniverseValidationError as exc:
            raise _error(HTTPStatus.BAD_REQUEST, "invalid_symbol", str(exc)) from exc
        _audit(
            admin,
            entity="universe",
            entity_id=f"{result['provider']}:{result['category']}:{result['symbol']}",
            action="remove",
            after=result,
        )
        return result

    @app.get("/api/orders/generate")
    def manual_orders(
        admin: auth_lib.AuthenticatedUser = Depends(require_admin),
    ) -> dict[str, Any]:
        result = _run_manual("new_orders", scheduler.run_manual_generate_new_orders)
        _audit(admin, entity="job", entity_id="new_orders", action="manual_run")
        return result

    @app.get("/api/report/generate")
    def manual_report(admin: auth_lib.AuthenticatedUser = Depends(require_admin)) -> dict[str, Any]:
        result = _run_manual("report", scheduler.run_manual_weekly_report)
        _audit(admin, entity="job", entity_id="weekly_report", action="manual_run")
        return result

    @app.get("/api/report/quarterly")
    def manual_quarterly(admin: auth_lib.AuthenticatedUser = Depends(require_admin)) -> dict[str, Any]:
        result = _run_manual("quarterly_report", scheduler.run_manual_quarterly_report)
        _audit(admin, entity="job", entity_id="quarterly_report", action="manual_run")
        return result

    @app.get("/api/report/biannual")
    def manual_biannual(admin: auth_lib.AuthenticatedUser = Depends(require_admin)) -> dict[str, Any]:
        result = _run_manual("biannual_report", scheduler.run_manual_biannual_report)
        _audit(admin, entity="job", entity_id="biannual_report", action="manual_run")
        return result

    @app.get("/api/report/annual")
    def manual_annual(admin: auth_lib.AuthenticatedUser = Depends(require_admin)) -> dict[str, Any]:
        result = _run_manual("annual_report", scheduler.run_manual_annual_report)
        _audit(admin, entity="job", entity_id="annual_report", action="manual_run")
        return result

    @app.get("/api/scheduler/reset")
    def manual_reset(admin: auth_lib.AuthenticatedUser = Depends(require_admin)) -> dict[str, Any]:
        outcome = scheduler.reset_locks()
        _audit(admin, entity="job", entity_id="scheduler", action="reset_locks", after=outcome)
        return {
            "status": "ok",
            "action": "scheduler_reset",
            "message": "scheduler_reset completed successfully",
            **outcome,
        }

    # ----- logs (auth-gated) --------------------------------------------

    @app.get("/api/logs")
    def get_logs(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
        lines: int = Query(default=10000, ge=1, le=100000),
    ) -> dict[str, Any]:
        log_path = Path(config.log_file)
        if not log_path.exists():
            return {
                "log_file": str(log_path),
                "line_count": lines,
                "logs": "Log file not found.",
                "updated_at": "N/A",
            }
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                tail = handle.readlines()[-lines:]
            content = "".join(tail)
        except OSError as exc:
            content = f"Failed to read log file: {exc}"
        updated_at = isoformat_utc(datetime.fromtimestamp(log_path.stat().st_mtime, tz=UTC)) or "N/A"
        return {
            "log_file": str(log_path),
            "line_count": lines,
            "logs": content,
            "updated_at": updated_at,
        }

    @app.get("/api/logs/stream")
    def get_logs_stream(_user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> StreamingResponse:
        log_path = Path(config.log_file)

        async def streamer() -> Any:
            yield _format_event("heartbeat", isoformat_utc(utc_now()) or "")
            if not log_path.exists():
                yield _format_event("append", "Log file not found.\n")
            position = log_path.stat().st_size if log_path.exists() else 0
            last_heartbeat_ts = utc_now()
            while True:
                if log_path.exists():
                    current_size = log_path.stat().st_size
                    if current_size < position:
                        position = 0
                    if current_size > position:
                        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                            handle.seek(position)
                            chunk = handle.read()
                            position = handle.tell()
                        if chunk:
                            yield _format_event("append", chunk)
                now = utc_now()
                if (now - last_heartbeat_ts).total_seconds() >= 1:
                    yield _format_event("heartbeat", isoformat_utc(now) or "")
                    last_heartbeat_ts = now
                await asyncio.sleep(1)

        return StreamingResponse(streamer(), media_type="text/event-stream")

    @app.get("/api/live/stream")
    def get_live_stream(
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> StreamingResponse:
        """Stream the live portfolio snapshot as Server-Sent Events.

        Emits a ``snapshot`` event every ``_LIVE_STREAM_INTERVAL_SECONDS``
        seconds containing the current live snapshot JSON, plus a
        ``heartbeat`` event at least every 15 seconds to keep the
        connection alive through proxies.
        """

        async def streamer() -> Any:
            yield _format_event("heartbeat", isoformat_utc(utc_now()) or "")
            last_heartbeat = utc_now()
            while True:
                try:
                    loop = asyncio.get_running_loop()
                    snapshot = await loop.run_in_executor(None, live_cache.get_snapshot)
                    yield _format_event("snapshot", json.dumps(snapshot))
                except Exception:
                    api_logger.exception("live snapshot failed")
                now = utc_now()
                if (now - last_heartbeat).total_seconds() >= 15:
                    yield _format_event("heartbeat", isoformat_utc(now) or "")
                    last_heartbeat = now
                await asyncio.sleep(_LIVE_STREAM_INTERVAL_SECONDS)

        return StreamingResponse(streamer(), media_type="text/event-stream")

    # ----- legend (column glossary sourced from backend/README.md) -------

    @app.get("/api/legend")
    def get_legend(_user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> dict[str, Any]:
        readme = Path(__file__).resolve().parents[1] / "README.md"
        try:
            content = readme.read_text(encoding="utf-8")
        except OSError:
            content = ""
        return {"glossary_markdown": content, "fields": list(EDITABLE_TRADE_FIELDS)}

    return app


# ----- thin wrapper kept so main.py only swaps the implementation -----------


class FastApiServerWrapper:
    """Run a FastAPI app on uvicorn inside the process.

    Mirrors the small lifecycle surface (`serve_forever`, `shutdown`,
    `server_close`) used by `main.py` so that the rest of the entry-point
    code does not need to change.
    """

    def __init__(
        self,
        host: str,
        port: int,
        app: FastAPI,
        logger: logging.Logger,
    ) -> None:
        import uvicorn  # local import so `python -c "import api"` doesn't pull uvicorn

        self.host = host
        self.port = port
        self.app = app
        self.logger = logger.getChild("api.server")
        self._uvicorn_config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="info",
            access_log=False,
            lifespan="off",
        )
        self._server = uvicorn.Server(self._uvicorn_config)
        self._stop_event = threading.Event()

    def serve_forever(self) -> None:  # pragma: no cover - thin runner
        self._server.run()

    def shutdown(self) -> None:
        self._server.should_exit = True
        self._stop_event.set()

    def server_close(self) -> None:
        # uvicorn cleans up after run() returns; nothing extra to do.
        return None


def create_api_server(host: str, port: int, scheduler: TradingScheduler, logger: logging.Logger) -> FastApiServerWrapper:
    """Create the FastAPI app + uvicorn wrapper used by ``main.py``."""

    app = create_app(scheduler, logger)
    return FastApiServerWrapper(host, port, app, logger)
