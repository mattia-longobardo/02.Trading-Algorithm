"""Shared utilities and configuration helpers."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

from dotenv import load_dotenv

F = TypeVar("F", bound=Callable[..., Any])
BASE_DIR = Path(__file__).resolve().parent
UNIVERSE_FILE = BASE_DIR / "data/universe.json"


@dataclass(slots=True)
class AppConfig:
    """Application configuration loaded from environment variables."""

    openai_api_key: str
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str
    max_open_trades_stock: int = 3
    max_open_trades_crypto: int = 3
    weekly_universe_stocks: int = 5
    weekly_universe_crypto: int = 5
    currency: str = "EUR"
    strategy_horizon_days_min: int = 90
    strategy_horizon_days_max: int = 120
    log_profile: str = "PRODUCTION"
    log_level: str = "INFO"
    log_file: str = "logs/trading_bot.log"
    universe_log_file: str = "logs/universe_candidates.log"
    db_market_data: str = "data/market_data.sqlite"
    db_trades: str = "data/trades.sqlite"
    lock_file: str = "run/trading_scheduler.lock"

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
        max_open_trades_stock=int(os.getenv("MAX_OPEN_TRADES_STOCK", "3")),
        max_open_trades_crypto=int(os.getenv("MAX_OPEN_TRADES_CRYPTO", "3")),
        weekly_universe_stocks=int(os.getenv("WEEKLY_UNIVERSE_STOCKS", "5")),
        weekly_universe_crypto=int(os.getenv("WEEKLY_UNIVERSE_CRYPTO", "5")),
        currency=os.getenv("CURRENCY", "EUR").upper(),
        strategy_horizon_days_min=int(os.getenv("STRATEGY_HORIZON_DAYS_MIN", "90")),
        strategy_horizon_days_max=int(os.getenv("STRATEGY_HORIZON_DAYS_MAX", "120")),
        log_profile=os.getenv("LOG_PROFILE", "PRODUCTION").upper(),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_file=os.getenv("LOG_FILE", "logs/trading_bot.log"),
        universe_log_file=os.getenv("UNIVERSE_LOG_FILE", "logs/universe_candidates.log"),
        db_market_data=os.getenv("DB_MARKET_DATA", "data/market_data.sqlite"),
        db_trades=os.getenv("DB_TRADES", "data/trades.sqlite"),
        lock_file=os.getenv("LOCK_FILE", "run/trading_scheduler.lock"),
    )
    config.log_file = resolve_runtime_path(config.log_file)
    config.universe_log_file = resolve_runtime_path(config.universe_log_file)
    config.db_market_data = resolve_runtime_path(config.db_market_data)
    config.db_trades = resolve_runtime_path(config.db_trades)
    config.lock_file = resolve_runtime_path(config.lock_file)
    ensure_parent_dir(config.log_file)
    ensure_parent_dir(config.universe_log_file)
    ensure_parent_dir(config.db_market_data)
    ensure_parent_dir(config.db_trades)
    ensure_parent_dir(config.lock_file)
    ensure_parent_dir(UNIVERSE_FILE)
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


def trim_ohlcv_payload(rows: list[dict[str, Any]], max_rows: int = 600) -> list[dict[str, Any]]:
    """Reduce token usage while still giving the model long context."""

    if len(rows) <= max_rows:
        return rows
    return rows[:120] + rows[-480:]


def to_json(data: Any) -> str:
    """Serialize data in a stable JSON format."""

    return json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True)


def read_universe_file() -> dict[str, list[str]]:
    """Load the saved universe from disk."""

    if not UNIVERSE_FILE.exists():
        return {"STOCK": [], "CRYPTO": []}
    return json.loads(UNIVERSE_FILE.read_text(encoding="utf-8"))


def write_universe_file(payload: dict[str, list[str]]) -> None:
    """Persist the current universe to disk."""

    ensure_parent_dir(UNIVERSE_FILE)
    UNIVERSE_FILE.write_text(to_json(payload), encoding="utf-8")


def write_json_file(file_path: str | Path, payload: Any) -> None:
    """Persist arbitrary JSON payloads to disk."""

    ensure_parent_dir(file_path)
    Path(file_path).write_text(to_json(payload), encoding="utf-8")


def market_data_start(first_download: bool) -> datetime:
    """Choose the backfill start date for market data downloads."""

    now = utc_now()
    if first_download:
        return now - timedelta(days=365 * 2)
    return now - timedelta(days=7)
