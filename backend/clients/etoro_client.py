"""eToro Public REST API client.

Talks to https://public-api.etoro.com over an injectable ``requests.Session``.
Exposes normalized plain-dict shapes so the trade and data layers stay
broker-agnostic:

- Position dict: {"position_id", "instrument_id", "symbol", "units",
  "open_rate", "amount", "is_buy", "leverage", "stop_loss_rate",
  "take_profit_rate"}
- Quote dict: {"bid_price", "ask_price", "last_price"}
- Bar dict: {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
- Asset dict: {"symbol", "instrument_id", "category", "name", "tradable"}
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

import requests

from clients.etoro_rate_limiter import RateLimiter
from core.db import get_instrument_mapping, upsert_instrument_mapping
from core.utils import AppConfig, parse_datetime, retry, utc_now

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
        self._exchange_cache: dict[int, str] | None = None

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
        return self._perform_request(method, path, params=params, json_body=json_body)

    def _perform_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if method.upper() == "GET":
            self.rate_limiter.acquire()
        url = f"{ETORO_BASE_URL}{path}"
        response = self.session.request(
            method.upper(),
            url,
            headers=headers or self._headers(),
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

    @retry(should_retry=_is_transient_etoro_error)
    def _request_or_none_on_404(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any | None:
        try:
            return self._perform_request(method, path, params=params, json_body=json_body)
        except EToroAPIError as exc:
            if exc.status_code == 404:
                return None
            raise

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
        return self._perform_request(method, path, headers=headers, json_body=json_body)

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

    def is_market_open(self, instrument_id: int, *, max_staleness_minutes: float = 15.0) -> bool:
        """True if the instrument has a fresh live quote (i.e. its market is open).

        eToro does not expose a reliable per-instrument market-open boolean, but a
        closed exchange freezes the rate at the last close, so the quote ``date``
        going stale is a robust, exchange-agnostic proxy (handles holidays/DST on
        its own). Crypto rates tick 24/7 and are always fresh. Fails *open*
        (returns True) on any error so a transient quote failure never blocks
        trading — the gate only suppresses entries when the market is provably
        closed.
        """
        try:
            payload = self._request(
                "GET",
                f"/api/v1/market-data/instruments/rates?instrumentIds={int(instrument_id)}",
            )
            rows = payload.get("rates") or []
            if not rows:
                return True
            quote_dt = parse_datetime(rows[0].get("date"))
            if quote_dt is None:
                return True
            age_minutes = (utc_now() - quote_dt).total_seconds() / 60.0
            return age_minutes <= max_staleness_minutes
        except Exception:
            self.logger.debug(
                "is_market_open: quote check failed for %s; assuming open", instrument_id, exc_info=True
            )
            return True

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

    _MAX_DAILY_CANDLES = 1000

    def _candles_count_for_start(self, start: Any) -> int:
        start_dt = parse_datetime(start) if isinstance(start, str) else start
        if start_dt is None:
            return self._MAX_DAILY_CANDLES
        days = (utc_now() - start_dt).days + 2
        return max(1, min(self._MAX_DAILY_CANDLES, days))

    def get_bars(self, symbol: str, category: str, start: Any, end: Any = None) -> list[dict[str, Any]]:
        normalized = str(symbol).upper().strip()
        instrument_id = self.instrument_id_for_symbol(normalized)
        if instrument_id is None:
            return []
        count = self._candles_count_for_start(start)
        rows = self.get_candles_by_instrument(instrument_id, normalized, count=count)
        start_dt = parse_datetime(start) if isinstance(start, str) else start
        end_dt = parse_datetime(end) if isinstance(end, str) else end
        out: list[dict[str, Any]] = []
        for row in rows:
            ts = parse_datetime(row["timestamp"])
            if ts is None:
                continue
            if start_dt is not None and ts < start_dt:
                continue
            if end_dt is not None and ts > end_dt:
                continue
            out.append(row)
        return out

    def get_multi_bars(
        self, symbols: list[str], category: str, start: Any, end: Any = None
    ) -> dict[str, list[dict[str, Any]]]:
        out: dict[str, list[dict[str, Any]]] = {}
        for symbol in symbols:
            normalized = str(symbol).upper().strip()
            if not normalized:
                continue
            try:
                out[normalized] = self.get_bars(normalized, category, start, end)
            except Exception:
                self.logger.exception("eToro get_bars failed for %s", normalized)
                out[normalized] = []
        return out

    def _resolve_or_raise(self, symbol: str) -> int:
        instrument_id = self.instrument_id_for_symbol(symbol)
        if instrument_id is None:
            raise EToroAPIError(404, f"unknown instrument for symbol {symbol}")
        return instrument_id

    def get_latest_price(self, symbol: str, category: str) -> float:
        instrument_id = self._resolve_or_raise(symbol)
        quote = self.get_rate_by_instrument(instrument_id)
        price = quote.get("last_price") or quote.get("ask_price") or quote.get("bid_price")
        if not price:
            raise EToroAPIError(404, f"no price for {symbol}")
        return float(price)

    def get_latest_quote(self, symbol: str, category: str) -> dict[str, float | None]:
        instrument_id = self._resolve_or_raise(symbol)
        quote = self.get_rate_by_instrument(instrument_id)
        return {
            "bid_price": quote.get("bid_price"),
            "ask_price": quote.get("ask_price"),
            "bid_size": None,
            "ask_size": None,
        }

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

    def instrument_id_for_symbol(self, symbol: str) -> int | None:
        """Resolve a ticker to an eToro instrumentId, caching in instrument_map."""

        normalized = str(symbol).upper().strip()
        cached = get_instrument_mapping(self.config.db_market_data, normalized)
        if cached:
            return int(cached["instrument_id"])
        asset = self.resolve_instrument(normalized)
        if asset is None:
            return None
        upsert_instrument_mapping(
            self.config.db_market_data,
            asset["symbol"],
            asset["instrument_id"],
            asset["category"],
            asset["name"],
            asset["tradable"],
        )
        return asset["instrument_id"]

    _ASSET_CLASS_HINTS = {
        "US_EQUITY": ("stock",),
        "STOCK": ("stock",),
        "CRYPTO": ("crypto",),
    }

    DISCOVER_PAGE_SIZE = 200
    DISCOVER_MAX_ITEMS = 2500
    _DISCOVER_CAPS = {"STOCK": 2500, "CRYPTO": 1000}
    # eToro's /market-data/search returns ONLY ``instrumentId`` per item
    # regardless of the requested ``fields`` projection, and ranks
    # most-popular-first with the *ascending* ``popularityUniques`` key (the
    # ``-popularityUniques`` descending key surfaces dated-future junk first).
    # So the search fallback just collects popular IDs and resolves their
    # metadata in a separate batch instruments lookup.
    _SEARCH_SORT = "popularityUniques"
    _SEARCH_MAX_PAGES = 25
    _INSTRUMENTS_LOOKUP_BATCH = 100

    def list_exchanges(self) -> dict[int, str]:
        """Return ``{exchangeID: exchangeDescription}`` (cached for the run)."""
        if self._exchange_cache is not None:
            return self._exchange_cache
        payload = self._request("GET", "/api/v1/market-data/exchanges")
        out: dict[int, str] = {}
        for row in payload.get("exchangeInfo") or []:
            exchange_id = row.get("exchangeID")
            if exchange_id is None:
                continue
            out[int(exchange_id)] = str(row.get("exchangeDescription") or "")
        self._exchange_cache = out
        return out

    def _instrument_type_ids(self, hints: tuple[str, ...]) -> list[int]:
        """Instrument type IDs whose description matches ``hints`` (``[]`` on 404)."""
        payload = self._request_or_none_on_404("GET", "/api/v1/market-data/instrument-types")
        if payload is None:
            return []
        out: list[int] = []
        for entry in payload.get("instrumentTypes") or []:
            desc = str(entry.get("instrumentTypeDescription") or "").lower()
            if any(hint in desc for hint in hints) and entry.get("instrumentTypeID") is not None:
                out.append(int(entry["instrumentTypeID"]))
        return out

    def _search_popular_instrument_ids(self, page: int) -> list[int] | None:
        """One page of instrument IDs ranked most-popular-first, or ``None`` on 404.

        The search projection is irrelevant (eToro returns only ``instrumentId``),
        so we request just that field and let the ascending ``popularityUniques``
        sort do the ranking. Non-positive IDs (synthetic aggregate rows like
        ``-100000``) are dropped.
        """
        payload = self._request_or_none_on_404(
            "GET",
            "/api/v1/market-data/search",
            params={
                "fields": "instrumentId",
                "pageSize": self.DISCOVER_PAGE_SIZE,
                "pageNumber": page,
                "sort": self._SEARCH_SORT,
            },
        )
        if payload is None:
            return None
        ids: list[int] = []
        for item in payload.get("items") or []:
            raw = item.get("instrumentId")
            if raw is None:
                continue
            try:
                iid = int(raw)
            except (TypeError, ValueError):
                continue
            if iid > 0:
                ids.append(iid)
        return ids

    def _resolve_instruments_metadata(self, instrument_ids: list[int]) -> dict[int, dict[str, Any]]:
        """Batch-resolve instrument IDs to their metadata rows.

        ``/market-data/instruments`` is the only endpoint that maps an ID to its
        symbol/type, but eToro's gateway 500s on ``%2C``-encoded commas, so the
        comma-joined ids must reach it literally (embedded in the path), exactly
        like ``get_rates_by_instruments``.
        """
        out: dict[int, dict[str, Any]] = {}
        for start in range(0, len(instrument_ids), self._INSTRUMENTS_LOOKUP_BATCH):
            batch = instrument_ids[start : start + self._INSTRUMENTS_LOOKUP_BATCH]
            ids_param = ",".join(str(int(i)) for i in batch)
            payload = self._request(
                "GET",
                f"/api/v1/market-data/instruments?instrumentIds={ids_param}",
            )
            for row in payload.get("instrumentDisplayDatas") or []:
                iid = row.get("instrumentID")
                if iid is None:
                    continue
                out[int(iid)] = row
        return out

    def _normalize_search_row(self, row: dict[str, Any], category: str) -> dict[str, Any]:
        """Shape an ``/market-data/instruments`` metadata row like a discover row.

        This endpoint exposes identity + classification only (no fundamentals),
        so the quality/liquidity fields are left unknown and filled later from
        price bars during enrichment. Popularity already pre-qualified the row.
        """
        symbol = str(row.get("symbolFull") or "").upper().strip()
        instrument_id = int(row["instrumentID"])
        name = str(row.get("instrumentDisplayName") or "")
        asset = {
            "symbol": symbol,
            "name": name,
            "isin": "",
            "status": "active",
            "tradable": True,
            "delisted": False,
            "fractionable": False,
            "instrument_id": instrument_id,
            "asset_class": category,
            "instrument_type": category,
            "exchange_name": "",
            "country_code": "",
            "market_cap": None,
            "current_rate": None,
            "avg_daily_volume": None,
            "dollar_volume": None,
            "days_since_first_trade": None,
            "popularity": 0,
            "analyst_consensus": None,
            "analyst_upside": None,
            "analyst_count": 0,
            "revenue_growth": None,
            "net_margin": None,
            "price_change_1d": None,
            "price_change_1w": None,
            "price_change_1m": None,
            "price_change_3m": None,
            "price_change_6m": None,
        }
        try:
            upsert_instrument_mapping(self.config.db_market_data, symbol, instrument_id, category, name, True)
        except Exception:
            self.logger.debug("Failed to cache instrument mapping for %s", symbol)
        return asset

    def _search_instruments_for_prefilter(self, asset_class: str) -> list[dict[str, Any]]:
        ac = str(asset_class).upper()
        hints = self._ASSET_CLASS_HINTS.get(ac, (ac.lower(),))
        category = "CRYPTO" if "crypto" in hints else "STOCK"
        type_ids = set(self._instrument_type_ids(hints))
        if not type_ids:
            return []
        # The search feed is popularity-ranked (best first) AND rate-limited, so
        # collecting the full DISCOVER cap is wasteful: the universe only keeps a
        # shortlist of a few hundred. Bound the pull to the configured shortlist
        # plus headroom for the downstream cheap filter / dedupe.
        shortlist = (
            self.config.universe_crypto_shortlist
            if category == "CRYPTO"
            else self.config.universe_stock_shortlist
        )
        cap = min(
            self._DISCOVER_CAPS.get(category, self.DISCOVER_MAX_ITEMS),
            max(int(shortlist) * 2, 200),
        )
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        while len(out) < cap and page <= self._SEARCH_MAX_PAGES:
            ids = self._search_popular_instrument_ids(page)
            if ids is None:
                self.logger.warning(
                    "eToro market-data search returned 404; cannot refresh %s candidates",
                    category,
                )
                return []
            if not ids:
                break
            metadata = self._resolve_instruments_metadata(ids)
            # iterate in the popularity order returned by search
            for iid in ids:
                row = metadata.get(iid)
                if row is None or row.get("isInternalInstrument"):
                    continue
                row_type_id = row.get("instrumentTypeID")
                if row_type_id is None or int(row_type_id) not in type_ids:
                    continue
                symbol = str(row.get("symbolFull") or "").upper().strip()
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                out.append(self._normalize_search_row(row, category))
                if len(out) >= cap:
                    break
            if len(ids) < self.DISCOVER_PAGE_SIZE:
                break
            page += 1
        return out

    def discover_instruments(self, asset_class: str) -> list[dict[str, Any]]:
        """Cheap metadata discovery for the universe prefilter.

        eToro's public API exposes no fundamentals-discovery endpoint, so
        candidates are ranked via ``/market-data/search`` (``popularityUniques``
        sort) and resolved to symbols/types via ``/market-data/instruments``.
        No price bars are fetched here; quality/liquidity is filled later during
        enrichment, and popularity already pre-qualifies the pool.

        Note: each accepted row is upserted into the local ``instrument_map``
        cache individually; O(rows) SQLite writes per run, bounded by the
        per-category cap.
        """
        return self._search_instruments_for_prefilter(asset_class)

    # --- account & portfolio ------------------------------------------------

    def _portfolio(self) -> dict[str, Any]:
        path = f"/api/v1/trading/info/{self._mode_segment()}portfolio"
        payload = self._request("GET", path)
        return payload.get("clientPortfolio") or {}

    def get_portfolio(self) -> dict[str, Any]:
        """Return the raw normalized portfolio payload (one GET).

        Exposes ``credit``, ``positions``, and ``orders`` so callers can
        derive both cash and equity without a second network call.
        """
        return self._portfolio()

    def get_rates_by_instruments(self, instrument_ids: list[int]) -> dict[int, dict]:
        """Fetch live rates for a batch of instrument IDs in a single GET.

        Returns ``{instrument_id: rate_dict}`` where each ``rate_dict``
        contains ``bid``, ``ask``, and ``lastExecution`` (any may be ``None``).
        Returns ``{}`` immediately when *instrument_ids* is empty (no network
        call).
        """
        if not instrument_ids:
            return {}
        # eToro's gateway returns 500 for %2C-encoded commas, and requests
        # percent-encodes a comma-joined ``params`` value. Embed the query in the
        # path so the commas reach eToro literally (``instrumentIds=1,2,3``).
        # A single id has no comma, which is why this only surfaced with >=2
        # open positions. (``requote_uri`` keeps literal commas intact.)
        ids_param = ",".join(str(int(i)) for i in instrument_ids)
        payload = self._request(
            "GET",
            f"/api/v1/market-data/instruments/rates?instrumentIds={ids_param}",
        )
        result: dict[int, dict] = {}
        for row in payload.get("rates") or []:
            iid = row.get("instrumentID")
            if iid is None:
                continue
            bid = float(row.get("bid") or 0.0) or None
            ask = float(row.get("ask") or 0.0) or None
            last = float(row.get("lastExecution") or 0.0) or None
            result[int(iid)] = {"bid": bid, "ask": ask, "lastExecution": last}
        return result

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

    @staticmethod
    def _format_history_date(value: Any) -> str:
        """Coerce a date/datetime/str into the ``YYYY-MM-DD`` that ``minDate`` expects."""

        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        return str(value)[:10]

    @staticmethod
    def _normalize_history_trade(raw: dict[str, Any]) -> dict[str, Any]:
        """Normalize one closed-trade row from ``trade/{demo/}history``.

        Exposes the broker's *authoritative* realized result (``netProfit`` and
        ``closeRate``) so the reconciler can overwrite locally-estimated PnL.
        """

        iid = raw.get("instrumentId")
        pid = raw.get("positionId")

        def _f(key: str) -> float | None:
            return float(raw[key]) if raw.get(key) is not None else None

        return {
            "position_id": str(pid) if pid is not None else None,
            "instrument_id": int(iid) if iid is not None else None,
            "net_profit": float(raw.get("netProfit") or 0.0),
            "open_rate": _f("openRate"),
            "close_rate": _f("closeRate"),
            "units": _f("units"),
            "investment": _f("investment"),
            "fees": float(raw.get("fees") or 0.0),
            "is_buy": bool(raw.get("isBuy", True)),
            "open_timestamp": raw.get("openTimestamp"),
            "close_timestamp": raw.get("closeTimestamp"),
        }

    def list_trade_history(
        self,
        min_date: Any,
        *,
        page_size: int = 200,
        max_pages: int = 50,
    ) -> list[dict[str, Any]]:
        """Return closed trades from ``minDate`` onward (paginated, normalized).

        eToro returns one JSON array per page; we keep requesting pages until a
        short/empty page signals the end. Each row carries ``net_profit`` /
        ``close_rate`` — the real execution the account settled at.
        """

        date_str = self._format_history_date(min_date)
        path = f"/api/v1/trading/info/trade/{self._mode_segment()}history"
        history: list[dict[str, Any]] = []
        page = 1
        while page <= max_pages:
            payload = self._request(
                "GET",
                path,
                params={"minDate": date_str, "page": page, "pageSize": page_size},
            )
            if isinstance(payload, list):
                rows = payload
            else:
                rows = payload.get("items") or payload.get("data") or []
            if not rows:
                break
            history.extend(self._normalize_history_trade(r) for r in rows)
            if len(rows) < page_size:
                break
            page += 1
        return history

    def get_available_cash(self) -> float:
        portfolio = self._portfolio()
        credit = float(portfolio.get("credit") or 0.0)
        pending = sum(float(o.get("amount") or 0.0) for o in (portfolio.get("orders") or []))
        return max(0.0, credit - pending)

    def get_account_equity(self) -> float:
        portfolio = self._portfolio()
        credit = float(portfolio.get("credit") or 0.0)
        positions = portfolio.get("positions") or []
        # Use the hardened batched-rates helper (it skips rows with a null
        # instrumentID and floats bid/ask/last). Mirrors ``live_snapshot._build``
        # so equity here matches the live snapshot the rest of the app shows.
        instrument_ids = [
            int(p["instrumentID"]) for p in positions if p.get("instrumentID") is not None
        ]
        if not instrument_ids:
            return credit
        # Tolerate a rates-fetch failure (e.g. an eToro 500): fall back to
        # openRate so equity stays a usable figure instead of raising and being
        # collapsed to 0 by callers. Mirrors ``live_snapshot._build``.
        try:
            rate_map = self.get_rates_by_instruments(instrument_ids)
        except Exception as exc:
            self.logger.debug("get_account_equity: rates fetch failed, using openRate: %s", exc)
            rate_map = {}
        market_value = 0.0
        for position in positions:
            iid = position.get("instrumentID")
            if iid is None:
                continue
            units = float(position.get("units") or 0.0)
            open_rate = float(position.get("openRate") or 0.0)
            rate = rate_map.get(int(iid), {})
            price = rate.get("bid") or rate.get("lastExecution") or open_rate
            market_value += units * float(price or open_rate)
        return credit + market_value

    def get_open_position(self, symbol: str) -> dict[str, Any] | None:
        instrument_id = self.instrument_id_for_symbol(symbol)
        if instrument_id is None:
            return None
        for position in self.list_open_positions():
            if position["instrument_id"] == instrument_id:
                position["symbol"] = str(symbol).upper().strip()
                return position
        return None

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
        # eToro requires EXACTLY ONE of symbol / instrumentId on open orders
        # (sending both → HTTP 400 "Exactly one of Symbol or InstrumentID must
        # be provided. Both were supplied."). We send the canonical instrumentId
        # only; `symbol` is kept in the signature for logging/clarity.
        body = {
            "action": "open",
            "transaction": "buy",
            "instrumentId": int(instrument_id),
            "settlementType": "real",
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

    def close_position_market(self, position_id: str, instrument_id: int, units: float | None = None) -> dict[str, Any]:
        """Close (or partially close) a position via the dedicated market-close endpoint.

        eToro's v2 orders endpoint does not accept ``action=close``; the correct
        path is the v1 market-close-orders endpoint, which needs the instrument id
        and (optionally) the units to deduct for a partial close.
        """
        path = f"/api/v1/trading/execution/{self._mode_segment()}market-close-orders/positions/{position_id}"
        body: dict[str, Any] = {"InstrumentID": int(instrument_id)}
        if units is not None:
            body["UnitsToDeduct"] = float(units)
        payload = self._request_with_id("POST", path, str(uuid4()), json_body=body)
        order = payload.get("orderForClose") or {}
        return {
            "order_id": str(order.get("orderID")) if order.get("orderID") is not None else None,
            "raw": payload,
        }

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an order before it executes (idempotent if already closed)."""
        path = f"/api/v2/trading/execution/{self._mode_segment()}orders/{order_id}"
        return self._request_with_id("DELETE", path, str(uuid4()))

    @staticmethod
    def _classify_order_status(name: str) -> tuple[bool, bool, bool, bool]:
        """Return (executed, waiting, rejected, canceled) from the status name.

        eToro status *ids* are inconsistent across asset types (id 3 was observed
        meaning "Filled" for crypto yet "Rejected" elsewhere), so classify ONLY by
        the human-readable name. An unrecognized name is treated as still-waiting
        (keep polling) rather than guessed terminal.
        """
        text = name.lower()
        if "fill" in text or "execut" in text:
            return True, False, False, False
        if "reject" in text:
            return False, False, True, False
        if "cancel" in text:
            return False, False, False, True
        return False, True, False, False  # waiting / unknown -> keep polling

    def get_order_status(self, order_id: str) -> dict[str, Any] | None:
        """Resolve an order's async outcome via the orders:lookup endpoint.

        Returns ``None`` when the order is not (yet) found (HTTP 404).
        """
        path = f"/api/v2/trading/info/{self._mode_segment()}orders:lookup"
        try:
            payload = self._request("GET", path, params={"orderId": str(order_id)})
        except EToroAPIError as exc:
            if exc.status_code == 404:
                return None
            raise
        status = payload.get("status") or {}
        name = str(status.get("name") or "")
        status_id = status.get("id")
        executed, waiting, rejected, canceled = self._classify_order_status(name)
        position_id = None
        for execution in payload.get("positionExecutions") or []:
            if str(execution.get("state") or "").lower() == "open" and execution.get("positionId") is not None:
                position_id = str(execution["positionId"])
                break
        return {
            "order_id": str(order_id),
            "status_name": name,
            "status_id": status_id,
            "executed": executed,
            "waiting": waiting,
            "rejected": rejected,
            "canceled": canceled,
            "error_code": status.get("errorCode"),
            "error_message": status.get("errorMessage"),
            "position_id": position_id,
        }
