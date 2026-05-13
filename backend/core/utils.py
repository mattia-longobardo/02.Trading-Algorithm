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


PROVIDER_ALPACA = "alpaca"
PROVIDER_BINANCE = "binance"
ALL_PROVIDERS: tuple[str, ...] = (PROVIDER_ALPACA, PROVIDER_BINANCE)


# Subset of AppConfig fields that operators can override at runtime through
# the Settings UI. Anything not listed here stays bound to .env / build env.
SETTINGS_OVERRIDABLE_KEYS: frozenset[str] = frozenset(
    {
        "max_open_trades_stock",
        "max_open_trades_crypto",
        "max_open_trades_binance",
        "weekly_universe_stocks",
        "weekly_universe_crypto",
        "weekly_universe_binance",
        "currency",
        "risk_tolerance",
        "strategy_horizon_days_min",
        "strategy_horizon_days_max",
        "crypto_entry_limit_collar_bps",
        "crypto_entry_max_chase_bps",
        "crypto_pending_reprice_minutes",
        "crypto_pending_cancel_minutes",
        "binance_entry_limit_collar_bps",
        "binance_entry_max_chase_bps",
        "binance_pending_reprice_minutes",
        "binance_pending_cancel_minutes",
        "alpaca_max_notional_per_order",
        "trailing_tp_min_profit_buffer_pct",
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
    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_base_url: str = "https://api.binance.com"
    # Path to an Ed25519 or RSA private-key PEM file. When configured the
    # Binance client signs requests with this key (Binance's newer SSH-style
    # API model) instead of the HMAC-SHA256 secret. ``binance_secret_key``
    # remains optional when a key file is used.
    binance_private_key_path: str = ""
    binance_private_key_password: str = ""
    openai_model_heavy: str = "gpt-5.4"
    openai_model_mid: str = "gpt-5.4-mini"
    openai_model_light: str = "gpt-5.4-nano"
    openai_reasoning_effort: str = "medium"
    max_open_trades_stock: int = 3
    max_open_trades_crypto: int = 3
    max_open_trades_binance: int = 3
    weekly_universe_stocks: int = 5
    weekly_universe_crypto: int = 5
    weekly_universe_binance: int = 5
    risk_tolerance: int = 5
    currency: str = "EUR"
    crypto_entry_limit_collar_bps: int = 15
    crypto_entry_max_chase_bps: int = 40
    crypto_pending_reprice_minutes: int = 2
    crypto_pending_cancel_minutes: int = 12
    # Alpaca caps single-order notional at $200k (error 40310000). When the
    # per-trade allocation exceeds this, we shrink the order to the cap so
    # the broker accepts it instead of rejecting the trade outright.
    alpaca_max_notional_per_order: float = 200_000.0
    binance_entry_limit_collar_bps: int = 15
    binance_entry_max_chase_bps: int = 40
    binance_pending_reprice_minutes: int = 2
    binance_pending_cancel_minutes: int = 12
    # Minimum profit cushion (in percent of entry_price) that the trailing
    # take profit must guarantee. The bot rejects GPT signals whose
    # `activation_pct − distance/entry × 100` falls below this buffer and
    # floors the runtime trigger at `entry × (1 + buffer/100)` as a safety
    # belt. Default 0.5% covers ~2× crypto round-trip fees plus typical
    # slippage on liquid pairs.
    trailing_tp_min_profit_buffer_pct: float = 0.5
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
    binance_quote_currency: str = "USDT"

    @property
    def paper(self) -> bool:
        return "paper" in self.alpaca_base_url.lower() or "sandbox" in self.alpaca_base_url.lower()

    @property
    def debug_logging(self) -> bool:
        return self.log_profile.upper() == "DEBUG" or self.log_level.upper() == "DEBUG"

    @property
    def alpaca_enabled(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_secret_key)

    @property
    def binance_enabled(self) -> bool:
        # Either the legacy HMAC secret or an asymmetric private-key file is
        # enough to sign requests — but the API key (the public identifier
        # Binance assigns) is always required.
        return bool(self.binance_api_key and (self.binance_secret_key or self.binance_private_key_path))

    @property
    def binance_uses_asymmetric_key(self) -> bool:
        return bool(self.binance_private_key_path)

    def active_providers(self) -> tuple[str, ...]:
        """Return the providers configured with credentials, in stable order."""

        active: list[str] = []
        if self.alpaca_enabled:
            active.append(PROVIDER_ALPACA)
        if self.binance_enabled:
            active.append(PROVIDER_BINANCE)
        return tuple(active)

    def provider_account_currency(self, provider: str) -> str:
        if provider == PROVIDER_BINANCE:
            return self.binance_quote_currency
        return self.account_currency

    def provider_max_open_crypto(self, provider: str) -> int:
        if provider == PROVIDER_BINANCE:
            return int(self.max_open_trades_binance)
        return int(self.max_open_trades_crypto)

    def provider_weekly_universe_size(self, provider: str) -> int:
        if provider == PROVIDER_BINANCE:
            return int(self.weekly_universe_binance)
        return int(self.weekly_universe_crypto)


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
        alpaca_api_key=os.getenv("ALPACA_API_KEY", "").strip(),
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY", "").strip(),
        alpaca_base_url=os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
        binance_api_key=os.getenv("BINANCE_API_KEY", "").strip(),
        binance_secret_key=os.getenv("BINANCE_SECRET_KEY", "").strip(),
        binance_base_url=(os.getenv("BINANCE_BASE_URL", "https://api.binance.com") or "https://api.binance.com").strip(),
        binance_private_key_path=os.getenv("BINANCE_PRIVATE_KEY_PATH", "").strip(),
        binance_private_key_password=os.getenv("BINANCE_PRIVATE_KEY_PASSWORD", ""),
        openai_model_heavy=os.getenv("OPENAI_MODEL_HEAVY", "gpt-5.4"),
        openai_model_mid=os.getenv("OPENAI_MODEL_MID", "gpt-5.4-mini"),
        openai_model_light=os.getenv("OPENAI_MODEL_LIGHT", "gpt-5.4-nano"),
        openai_reasoning_effort=os.getenv("OPENAI_REASONING_EFFORT", "medium").lower(),
        max_open_trades_stock=int(os.getenv("MAX_OPEN_TRADES_STOCK", "3")),
        max_open_trades_crypto=int(os.getenv("MAX_OPEN_TRADES_CRYPTO", "3")),
        max_open_trades_binance=int(os.getenv("MAX_OPEN_TRADES_BINANCE", "3")),
        weekly_universe_stocks=int(os.getenv("WEEKLY_UNIVERSE_STOCKS", "5")),
        weekly_universe_crypto=int(os.getenv("WEEKLY_UNIVERSE_CRYPTO", "5")),
        weekly_universe_binance=int(os.getenv("WEEKLY_UNIVERSE_BINANCE", "5")),
        risk_tolerance=max(1, min(10, int(os.getenv("RISK_TOLERANCE", "5")))),
        currency=os.getenv("CURRENCY", "EUR").upper(),
        crypto_entry_limit_collar_bps=max(0, int(os.getenv("CRYPTO_ENTRY_LIMIT_COLLAR_BPS", "15"))),
        crypto_entry_max_chase_bps=max(0, int(os.getenv("CRYPTO_ENTRY_MAX_CHASE_BPS", "40"))),
        crypto_pending_reprice_minutes=max(1, int(os.getenv("CRYPTO_PENDING_REPRICE_MINUTES", "2"))),
        crypto_pending_cancel_minutes=max(1, int(os.getenv("CRYPTO_PENDING_CANCEL_MINUTES", "12"))),
        alpaca_max_notional_per_order=max(0.0, float(os.getenv("ALPACA_MAX_NOTIONAL_PER_ORDER", "200000"))),
        binance_entry_limit_collar_bps=max(0, int(os.getenv("BINANCE_ENTRY_LIMIT_COLLAR_BPS", os.getenv("CRYPTO_ENTRY_LIMIT_COLLAR_BPS", "15")))),
        binance_entry_max_chase_bps=max(0, int(os.getenv("BINANCE_ENTRY_MAX_CHASE_BPS", os.getenv("CRYPTO_ENTRY_MAX_CHASE_BPS", "40")))),
        binance_pending_reprice_minutes=max(1, int(os.getenv("BINANCE_PENDING_REPRICE_MINUTES", os.getenv("CRYPTO_PENDING_REPRICE_MINUTES", "2")))),
        binance_pending_cancel_minutes=max(1, int(os.getenv("BINANCE_PENDING_CANCEL_MINUTES", os.getenv("CRYPTO_PENDING_CANCEL_MINUTES", "12")))),
        trailing_tp_min_profit_buffer_pct=max(0.0, float(os.getenv("TRAILING_TP_MIN_PROFIT_BUFFER_PCT", "0.5"))),
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
        # ``ALPACA_ACCOUNT_CURRENCY`` is the new, explicit name. ``ACCOUNT_CURRENCY``
        # is kept as a fallback so pre-Binance ``.env`` files keep working.
        account_currency=(
            os.getenv("ALPACA_ACCOUNT_CURRENCY")
            or os.getenv("ACCOUNT_CURRENCY")
            or "USD"
        ).strip().upper(),
        binance_quote_currency=(os.getenv("BINANCE_QUOTE_CURRENCY", "USDT") or "USDT").strip().upper(),
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
    should_retry: Callable[[BaseException], bool] | None = None,
) -> Callable[[F], F]:
    """Retry decorator with exponential backoff.

    ``should_retry`` lets callers fail fast on deterministic errors (e.g.
    broker validation failures like "notional exceeds max") so a single
    submitted-but-invalid order is not retried 3× — which would log a
    duplicate "Submitting…" line per attempt for the same pair, and risk
    creating real duplicate positions if a write call ever partially
    succeeded. Returns ``True`` to retry, ``False`` to re-raise immediately.
    Defaults to retrying every caught exception.
    """

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
                    retryable = should_retry(exc) if should_retry else True
                    if logger:
                        config = getattr(args[0], "config", None) if args else None
                        debug_logging = bool(getattr(config, "debug_logging", False))
                        if not retryable:
                            logger.warning(
                                "Non-retryable error in %s, failing fast: %s",
                                func.__name__,
                                exc,
                                exc_info=debug_logging,
                            )
                        elif debug_logging:
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
                    if not retryable:
                        raise
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


ProviderUniverse = dict[str, dict[str, list[str]]]


def _empty_universe() -> ProviderUniverse:
    return {
        PROVIDER_ALPACA: {"STOCK": [], "CRYPTO": []},
        PROVIDER_BINANCE: {"CRYPTO": []},
    }


def _normalize_universe_payload(raw: Any) -> ProviderUniverse:
    """Coerce any historical or partial payload into the current schema.

    The legacy schema stored a flat ``{"STOCK": [...], "CRYPTO": [...]}`` map
    that targeted Alpaca only. New writers always use the provider-tagged
    schema (``{"alpaca": {...}, "binance": {...}}``); this helper makes both
    forms readable so the migration is transparent.
    """

    universe = _empty_universe()
    if not isinstance(raw, dict):
        return universe

    if any(key in raw for key in ALL_PROVIDERS):
        for provider in ALL_PROVIDERS:
            entry = raw.get(provider)
            if not isinstance(entry, dict):
                continue
            for category, symbols in entry.items():
                if not isinstance(symbols, list):
                    continue
                cat = str(category).upper()
                cleaned = [str(s).upper().strip() for s in symbols if str(s).strip()]
                universe.setdefault(provider, {})[cat] = cleaned
        return universe

    # Legacy flat format → assume Alpaca.
    for category in ("STOCK", "CRYPTO"):
        symbols = raw.get(category)
        if isinstance(symbols, list):
            universe[PROVIDER_ALPACA][category] = [
                str(s).upper().strip() for s in symbols if str(s).strip()
            ]
    return universe


def read_universe_file() -> ProviderUniverse:
    """Load the saved universe from disk in the provider-tagged schema."""

    if not UNIVERSE_FILE.exists():
        return _empty_universe()
    try:
        raw = json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty_universe()
    return _normalize_universe_payload(raw)


def write_universe_file(payload: ProviderUniverse | dict[str, Any]) -> None:
    """Persist the current universe to disk using the provider-tagged schema."""

    ensure_parent_dir(UNIVERSE_FILE)
    normalized = _normalize_universe_payload(payload)
    temp_path = UNIVERSE_FILE.with_name(f"{UNIVERSE_FILE.name}.{uuid4().hex}.tmp")
    temp_path.write_text(to_json(normalized), encoding="utf-8")
    temp_path.replace(UNIVERSE_FILE)


def universe_for_provider(universe: ProviderUniverse, provider: str) -> dict[str, list[str]]:
    """Return the per-category universe for a single provider."""

    return universe.get(provider) or {}


def merge_universe_categories(universe: ProviderUniverse) -> dict[str, list[str]]:
    """Flatten the provider universe into ``{category: [symbols]}``.

    Used by callers that don't care about which provider owns each symbol.
    """

    merged: dict[str, list[str]] = {}
    for provider in ALL_PROVIDERS:
        categories = universe.get(provider) or {}
        for category, symbols in categories.items():
            for symbol in symbols:
                merged.setdefault(category, []).append(symbol)
    return merged


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
