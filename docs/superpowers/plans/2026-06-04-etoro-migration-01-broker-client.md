# eToro Migration — Plan 1: Foundation & Broker Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the eToro broker layer — config, a rate limiter, an `instrument_map` cache table, and a fully unit-tested `EToroClient` HTTP client — as standalone new code that leaves the existing Alpaca tree green.

**Architecture:** All work is additive. New files (`clients/etoro_client.py`, `clients/etoro_rate_limiter.py`) and additive changes to `core/utils.py`, `core/db.py`, `backend/.env.example`. The existing Alpaca code, wiring, and tests are untouched; Alpaca is removed only in Plan 4 (cutover). `EToroClient` talks to eToro's REST API over an injectable `requests.Session` so every method is testable with a mocked session. It exposes normalized plain-dict return shapes (documented per method) that Plans 2–3 will consume.

**Tech Stack:** Python 3.11+, `requests` (already a dependency), `unittest` run under `pytest`, SQLite. Tests run from the `backend/` directory (e.g. `cd backend && python -m pytest`).

**eToro API facts (verified against their OpenAPI spec):**
- Base host `https://public-api.etoro.com`. v1 endpoints under `/api/v1`, order execution/info under `/api/v2`.
- Auth headers on **every** request: `x-api-key`, `x-user-key`, and a fresh `x-request-id` GUID (also the order idempotency key).
- Demo vs Real selected by a path segment (encoded per-endpoint in §Task 4).
- Rate limit: 60 GET requests/minute.

**Normalized return shapes used across this plan (define once, reuse):**
- **Position dict:** `{"position_id": str, "instrument_id": int, "symbol": str|None, "units": float, "open_rate": float, "amount": float, "is_buy": bool, "leverage": float, "stop_loss_rate": float|None, "take_profit_rate": float|None}`
- **Quote dict:** `{"bid_price": float|None, "ask_price": float|None, "bid_size": None, "ask_size": None}`
- **Bar dict:** `{"symbol": str, "timestamp": str (ISO-8601 UTC), "open": float, "high": float, "low": float, "close": float, "volume": float}`
- **Asset dict:** `{"symbol": str, "instrument_id": int, "category": str ("STOCK"|"CRYPTO"), "name": str, "tradable": bool}`
- **Open-order result dict:** `{"order_id": str, "reference_id": str, "position_id": str|None, "filled_price": float|None, "units": float|None}`

---

## File Structure

| File | Responsibility |
|---|---|
| `core/utils.py` (modify) | Add `PROVIDER_ETORO`, eToro `AppConfig` fields, `demo`/`etoro_enabled` properties, env loading. Additive — Alpaca fields stay. |
| `core/db.py` (modify) | Add `instrument_map` table + repository helpers. Additive. |
| `clients/etoro_rate_limiter.py` (create) | `RateLimiter` token-bucket, injectable clock/sleep for tests. |
| `clients/etoro_client.py` (create) | `EToroClient`: HTTP foundation, market data, instruments, account/portfolio, orders. |
| `backend/.env.example` (modify) | Add `ETORO_*` keys (additive). |
| `tests/test_etoro_rate_limiter.py` (create) | Unit tests for the limiter. |
| `tests/test_etoro_client.py` (create) | Unit tests for every `EToroClient` method against a mocked session. |
| `tests/test_etoro_config.py` (create) | Unit tests for eToro config loading + properties. |
| `tests/test_etoro_instruments_db.py` (create) | Unit tests for `instrument_map` helpers. |

---

## Task 1: eToro provider constant + config fields

**Files:**
- Modify: `core/utils.py`
- Test: `tests/test_etoro_config.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_etoro_config.py`:

```python
import os
import sys
import unittest
from types import ModuleType
from unittest.mock import patch

dotenv_stub = ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda: None
sys.modules.setdefault("dotenv", dotenv_stub)

from core.utils import AppConfig, PROVIDER_ETORO, load_config


class EtoroConfigTests(unittest.TestCase):
    def test_provider_constant(self):
        self.assertEqual(PROVIDER_ETORO, "etoro")

    def test_demo_property_defaults_true(self):
        config = AppConfig(
            openai_api_key="k",
            alpaca_api_key="",
            alpaca_secret_key="",
            alpaca_base_url="https://paper-api.alpaca.markets",
            etoro_api_key="app-key",
            etoro_user_key="user-key",
            etoro_account_type="demo",
        )
        self.assertTrue(config.demo)
        self.assertTrue(config.etoro_enabled)
        self.assertIn(PROVIDER_ETORO, config.active_providers())

    def test_real_account_type(self):
        config = AppConfig(
            openai_api_key="k",
            alpaca_api_key="",
            alpaca_secret_key="",
            alpaca_base_url="x",
            etoro_api_key="a",
            etoro_user_key="b",
            etoro_account_type="real",
        )
        self.assertFalse(config.demo)

    def test_load_config_reads_etoro_env(self):
        env = {
            "OPENAI_API_KEY": "o",
            "ETORO_API_KEY": "  app  ",
            "ETORO_USER_KEY": " user ",
            "ETORO_ACCOUNT_TYPE": "REAL",
            "ETORO_DEFAULT_LEVERAGE": "1",
            "ETORO_MIN_TRADE_AMOUNT": "50",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        self.assertEqual(config.etoro_api_key, "app")
        self.assertEqual(config.etoro_user_key, "user")
        self.assertEqual(config.etoro_account_type, "real")
        self.assertFalse(config.demo)
        self.assertEqual(config.etoro_default_leverage, 1)
        self.assertEqual(config.etoro_min_trade_amount, 50.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_etoro_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'PROVIDER_ETORO'`.

- [ ] **Step 3: Add the provider constant**

In `core/utils.py`, after line 23 (`ALL_PROVIDERS: tuple[str, ...] = (PROVIDER_ALPACA,)`), add:

```python
PROVIDER_ETORO = "etoro"
```

- [ ] **Step 4: Add eToro fields to `AppConfig`**

In `core/utils.py`, inside the `AppConfig` dataclass, immediately after the `account_currency: str = "USD"` line (currently line 112), add:

```python
    # --- eToro broker -------------------------------------------------------
    etoro_api_key: str = ""
    etoro_user_key: str = ""
    # "demo" (default, eToro paper account) or "real".
    etoro_account_type: str = "demo"
    etoro_default_leverage: int = 1
    # eToro enforces a per-position minimum investment (USD). Orders below
    # this are shrunk up to the minimum or skipped by the trade layer.
    etoro_min_trade_amount: float = 50.0
```

- [ ] **Step 5: Add `demo` and `etoro_enabled` properties**

In `core/utils.py`, after the `alpaca_enabled` property (currently ends line 124), add:

```python
    @property
    def demo(self) -> bool:
        return self.etoro_account_type.strip().lower() != "real"

    @property
    def etoro_enabled(self) -> bool:
        return bool(self.etoro_api_key and self.etoro_user_key)
```

- [ ] **Step 6: Register eToro in `active_providers`**

In `core/utils.py`, replace the body of `active_providers` (currently lines 126-132) with:

```python
    def active_providers(self) -> tuple[str, ...]:
        """Return the providers configured with credentials, in stable order."""

        active: list[str] = []
        if self.alpaca_enabled:
            active.append(PROVIDER_ALPACA)
        if self.etoro_enabled:
            active.append(PROVIDER_ETORO)
        return tuple(active)
```

- [ ] **Step 7: Load eToro env in `load_config`**

In `core/utils.py`, inside the `AppConfig(...)` constructor call in `load_config` (after the `account_currency=...` block that ends at line 214, before the closing `)`), add these keyword arguments:

```python
        etoro_api_key=os.getenv("ETORO_API_KEY", "").strip(),
        etoro_user_key=os.getenv("ETORO_USER_KEY", "").strip(),
        etoro_account_type=os.getenv("ETORO_ACCOUNT_TYPE", "demo").strip().lower() or "demo",
        etoro_default_leverage=max(1, int(os.getenv("ETORO_DEFAULT_LEVERAGE", "1"))),
        etoro_min_trade_amount=max(0.0, float(os.getenv("ETORO_MIN_TRADE_AMOUNT", "50"))),
```

- [ ] **Step 8: Add the new keys to the settings allowlist**

In `core/utils.py`, inside `SETTINGS_OVERRIDABLE_KEYS` (the frozenset at lines 28-47), add these entries to the set literal:

```python
        "etoro_min_trade_amount",
        "etoro_default_leverage",
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_etoro_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 10: Run the full suite to confirm nothing broke**

Run: `cd backend && python -m pytest -q`
Expected: all pre-existing tests still PASS.

- [ ] **Step 11: Commit**

```bash
git add backend/core/utils.py backend/tests/test_etoro_config.py
git commit -m "feat(etoro): add eToro provider constant and config fields"
```

---

## Task 2: `instrument_map` table + repository helpers

**Files:**
- Modify: `core/db.py`
- Test: `tests/test_etoro_instruments_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_etoro_instruments_db.py`:

```python
import tempfile
import unittest
from pathlib import Path

from core.db import (
    initialize_databases,
    upsert_instrument_mapping,
    get_instrument_mapping,
)


class InstrumentMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "market.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "trades.sqlite")
        initialize_databases(self.market_db, self.trades_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_then_get(self):
        upsert_instrument_mapping(
            self.market_db, "AAPL", 101, "STOCK", "Apple Inc", True
        )
        row = get_instrument_mapping(self.market_db, "aapl")
        self.assertIsNotNone(row)
        self.assertEqual(row["instrument_id"], 101)
        self.assertEqual(row["category"], "STOCK")
        self.assertEqual(row["symbol"], "AAPL")

    def test_upsert_is_idempotent_and_updates(self):
        upsert_instrument_mapping(self.market_db, "BTC", 100000, "CRYPTO", "Bitcoin", True)
        upsert_instrument_mapping(self.market_db, "BTC", 100000, "CRYPTO", "Bitcoin", False)
        row = get_instrument_mapping(self.market_db, "BTC")
        self.assertEqual(row["tradable"], 0)

    def test_get_missing_returns_none(self):
        self.assertIsNone(get_instrument_mapping(self.market_db, "NOPE"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_etoro_instruments_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'upsert_instrument_mapping'`.

- [ ] **Step 3: Add the table schema**

In `core/db.py`, after the `MARKET_SCHEMA` string (ends line 20), add:

```python
INSTRUMENT_MAP_SCHEMA = """
CREATE TABLE IF NOT EXISTS instrument_map (
    symbol TEXT PRIMARY KEY,
    instrument_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    display_name TEXT,
    tradable INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_instrument_map_id ON instrument_map(instrument_id);
"""
```

- [ ] **Step 4: Create the table on init**

In `core/db.py`, in `initialize_databases`, change the market-db block (currently lines 212-218) so the instrument-map schema is also executed:

```python
    market_conn = _connect(market_db_path)
    try:
        market_conn.executescript(MARKET_SCHEMA)
        market_conn.executescript(INSTRUMENT_MAP_SCHEMA)
        _migrate_legacy_ohlcv_table(market_conn)
        market_conn.commit()
    finally:
        market_conn.close()
```

- [ ] **Step 5: Add the repository helpers**

In `core/db.py`, at the end of the file, add:

```python
def upsert_instrument_mapping(
    db_path: str,
    symbol: str,
    instrument_id: int,
    category: str,
    display_name: str | None,
    tradable: bool,
) -> None:
    """Insert or update a symbol → eToro instrumentId mapping."""

    normalized = str(symbol).upper().strip()
    with db_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO instrument_map (symbol, instrument_id, category, display_name, tradable, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(symbol) DO UPDATE SET
                instrument_id = excluded.instrument_id,
                category = excluded.category,
                display_name = excluded.display_name,
                tradable = excluded.tradable,
                updated_at = CURRENT_TIMESTAMP
            """,
            (normalized, int(instrument_id), str(category).upper().strip(), display_name, 1 if tradable else 0),
        )


def get_instrument_mapping(db_path: str, symbol: str) -> dict[str, Any] | None:
    """Return the cached mapping row for a symbol, or None."""

    normalized = str(symbol).upper().strip()
    return fetch_one(
        db_path,
        "SELECT symbol, instrument_id, category, display_name, tradable FROM instrument_map WHERE symbol = ?",
        (normalized,),
    )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_etoro_instruments_db.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/core/db.py backend/tests/test_etoro_instruments_db.py
git commit -m "feat(etoro): add instrument_map table and repository helpers"
```

---

## Task 3: Rate limiter

**Files:**
- Create: `clients/etoro_rate_limiter.py`
- Test: `tests/test_etoro_rate_limiter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_etoro_rate_limiter.py`:

```python
import unittest

from clients.etoro_rate_limiter import RateLimiter


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class RateLimiterTests(unittest.TestCase):
    def test_allows_up_to_capacity_without_sleeping(self):
        clock = FakeClock()
        limiter = RateLimiter(max_calls=3, period=60.0, monotonic=clock.monotonic, sleep=clock.sleep)
        for _ in range(3):
            limiter.acquire()
        self.assertEqual(clock.slept, [])

    def test_blocks_when_capacity_exceeded(self):
        clock = FakeClock()
        limiter = RateLimiter(max_calls=2, period=60.0, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        limiter.acquire()
        limiter.acquire()  # third call must wait until the window rolls
        self.assertEqual(len(clock.slept), 1)
        self.assertAlmostEqual(clock.slept[0], 60.0)

    def test_window_slides(self):
        clock = FakeClock()
        limiter = RateLimiter(max_calls=2, period=60.0, monotonic=clock.monotonic, sleep=clock.sleep)
        limiter.acquire()
        limiter.acquire()
        clock.now += 61.0  # both timestamps expire
        limiter.acquire()
        self.assertEqual(clock.slept, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_etoro_rate_limiter.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clients.etoro_rate_limiter'`.

- [ ] **Step 3: Implement the limiter**

Create `clients/etoro_rate_limiter.py`:

```python
"""A simple sliding-window rate limiter for the eToro REST client."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class RateLimiter:
    """Sliding-window limiter: at most ``max_calls`` acquisitions per ``period`` seconds.

    ``monotonic`` and ``sleep`` are injectable so tests can drive a fake clock.
    Thread-safe so the scheduler's monitor loop and signal jobs can share one.
    """

    def __init__(
        self,
        max_calls: int,
        period: float,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._max_calls = max(1, int(max_calls))
        self._period = float(period)
        self._monotonic = monotonic
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._monotonic()
            self._evict(now)
            if len(self._calls) >= self._max_calls:
                wait = self._period - (now - self._calls[0])
                if wait > 0:
                    self._sleep(wait)
                now = self._monotonic()
                self._evict(now)
            self._calls.append(now)

    def _evict(self, now: float) -> None:
        while self._calls and (now - self._calls[0]) >= self._period:
            self._calls.popleft()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_etoro_rate_limiter.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_rate_limiter.py backend/tests/test_etoro_rate_limiter.py
git commit -m "feat(etoro): add sliding-window rate limiter"
```

---

## Task 4: `EToroClient` HTTP foundation

**Files:**
- Create: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_etoro_client.py`:

```python
import logging
import unittest
from unittest.mock import Mock

from core.utils import AppConfig
from clients.etoro_client import EToroClient, EToroAPIError


def make_config(account_type="demo"):
    return AppConfig(
        openai_api_key="k",
        alpaca_api_key="",
        alpaca_secret_key="",
        alpaca_base_url="x",
        etoro_api_key="app-key",
        etoro_user_key="user-key",
        etoro_account_type=account_type,
    )


def make_response(status_code=200, json_body=None):
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = "" if json_body is None else str(json_body)
    return resp


def make_client(account_type="demo"):
    session = Mock()
    client = EToroClient(
        make_config(account_type),
        logging.getLogger("test"),
        session=session,
        rate_limiter=Mock(),  # no-op limiter in tests
    )
    return client, session


class EToroFoundationTests(unittest.TestCase):
    def test_headers_include_auth_and_request_id(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"ok": True})
        client._request("GET", "/api/v1/me")
        _, kwargs = session.request.call_args
        headers = kwargs["headers"]
        self.assertEqual(headers["x-api-key"], "app-key")
        self.assertEqual(headers["x-user-key"], "user-key")
        self.assertTrue(headers["x-request-id"])  # non-empty GUID

    def test_each_request_gets_a_unique_request_id(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {})
        client._request("GET", "/a")
        client._request("GET", "/b")
        first = session.request.call_args_list[0].kwargs["headers"]["x-request-id"]
        second = session.request.call_args_list[1].kwargs["headers"]["x-request-id"]
        self.assertNotEqual(first, second)

    def test_4xx_raises_and_is_not_retried(self):
        client, session = make_client()
        session.request.return_value = make_response(400, {"error": "bad"})
        with self.assertRaises(EToroAPIError):
            client._request("POST", "/x", json_body={"a": 1})
        self.assertEqual(session.request.call_count, 1)  # fail-fast, no retry

    def test_demo_vs_real_mode(self):
        demo, _ = make_client("demo")
        real, _ = make_client("real")
        self.assertEqual(demo._mode_segment(), "demo/")
        self.assertEqual(real._mode_segment(), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_etoro_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'clients.etoro_client'`.

- [ ] **Step 3: Implement the client foundation**

Create `clients/etoro_client.py`:

```python
"""eToro Public REST API client.

Talks to https://public-api.etoro.com over an injectable ``requests.Session``.
Exposes normalized plain-dict shapes (see the module docstring in the plan)
so the trade and data layers stay broker-agnostic.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import requests

from clients.etoro_rate_limiter import RateLimiter
from core.utils import AppConfig, retry

ETORO_BASE_URL = "https://public-api.etoro.com"


class EToroAPIError(Exception):
    """Raised when the eToro API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(f"eToro API {status_code}: {message}")
        self.status_code = status_code


def _is_transient_etoro_error(exc: BaseException) -> bool:
    """Retry only 5xx / network-class errors; fail fast on 4xx."""

    if isinstance(exc, EToroAPIError):
        return not (400 <= exc.status_code < 500)
    if isinstance(exc, requests.RequestException):
        return True
    return True


class EToroClient:
    """Thin wrapper around eToro's REST API with auth, retries and rate limiting."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        session: requests.Session | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.config = config
        self.logger = logger.getChild("etoro")
        self.session = session or requests.Session()
        self.rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter(max_calls=60, period=60.0)

    # --- low-level HTTP -----------------------------------------------------

    def _mode_segment(self) -> str:
        """Path segment inserted for demo accounts (e.g. 'trading/info/<seg>portfolio')."""

        return "demo/" if self.config.demo else ""

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.config.etoro_api_key,
            "x-user-key": self.config.etoro_user_key,
            "x-request-id": str(uuid4()),
            "Content-Type": "application/json",
        }

    @retry(should_retry=_is_transient_etoro_error)
    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        if method.upper() == "GET":
            self.rate_limiter.acquire()
        url = f"{ETORO_BASE_URL}{path}"
        response = self.session.request(
            method.upper(),
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
            timeout=30,
        )
        status = int(getattr(response, "status_code", 0))
        if status >= 400:
            raise EToroAPIError(status, getattr(response, "text", "") or "request failed")
        try:
            return response.json()
        except ValueError:
            return {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_etoro_client.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add EToroClient HTTP foundation (auth, retries, rate limit)"
```

---

## Task 5: Market data — rates and candles

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append a test class)

eToro endpoints:
- Rates: `GET /api/v1/market-data/instruments/rates?instrumentIds=<csv>` → `{"rates": [{"instrumentID", "ask", "bid", "lastExecution"}]}`
- Candles: `GET /api/v1/market-data/instruments/{instrumentId}/history/candles/desc/OneDay/{count}` → `{"candles": [{"instrumentId", "candles": [{"fromDate","open","high","low","close","volume"}]}]}`

This task fetches by **instrumentId**. Symbol→instrumentId resolution is added in Task 6; these methods accept an `instrument_id` and a `symbol` label for the returned bar rows.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
class EToroMarketDataTests(unittest.TestCase):
    def test_get_rate_returns_bid_ask(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {
            "rates": [{"instrumentID": 101, "ask": 10.5, "bid": 10.4, "lastExecution": 10.45}]
        })
        quote = client.get_rate_by_instrument(101)
        self.assertEqual(quote["ask_price"], 10.5)
        self.assertEqual(quote["bid_price"], 10.4)
        self.assertEqual(quote["last_price"], 10.45)

    def test_get_candles_normalizes_bars(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {
            "candles": [{
                "instrumentId": 101,
                "candles": [
                    {"fromDate": "2026-01-01T00:00:00Z", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100.0},
                    {"fromDate": "2026-01-02T00:00:00Z", "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 200.0},
                ],
            }]
        })
        bars = client.get_candles_by_instrument(101, "AAPL", count=2)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0]["symbol"], "AAPL")
        self.assertEqual(bars[0]["close"], 1.5)
        self.assertTrue(bars[0]["timestamp"].startswith("2026-01-01"))
        # ascending order (oldest first)
        self.assertLess(bars[0]["timestamp"], bars[1]["timestamp"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_etoro_client.py::EToroMarketDataTests -v`
Expected: FAIL with `AttributeError: 'EToroClient' object has no attribute 'get_rate_by_instrument'`.

- [ ] **Step 3: Implement the market-data methods**

Append to the `EToroClient` class in `clients/etoro_client.py`:

```python
    # --- market data --------------------------------------------------------

    def get_rate_by_instrument(self, instrument_id: int) -> dict[str, float | None]:
        payload = self._request(
            "GET",
            "/api/v1/market-data/instruments/rates",
            params={"instrumentIds": str(int(instrument_id))},
        )
        rates = payload.get("rates") or []
        if not rates:
            raise EToroAPIError(404, f"no rate for instrument {instrument_id}")
        row = rates[0]
        ask = float(row.get("ask") or 0.0) or None
        bid = float(row.get("bid") or 0.0) or None
        last = float(row.get("lastExecution") or 0.0) or None
        return {"ask_price": ask, "bid_price": bid, "last_price": last}

    def get_candles_by_instrument(
        self,
        instrument_id: int,
        symbol: str,
        count: int = 365,
        interval: str = "OneDay",
    ) -> list[dict[str, Any]]:
        path = (
            f"/api/v1/market-data/instruments/{int(instrument_id)}"
            f"/history/candles/desc/{interval}/{int(count)}"
        )
        payload = self._request("GET", path)
        groups = payload.get("candles") or []
        rows: list[dict[str, Any]] = []
        for group in groups:
            for candle in group.get("candles") or []:
                rows.append(
                    {
                        "symbol": str(symbol).upper().strip(),
                        "timestamp": str(candle.get("fromDate")),
                        "open": float(candle.get("open")),
                        "high": float(candle.get("high")),
                        "low": float(candle.get("low")),
                        "close": float(candle.get("close")),
                        "volume": float(candle.get("volume") or 0.0),
                    }
                )
        rows.sort(key=lambda r: r["timestamp"])
        return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_etoro_client.py::EToroMarketDataTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add rates and candles market-data methods"
```

---

## Task 6: Instruments — resolution and listing

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append a test class)

eToro endpoints:
- By symbol: `GET /api/v1/instruments/{symbol}` → `{"instrumentId", "symbol", "instrumentType", "isCurrentlyTradable", "isBuyEnabled", "displayname"}` (single instrument).
- By type: `GET /api/v1/market-data/instruments?instrumentTypeIds=<id>` → `{"instruments": [{...}]}`.

The client maps eToro `instrumentType` strings to the bot's `"STOCK"`/`"CRYPTO"` categories.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
class EToroInstrumentTests(unittest.TestCase):
    def test_resolve_instrument_by_symbol(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {
            "instrumentId": 101,
            "symbol": "AAPL",
            "instrumentType": "Stocks",
            "displayname": "Apple Inc",
            "isCurrentlyTradable": True,
            "isBuyEnabled": True,
        })
        asset = client.resolve_instrument("aapl")
        self.assertEqual(asset["instrument_id"], 101)
        self.assertEqual(asset["symbol"], "AAPL")
        self.assertEqual(asset["category"], "STOCK")
        self.assertTrue(asset["tradable"])

    def test_resolve_instrument_crypto_category(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {
            "instrumentId": 100000, "symbol": "BTC", "instrumentType": "Crypto",
            "displayname": "Bitcoin", "isCurrentlyTradable": True, "isBuyEnabled": True,
        })
        asset = client.resolve_instrument("BTC")
        self.assertEqual(asset["category"], "CRYPTO")

    def test_resolve_missing_returns_none(self):
        client, session = make_client()
        session.request.return_value = make_response(404, {})
        self.assertIsNone(client.resolve_instrument("NOPE"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_etoro_client.py::EToroInstrumentTests -v`
Expected: FAIL with `AttributeError: ... 'resolve_instrument'`.

- [ ] **Step 3: Implement instrument resolution**

Append to the `EToroClient` class in `clients/etoro_client.py`:

```python
    # --- instruments --------------------------------------------------------

    _CRYPTO_TYPE_HINTS = ("crypto",)

    def _category_for_type(self, instrument_type: str) -> str:
        text = str(instrument_type or "").lower()
        if any(hint in text for hint in self._CRYPTO_TYPE_HINTS):
            return "CRYPTO"
        return "STOCK"

    def resolve_instrument(self, symbol: str) -> dict[str, Any] | None:
        """Look up a single instrument by ticker symbol. Returns an Asset dict or None."""

        normalized = str(symbol).upper().strip()
        try:
            payload = self._request("GET", f"/api/v1/instruments/{normalized}")
        except EToroAPIError as exc:
            if exc.status_code == 404:
                return None
            raise
        if not payload or payload.get("instrumentId") is None:
            return None
        return {
            "symbol": str(payload.get("symbol") or normalized).upper().strip(),
            "instrument_id": int(payload["instrumentId"]),
            "category": self._category_for_type(payload.get("instrumentType", "")),
            "name": str(payload.get("displayname") or ""),
            "tradable": bool(payload.get("isCurrentlyTradable")) and bool(payload.get("isBuyEnabled", True)),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_etoro_client.py::EToroInstrumentTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add instrument resolution by symbol"
```

---

## Task 7: Account & portfolio

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append a test class)

eToro endpoints (mode-aware):
- Portfolio: `GET /api/v1/trading/info/{seg}portfolio` where `{seg}` is `""` (real) or `"demo/"` → `{"clientPortfolio": {"credit": float, "positions": [Position], "orders": [...]}}`.
- Equity model (USD): `available_cash = credit − Σ(pending order amounts)`; `equity = credit + Σ(position units × latest bid)`. With this project's client-side emulation there are no broker pending orders, so `available_cash == credit` in practice; the subtraction is kept for safety.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
class EToroAccountTests(unittest.TestCase):
    def _portfolio_response(self):
        return make_response(200, {
            "clientPortfolio": {
                "credit": 1000.0,
                "orders": [],
                "positions": [
                    {"positionID": "p1", "instrumentID": 101, "units": 2.0,
                     "openRate": 50.0, "amount": 100.0, "isBuy": True, "leverage": 1,
                     "stopLossRate": 45.0, "takeProfitRate": 60.0},
                ],
            }
        })

    def test_get_available_cash(self):
        client, session = make_client()
        session.request.return_value = self._portfolio_response()
        self.assertEqual(client.get_available_cash(), 1000.0)

    def test_list_open_positions_normalizes(self):
        client, session = make_client()
        session.request.return_value = self._portfolio_response()
        positions = client.list_open_positions()
        self.assertEqual(len(positions), 1)
        p = positions[0]
        self.assertEqual(p["position_id"], "p1")
        self.assertEqual(p["instrument_id"], 101)
        self.assertEqual(p["units"], 2.0)
        self.assertEqual(p["open_rate"], 50.0)
        self.assertTrue(p["is_buy"])

    def test_account_equity_adds_market_value(self):
        client, session = make_client()
        # First call: portfolio. Second call: rates for held instruments.
        session.request.side_effect = [
            self._portfolio_response(),
            make_response(200, {"rates": [{"instrumentID": 101, "bid": 55.0, "ask": 55.2, "lastExecution": 55.1}]}),
        ]
        equity = client.get_account_equity()
        # credit 1000 + 2 units * 55.0 bid = 1110
        self.assertEqual(equity, 1110.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_etoro_client.py::EToroAccountTests -v`
Expected: FAIL with `AttributeError: ... 'get_available_cash'`.

- [ ] **Step 3: Implement account/portfolio methods**

Append to the `EToroClient` class in `clients/etoro_client.py`:

```python
    # --- account & portfolio ------------------------------------------------

    def _portfolio(self) -> dict[str, Any]:
        path = f"/api/v1/trading/info/{self._mode_segment()}portfolio"
        payload = self._request("GET", path)
        return payload.get("clientPortfolio") or {}

    @staticmethod
    def _normalize_position(raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "position_id": str(raw.get("positionID")),
            "instrument_id": int(raw.get("instrumentID")),
            "symbol": None,
            "units": float(raw.get("units") or 0.0),
            "open_rate": float(raw.get("openRate") or 0.0),
            "amount": float(raw.get("amount") or 0.0),
            "is_buy": bool(raw.get("isBuy", True)),
            "leverage": float(raw.get("leverage") or 1.0),
            "stop_loss_rate": (float(raw["stopLossRate"]) if raw.get("stopLossRate") is not None else None),
            "take_profit_rate": (float(raw["takeProfitRate"]) if raw.get("takeProfitRate") is not None else None),
        }

    def list_open_positions(self) -> list[dict[str, Any]]:
        portfolio = self._portfolio()
        return [self._normalize_position(p) for p in (portfolio.get("positions") or [])]

    def get_available_cash(self) -> float:
        portfolio = self._portfolio()
        credit = float(portfolio.get("credit") or 0.0)
        pending = sum(float(o.get("amount") or 0.0) for o in (portfolio.get("orders") or []))
        return max(0.0, credit - pending)

    def get_account_equity(self) -> float:
        portfolio = self._portfolio()
        credit = float(portfolio.get("credit") or 0.0)
        positions = [self._normalize_position(p) for p in (portfolio.get("positions") or [])]
        if not positions:
            return credit
        instrument_ids = ",".join(str(p["instrument_id"]) for p in positions)
        rates_payload = self._request(
            "GET",
            "/api/v1/market-data/instruments/rates",
            params={"instrumentIds": instrument_ids},
        )
        by_id = {int(r.get("instrumentID")): r for r in (rates_payload.get("rates") or [])}
        market_value = 0.0
        for position in positions:
            rate = by_id.get(position["instrument_id"], {})
            price = float(rate.get("bid") or rate.get("lastExecution") or position["open_rate"])
            market_value += position["units"] * price
        return credit + market_value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_etoro_client.py::EToroAccountTests -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add account cash, equity and positions methods"
```

---

## Task 8: Orders — open, close, order info

**Files:**
- Modify: `clients/etoro_client.py`
- Test: `tests/test_etoro_client.py` (append a test class)

eToro endpoints (mode-aware), all POST to `/api/v2/trading/execution/{seg}orders`:
- **Open:** body `{action:"open", transaction:"buy", symbol, instrumentId, orderType:"mkt", amount, orderCurrency:"usd", leverage, stopLossRate, takeProfitRate, stopLossType:"fixed"}`.
- **Close:** body `{action:"close", positionIds:[<id>]}`. Partial close uses `units`.
- **Order info / fill read-back:** `GET /api/v2/trading/info/{seg}orders:lookup?orderId=<id>` → resolves the resulting `positionId`, `openRate`, `units`.

(The lookup response field names are not fully specified in the public OpenAPI; `get_order_info` returns the raw payload plus best-effort extracted `position_id`/`filled_price`/`units`, defaulting to `None` when absent so callers fall back to a portfolio scan — this fallback is wired in Plan 3.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_etoro_client.py`:

```python
class EToroOrderTests(unittest.TestCase):
    def test_open_market_position_builds_correct_body(self):
        client, session = make_client("demo")
        session.request.return_value = make_response(200, {"orderId": "o1", "referenceId": "ref-1"})
        result = client.open_market_position(
            instrument_id=101, symbol="AAPL", amount_usd=250.0,
            stop_loss_rate=90.0, take_profit_rate=130.0, leverage=1,
        )
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/api/v2/trading/execution/demo/orders"))
        body = kwargs["json"]
        self.assertEqual(body["action"], "open")
        self.assertEqual(body["transaction"], "buy")
        self.assertEqual(body["instrumentId"], 101)
        self.assertEqual(body["orderType"], "mkt")
        self.assertEqual(body["amount"], 250.0)
        self.assertEqual(body["orderCurrency"], "usd")
        self.assertEqual(body["leverage"], 1)
        self.assertEqual(body["stopLossRate"], 90.0)
        self.assertEqual(body["takeProfitRate"], 130.0)
        self.assertEqual(body["stopLossType"], "fixed")
        self.assertEqual(result["order_id"], "o1")
        self.assertEqual(result["reference_id"], "ref-1")

    def test_close_position_market_builds_body(self):
        client, session = make_client("real")
        session.request.return_value = make_response(200, {"orderId": "c1"})
        result = client.close_position_market("p1")
        args, kwargs = session.request.call_args
        self.assertTrue(args[1].endswith("/api/v2/trading/execution/orders"))
        body = kwargs["json"]
        self.assertEqual(body["action"], "close")
        self.assertEqual(body["positionIds"], ["p1"])
        self.assertEqual(result["order_id"], "c1")

    def test_open_uses_request_id_as_idempotency_key(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"orderId": "o1"})
        result = client.open_market_position(
            instrument_id=101, symbol="AAPL", amount_usd=100.0,
            stop_loss_rate=90.0, take_profit_rate=130.0, leverage=1,
        )
        sent_request_id = session.request.call_args.kwargs["headers"]["x-request-id"]
        self.assertEqual(result["reference_id"], "ref-1") if False else None
        self.assertEqual(result["request_id"], sent_request_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_etoro_client.py::EToroOrderTests -v`
Expected: FAIL with `AttributeError: ... 'open_market_position'`.

- [ ] **Step 3: Implement order methods**

Append to the `EToroClient` class in `clients/etoro_client.py`:

```python
    # --- orders -------------------------------------------------------------

    def _orders_path(self) -> str:
        return f"/api/v2/trading/execution/{self._mode_segment()}orders"

    def open_market_position(
        self,
        instrument_id: int,
        symbol: str,
        amount_usd: float,
        stop_loss_rate: float,
        take_profit_rate: float,
        leverage: int = 1,
    ) -> dict[str, Any]:
        request_id = str(uuid4())
        body = {
            "action": "open",
            "transaction": "buy",
            "symbol": str(symbol).upper().strip(),
            "instrumentId": int(instrument_id),
            "orderType": "mkt",
            "leverage": int(leverage),
            "amount": float(amount_usd),
            "orderCurrency": "usd",
            "stopLossRate": float(stop_loss_rate),
            "takeProfitRate": float(take_profit_rate),
            "stopLossType": "fixed",
        }
        payload = self._request_with_id("POST", self._orders_path(), request_id, json_body=body)
        return {
            "order_id": str(payload.get("orderId")) if payload.get("orderId") is not None else None,
            "reference_id": str(payload.get("referenceId")) if payload.get("referenceId") is not None else None,
            "request_id": request_id,
            "position_id": str(payload.get("positionId")) if payload.get("positionId") is not None else None,
            "raw": payload,
        }

    def close_position_market(self, position_id: str, units: float | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"action": "close", "positionIds": [str(position_id)]}
        if units is not None:
            body["units"] = float(units)
        payload = self._request("POST", self._orders_path(), json_body=body)
        return {
            "order_id": str(payload.get("orderId")) if payload.get("orderId") is not None else None,
            "raw": payload,
        }

    def get_order_info(self, order_id: str) -> dict[str, Any]:
        path = f"/api/v2/trading/info/{self._mode_segment()}orders:lookup"
        payload = self._request("GET", path, params={"orderId": str(order_id)})
        position_id = payload.get("positionId")
        return {
            "position_id": str(position_id) if position_id is not None else None,
            "filled_price": (float(payload["openRate"]) if payload.get("openRate") is not None else None),
            "units": (float(payload["units"]) if payload.get("units") is not None else None),
            "raw": payload,
        }
```

Then add the `_request_with_id` helper (lets the open call reuse one GUID as both header and returned idempotency key). Add it right after `_request`:

```python
    @retry(should_retry=_is_transient_etoro_error)
    def _request_with_id(
        self,
        method: str,
        path: str,
        request_id: str,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers = self._headers()
        headers["x-request-id"] = request_id
        url = f"{ETORO_BASE_URL}{path}"
        response = self.session.request(
            method.upper(), url, headers=headers, json=json_body, timeout=30
        )
        status = int(getattr(response, "status_code", 0))
        if status >= 400:
            raise EToroAPIError(status, getattr(response, "text", "") or "request failed")
        try:
            return response.json()
        except ValueError:
            return {}
```

- [ ] **Step 4: Fix the idempotency test assertion**

The test's third case asserts `result["request_id"]` equals the sent header. Remove the dead `if False` line that was a placeholder guard and keep only the real assertions:

```python
    def test_open_uses_request_id_as_idempotency_key(self):
        client, session = make_client()
        session.request.return_value = make_response(200, {"orderId": "o1"})
        result = client.open_market_position(
            instrument_id=101, symbol="AAPL", amount_usd=100.0,
            stop_loss_rate=90.0, take_profit_rate=130.0, leverage=1,
        )
        sent_request_id = session.request.call_args.kwargs["headers"]["x-request-id"]
        self.assertEqual(result["request_id"], sent_request_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_etoro_client.py::EToroOrderTests -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the whole eToro client suite**

Run: `cd backend && python -m pytest tests/test_etoro_client.py -v`
Expected: PASS (all classes).

- [ ] **Step 7: Commit**

```bash
git add backend/clients/etoro_client.py backend/tests/test_etoro_client.py
git commit -m "feat(etoro): add open/close/order-info order methods"
```

---

## Task 9: `.env.example` keys (additive)

**Files:**
- Modify: `backend/.env.example`

- [ ] **Step 1: Add the eToro block**

In `backend/.env.example`, after the existing `ALPACA_MAX_NOTIONAL_PER_ORDER=200000` line, add:

```bash

# --- eToro broker ----------------------------------------------------------
# Public API key (identifies the application) and User key (identifies your
# eToro account). Both required. Get them from the eToro API portal.
ETORO_API_KEY=your_etoro_api_key
ETORO_USER_KEY=your_etoro_user_key
# "demo" (eToro paper account, default) or "real" (live money).
ETORO_ACCOUNT_TYPE=demo
# Always 1 for unleveraged real-asset positions.
ETORO_DEFAULT_LEVERAGE=1
# eToro's per-position minimum investment in USD.
ETORO_MIN_TRADE_AMOUNT=50
```

- [ ] **Step 2: Verify**

Run: `grep -c ETORO_ backend/.env.example`
Expected: `5`.

- [ ] **Step 3: Commit**

```bash
git add backend/.env.example
git commit -m "docs(etoro): add ETORO_* keys to .env.example"
```

---

## Final verification

- [ ] **Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS (pre-existing Alpaca tests + new eToro tests). No Alpaca code was modified, so the tree is green and shippable.

---

## Self-Review (completed during planning)

- **Spec coverage (Plan 1 scope):** config replacement fields (§5.5) — Tasks 1, 9 ✓ (additive; Alpaca removal deferred to Plan 4 to keep the tree green). `EToroClient` HTTP/auth/rate-limit/retries (§5.1) — Tasks 3, 4 ✓. Market data rates+candles (§5.1) — Task 5 ✓. Instrument resolution (§5.1, §5.2) — Task 6 ✓; `instrument_map` table (§5.2, §5.6) — Task 2 ✓. Account/equity/positions (§5.1) — Task 7 ✓. Orders open/close/info (§5.1, §5.3, §5.4) — Task 8 ✓. Tests (§7) — every task is TDD ✓.
- **Deferred to later plans (by design):** symbol→instrumentId caching wired through `instrument_map` and `list_assets` by type (Plan 2); market-data/universe rewiring (Plan 2); trade-lifecycle emulated entry/exit (Plan 3); Alpaca removal, API/scheduler wiring, fresh DB schema, demo integration (Plan 4).
- **Placeholder scan:** none. The only `if False` artifact in a draft test is explicitly removed in Task 8 Step 4.
- **Type consistency:** normalized dict shapes are declared in the header and used identically across Tasks 5–8 (`position_id`, `instrument_id`, `open_rate`, `bid_price`/`ask_price`, bar keys). `_mode_segment()`, `_request()`, `_request_with_id()`, `_orders_path()`, `_portfolio()` names are consistent across tasks.
