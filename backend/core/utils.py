"""Shared utilities and configuration helpers."""

from __future__ import annotations

import json
import os
import time
from uuid import uuid4
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv

F = TypeVar("F", bound=Callable[..., Any])
BASE_DIR = Path(__file__).resolve().parents[1]
UNIVERSE_FILE = BASE_DIR / "data/universe.json"


# Subset of AppConfig fields that operators can override at runtime through
# the Settings UI. Anything not listed here stays bound to .env / build env.
SETTINGS_OVERRIDABLE_KEYS: frozenset[str] = frozenset(
    {
        "max_open_trades_stock",
        "max_open_trades_crypto",
        "weekly_universe_stocks",
        "weekly_universe_crypto",
        "currency",
        "risk_tolerance",
        "strategy_horizon_days_min",
        "strategy_horizon_days_max",
        "crypto_entry_limit_collar_bps",
        "crypto_entry_max_chase_bps",
        "crypto_pending_reprice_minutes",
        "crypto_pending_cancel_minutes",
        "log_level",
        "log_profile",
    }
)

# Settings whose change requires a restart (or, for future iterations, a hot
# reload that the runtime does not yet implement). The UI surfaces this so the
# operator knows whether they need to restart the container.
SETTINGS_RESTART_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "log_level",
        "log_profile",
    }
)


@dataclass(slots=True)
class AppConfig:
    """Application configuration loaded from environment variables."""

    openai_api_key: str
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str
    openai_model_heavy: str = "gpt-5.4"
    openai_model_mid: str = "gpt-5.4-mini"
    openai_model_light: str = "gpt-5.4-nano"
    openai_reasoning_effort: str = "medium"
    max_open_trades_stock: int = 3
    max_open_trades_crypto: int = 3
    weekly_universe_stocks: int = 5
    weekly_universe_crypto: int = 5
    risk_tolerance: int = 5
    currency: str = "EUR"
    crypto_entry_limit_collar_bps: int = 15
    crypto_entry_max_chase_bps: int = 40
    crypto_pending_reprice_minutes: int = 2
    crypto_pending_cancel_minutes: int = 12
    strategy_horizon_days_min: int = 90
    strategy_horizon_days_max: int = 120
    log_profile: str = "PRODUCTION"
    log_level: str = "INFO"
    log_file: str = "logs/trading_bot.log"
    universe_log_file: str = "logs/universe_candidates.log"
    report_dir: str = "data/reports"
    db_market_data: str = "data/market_data.sqlite"
    db_trades: str = "data/trades.sqlite"
    db_app: str = "data/app.sqlite"
    lock_file: str = "run/trading_scheduler.lock"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_allowed_origins: tuple[str, ...] = ()
    admin_username: str = ""
    admin_password: str = ""
    admin_display_name: str = ""
    session_cookie_secure: bool = False
    session_cookie_samesite: str = "lax"
    account_currency: str = "USD"

    @property
    def paper(self) -> bool:
        return "paper" in self.alpaca_base_url.lower() or "sandbox" in self.alpaca_base_url.lower()

    @property
    def debug_logging(self) -> bool:
        return self.log_profile.upper() == "DEBUG" or self.log_level.upper() == "DEBUG"


def ensure_parent_dir(file_path: str | Path) -> None:
    """Create the parent directory for a file path if it does not exist."""

    Path(file_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def resolve_runtime_path(file_path: str | Path) -> str:
    """Resolve application runtime files relative to the project root."""

    candidate = Path(file_path).expanduser()
    if not candidate.is_absolute():
        candidate = BASE_DIR / candidate
    return str(candidate.resolve())


def load_config() -> AppConfig:
    """Load environment variables into the application config."""

    load_dotenv()
    config = AppConfig(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        alpaca_api_key=os.getenv("ALPACA_API_KEY", ""),
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        alpaca_base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        openai_model_heavy=os.getenv("OPENAI_MODEL_HEAVY", "gpt-5.4"),
        openai_model_mid=os.getenv("OPENAI_MODEL_MID", "gpt-5.4-mini"),
        openai_model_light=os.getenv("OPENAI_MODEL_LIGHT", "gpt-5.4-nano"),
        openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium").lower(),
        max_open_trades_stock=int(os.getenv("MAX_OPEN_TRADES_STOCK", "3")),
        max_open_trades_crypto=int(os.getenv("MAX_OPEN_TRADES_CRYPTO", "3")),
        weekly_universe_stocks=int(os.getenv("WEEKLY_UNIVERSE_STOCKS", "5")),
        weekly_universe_crypto=int(os.getenv("WEEKLY_UNIVERSE_CRYPTO", "5")),
        risk_tolerance=max(1, min(10, int(os.getenv("RISK_TOLERANCE", "5")))),
        currency=os.getenv("CURRENCY", "EUR").upper(),
        crypto_entry_limit_collar_bps=max(0, int(os.getenv("CRYPTO_ENTRY_LIMIT_COLLAR_BPS", "15"))),
        crypto_entry_max_chase_bps=max(0, int(os.getenv("CRYPTO_ENTRY_MAX_CHASE_BPS", "40"))),
        crypto_pending_reprice_minutes=max(1, int(os.getenv("CRYPTO_PENDING_REPRICE_MINUTES", "2"))),
        crypto_pending_cancel_minutes=max(1, int(os.getenv("CRYPTO_PENDING_CANCEL_MINUTES", "12"))),
        strategy_horizon_days_min=int(os.getenv("STRATEGY_HORIZON_DAYS_MIN", "90")),
        strategy_horizon_days_max=int(os.getenv("STRATEGY_HORIZON_DAYS_MAX", "120")),
        log_profile=os.getenv("LOG_PROFILE", "PRODUCTION").upper(),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_file=os.getenv("LOG_FILE", "logs/trading_bot.log"),
        universe_log_file=os.getenv("UNIVERSE_LOG_FILE", "logs/universe_candidates.log"),
        report_dir=os.getenv("REPORT_DIR", "data/reports"),
        db_market_data=os.getenv("DB_MARKET_DATA", "data/market_data.sqlite"),
        db_trades=os.getenv("DB_TRADES", "data/trades.sqlite"),
        lock_file=os.getenv("LOCK_FILE", "run/trading_scheduler.lock"),
        api_host=os.getenv("API_HOST", "0.0.0.0"),
        api_port=int(os.getenv("API_PORT", "8000")),
        cors_allowed_origins=tuple(
            origin.strip()
            for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        ),
        db_app=os.getenv("DB_APP", "data/app.sqlite"),
        admin_username=os.getenv("ADMIN_USERNAME", "").strip(),
        admin_password=os.getenv("ADMIN_PASSWORD", ""),
        admin_display_name=os.getenv("ADMIN_DISPLAY_NAME", "").strip(),
        session_cookie_secure=os.getenv("SESSION_COOKIE_SECURE", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        session_cookie_samesite=os.getenv("SESSION_COOKIE_SAMESITE", "lax").strip().lower() or "lax",
        account_currency=(os.getenv("ACCOUNT_CURRENCY", "USD") or "USD").strip().upper(),
    )
    config.log_file = resolve_runtime_path(config.log_file)
    config.universe_log_file = resolve_runtime_path(config.universe_log_file)
    config.report_dir = resolve_runtime_path(config.report_dir)
    config.db_market_data = resolve_runtime_path(config.db_market_data)
    config.db_trades = resolve_runtime_path(config.db_trades)
    config.db_app = resolve_runtime_path(config.db_app)
    config.lock_file = resolve_runtime_path(config.lock_file)
    ensure_parent_dir(config.log_file)
    ensure_parent_dir(config.universe_log_file)
    Path(config.report_dir).mkdir(parents=True, exist_ok=True)
    ensure_parent_dir(config.db_market_data)
    ensure_parent_dir(config.db_trades)
    ensure_parent_dir(config.db_app)
    ensure_parent_dir(config.lock_file)
    ensure_parent_dir(UNIVERSE_FILE)
    return config


def apply_settings_overlay(config: AppConfig, overlay: dict[str, Any]) -> AppConfig:
    """Mutate ``config`` in place with operator-supplied overrides.

    Only keys in :data:`SETTINGS_OVERRIDABLE_KEYS` are honored. Values are
    coerced to the field type, so the same JSON blob can survive round-trips
    through SQLite. Returns the same config object for convenience.
    """

    def _coerce(name: str, raw: Any, current: Any) -> Any:
        if raw is None:
            return current
        if isinstance(current, bool):
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(current, int) and not isinstance(current, bool):
            try:
                return int(raw)
            except (TypeError, ValueError):
                return current
        if isinstance(current, float):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return current
        if isinstance(current, str):
            return str(raw)
        return raw

    for key, value in overlay.items():
        if key not in SETTINGS_OVERRIDABLE_KEYS:
            continue
        if not hasattr(config, key):
            continue
        current = getattr(config, key)
        try:
            setattr(config, key, _coerce(key, value, current))
        except (TypeError, ValueError):
            continue

    # Sanity: never let risk_tolerance leave [1, 10].
    config.risk_tolerance = max(1, min(10, int(config.risk_tolerance)))
    return config


def utc_now() -> datetime:
    """Return an aware UTC timestamp."""

    return datetime.now(UTC)


def isoformat_utc(value: datetime | None) -> str | None:
    """Serialize a UTC datetime."""

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an ISO datetime string if present."""

    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[F], F]:
    """Retry decorator with exponential backoff."""

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: BaseException | None = None
            logger = getattr(args[0], "logger", None) if args else None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # type: ignore[arg-type]
                    last_error = exc
                    if logger:
                        config = getattr(args[0], "config", None) if args else None
                        debug_logging = bool(getattr(config, "debug_logging", False))
                        if debug_logging:
                            logger.warning(
                                "Attempt %s/%s failed in %s: %s",
                                attempt,
                                max_attempts,
                                func.__name__,
                                exc,
                                exc_info=True,
                            )
                        elif attempt == max_attempts:
                            logger.warning(
                                "Attempt %s/%s failed in %s: %s",
                                attempt,
                                max_attempts,
                                func.__name__,
                                exc,
                            )
                        else:
                            logger.debug(
                                "Attempt %s/%s failed in %s: %s",
                                attempt,
                                max_attempts,
                                func.__name__,
                                exc,
                            )
                    if attempt == max_attempts:
                        break
                    time.sleep(base_delay * (2 ** (attempt - 1)))
            raise last_error or RuntimeError(f"{func.__name__} failed without raising an error")

        return wrapper  # type: ignore[return-value]

    return decorator


def build_mixed_timeframe_ohlcv(
    rows: list[dict[str, Any]],
    recent_daily: int = 60,
    weekly_count: int = 30,
) -> dict[str, list[dict[str, Any]]]:
    """Return last N daily bars plus older period aggregated to weekly bars."""

    if not rows:
        return {"daily": [], "weekly": []}

    sorted_rows = sorted(rows, key=lambda r: r.get("timestamp") or "")
    if len(sorted_rows) <= recent_daily:
        return {"daily": sorted_rows, "weekly": []}
    daily_part = sorted_rows[-recent_daily:]
    older_part = sorted_rows[:-recent_daily]
    weekly_part = _aggregate_daily_to_weekly(older_part)[-weekly_count:]
    return {"daily": daily_part, "weekly": weekly_part}


def _aggregate_daily_to_weekly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    bars: list[dict[str, Any]] = []
    bucket: list[dict[str, Any]] = []
    current_key: tuple[int, int] | None = None
    for row in rows:
        ts_value = row.get("timestamp")
        dt = parse_datetime(ts_value) if isinstance(ts_value, str) else ts_value
        if dt is None:
            continue
        iso = dt.isocalendar()
        key = (iso[0], iso[1])
        if current_key is None:
            current_key = key
        if key != current_key:
            bars.append(_build_weekly_bar(bucket))
            bucket = []
            current_key = key
        bucket.append(row)
    if bucket:
        bars.append(_build_weekly_bar(bucket))
    return bars


def _build_weekly_bar(rows: list[dict[str, Any]]) -> dict[str, Any]:
    highs = [float(r["high"]) for r in rows if r.get("high") is not None]
    lows = [float(r["low"]) for r in rows if r.get("low") is not None]
    volumes = [float(r["volume"]) for r in rows if r.get("volume") is not None]
    return {
        "timestamp": rows[0].get("timestamp"),
        "open": rows[0].get("open"),
        "high": max(highs) if highs else None,
        "low": min(lows) if lows else None,
        "close": rows[-1].get("close"),
        "volume": sum(volumes) if volumes else 0.0,
    }


def to_json(data: Any) -> str:
    """Serialize data in a stable JSON format."""

    return json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True)


def to_toon(data: Any) -> str:
    """Serialize data in TOON format for reduced token usage."""

    from toon_format import encode  # type: ignore[import]
    return encode(data)


def read_universe_file() -> dict[str, list[str]]:
    """Load the saved universe from disk."""

    if not UNIVERSE_FILE.exists():
        return {"STOCK": [], "CRYPTO": []}
    return json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))


def write_universe_file(payload: dict[str, list[str]]) -> None:
    """Persist the current universe to disk."""

    ensure_parent_dir(UNIVERSE_FILE)
    temp_path = UNIVERSE_FILE.with_name(f"{UNIVERSE_FILE.name}.{uuid4().hex}.tmp")
    temp_path.write_text(to_json(payload), encoding="utf-8")
    temp_path.replace(UNIVERSE_FILE)


def write_json_file(file_path: str | Path, payload: Any) -> None:
    """Persist arbitrary JSON payloads to disk."""

    destination = Path(file_path)
    ensure_parent_dir(destination)
    temp_path = destination.with_name(f"{destination.name}.{uuid4().hex}.tmp")
    temp_path.write_text(to_json(payload), encoding="utf-8")
    temp_path.replace(destination)


def market_data_start(first_download: bool) -> datetime:
    """Choose the backfill start date for market data downloads."""

    now = utc_now()
    if first_download:
        return now - timedelta(days=365 * 2)
    return now - timedelta(days=7)
