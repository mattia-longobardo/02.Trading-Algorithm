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


class EToroAsset:
    """Minimal asset view (attribute-compatible with the universe scanner)."""

    __slots__ = ("symbol", "name", "status", "tradable", "fractionable", "instrument_id")

    def __init__(self, symbol: str, name: str, status: str, tradable: bool, fractionable: bool, instrument_id: int) -> None:
        self.symbol = symbol
        self.name = name
        self.status = status
        self.tradable = tradable
        self.fractionable = fractionable
        self.instrument_id = instrument_id


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
    # discover mixes all asset classes; the working server-side type filter is
    # `assetClass` (NOT `instrumentTypeID`, which does not filter).
    _ASSET_CLASS_PARAM = {"US_EQUITY": "Stocks", "STOCK": "Stocks", "CRYPTO": "Crypto"}
    _DISCOVER_CAPS = {"STOCK": 2500, "CRYPTO": 1000}
    # The default discover projection is minimal; requesting an explicit field
    # list returns the full fundamentals object (incl. marketCap, liquidity,
    # analyst consensus, growth/margin) with NO bar fetch.
    _DISCOVER_FIELDS = (
        "symbol,isin,displayName,assetClass,exchangeName,countryCode,"
        "marketCapInUSD,currentRate,popularityUniques,isBuyEnabled,isDelisted,"
        "daysSinceFirstTrade,averageDailyVolumeLast3Months-TTM,"
        "tipranksAllConsensus,tipranksAllUpside,tipranksAllTotalAnalysts,"
        "oneYearAnnualRevenueGrowthRate,netProfitMargin,"
        "dailyPriceChange,weeklyPriceChange,monthlyPriceChange,"
        "threeMonthPriceChange,sixMonthPriceChange"
    )

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
        payload = self._request("GET", "/api/v1/market-data/instrument-types")
        out: list[int] = []
        for entry in payload.get("instrumentTypes") or []:
            desc = str(entry.get("instrumentTypeDescription") or "").lower()
            if any(hint in desc for hint in hints) and entry.get("instrumentTypeID") is not None:
                out.append(int(entry["instrumentTypeID"]))
        return out

    def list_assets(self, asset_class: str) -> list[EToroAsset]:
        hints = self._ASSET_CLASS_HINTS.get(str(asset_class).upper(), (str(asset_class).lower(),))
        category = "CRYPTO" if "crypto" in hints else "STOCK"
        type_ids = self._instrument_type_ids(hints)
        if not type_ids:
            return []
        payload = self._request(
            "GET",
            "/api/v1/market-data/instruments",
            params={"instrumentTypeIds": ",".join(str(i) for i in type_ids)},
        )
        assets: list[EToroAsset] = []
        for row in payload.get("instrumentDisplayDatas") or []:
            if row.get("isInternalInstrument"):
                continue
            symbol = str(row.get("symbolFull") or "").upper().strip()
            if not symbol or row.get("instrumentID") is None:
                continue
            instrument_id = int(row["instrumentID"])
            name = str(row.get("instrumentDisplayName") or "")
            assets.append(EToroAsset(symbol, name, "active", True, True, instrument_id))
            try:
                upsert_instrument_mapping(self.config.db_market_data, symbol, instrument_id, category, name, True)
            except Exception:
                self.logger.debug("Failed to cache instrument mapping for %s", symbol)
        return assets

    @staticmethod
    def _discover_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalize_discover_row(self, row: dict[str, Any], category: str) -> dict[str, Any]:
        symbol = str(row.get("symbol") or "").upper().strip()
        instrument_id = int(row["instrumentId"])
        name = str(row.get("displayName") or "")
        delisted = bool(row.get("isDelisted"))
        tradable = bool(row.get("isBuyEnabled", True)) and not delisted
        current_rate = self._discover_float(row.get("currentRate"))
        avg_daily_volume = self._discover_float(row.get("averageDailyVolumeLast3Months-TTM"))
        dollar_volume = (
            avg_daily_volume * current_rate
            if avg_daily_volume is not None and current_rate is not None
            else None
        )
        consensus = row.get("tipranksAllConsensus")
        asset = {
            "symbol": symbol,
            "name": name,
            "isin": str(row.get("isin") or "").strip(),
            "status": "active",
            "tradable": tradable,
            "delisted": delisted,
            "fractionable": False,
            "instrument_id": instrument_id,
            "asset_class": str(row.get("assetClass") or ""),
            "instrument_type": str(row.get("assetClass") or ""),
            "exchange_name": str(row.get("exchangeName") or ""),
            "country_code": str(row.get("countryCode") or "").upper(),
            "market_cap": self._discover_float(row.get("marketCapInUSD")),
            "current_rate": current_rate,
            "avg_daily_volume": avg_daily_volume,
            "dollar_volume": dollar_volume,
            "days_since_first_trade": self._discover_float(row.get("daysSinceFirstTrade")),
            "popularity": int(self._discover_float(row.get("popularityUniques")) or 0),
            "analyst_consensus": str(consensus) if consensus else None,
            "analyst_upside": self._discover_float(row.get("tipranksAllUpside")),
            "analyst_count": int(self._discover_float(row.get("tipranksAllTotalAnalysts")) or 0),
            "revenue_growth": self._discover_float(row.get("oneYearAnnualRevenueGrowthRate")),
            "net_margin": self._discover_float(row.get("netProfitMargin")),
            "price_change_1d": self._discover_float(row.get("dailyPriceChange")),
            "price_change_1w": self._discover_float(row.get("weeklyPriceChange")),
            "price_change_1m": self._discover_float(row.get("monthlyPriceChange")),
            "price_change_3m": self._discover_float(row.get("threeMonthPriceChange")),
            "price_change_6m": self._discover_float(row.get("sixMonthPriceChange")),
        }
        try:
            upsert_instrument_mapping(self.config.db_market_data, symbol, instrument_id, category, name, tradable)
        except Exception:
            self.logger.debug("Failed to cache instrument mapping for %s", symbol)
        return asset

    def discover_instruments(self, asset_class: str) -> list[dict[str, Any]]:
        """Cheap metadata discovery for the universe prefilter.

        Uses ``/api/v1/instruments/discover`` with the ``assetClass`` server-side
        filter and an explicit ``fields`` projection to return rich fundamentals
        (market cap, liquidity, analyst consensus, growth/margin, momentum)
        WITHOUT fetching any price bars. Stocks are filtered to
        ``universe_stock_min_market_cap`` server-side and sorted by market cap.

        Note: each accepted row is upserted into the local ``instrument_map``
        cache individually; O(rows) SQLite writes per run, bounded by the
        per-category cap.
        """
        ac = str(asset_class).upper()
        asset_class_param = self._ASSET_CLASS_PARAM.get(ac, ac.title())
        category = "CRYPTO" if asset_class_param == "Crypto" else "STOCK"
        params_base: dict[str, Any] = {
            "assetClass": asset_class_param,
            "pageSize": self.DISCOVER_PAGE_SIZE,
            "fields": self._DISCOVER_FIELDS,
        }
        if category == "STOCK":
            params_base["sort"] = "-marketCap"
            min_cap = self.config.universe_stock_min_market_cap
            if min_cap and min_cap > 0:
                params_base["marketCapMin"] = int(min_cap)
        else:
            params_base["sort"] = "-popularityUniques"
        cap = self._DISCOVER_CAPS.get(category, self.DISCOVER_MAX_ITEMS)
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        page = 1
        while len(out) < cap:
            payload = self._request(
                "GET", "/api/v1/instruments/discover", params={**params_base, "page": page}
            )
            items = payload.get("items") or []
            if not items:
                break
            for row in items:
                if row.get("isInternalInstrument") or row.get("isHiddenFromClient"):
                    continue
                symbol = str(row.get("symbol") or "").upper().strip()
                if not symbol or symbol in seen or row.get("instrumentId") is None:
                    continue
                seen.add(symbol)
                out.append(self._normalize_discover_row(row, category))
            if len(items) < self.DISCOVER_PAGE_SIZE:
                break
            page += 1
        return out

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
        ids_param = ",".join(str(int(i)) for i in instrument_ids)
        payload = self._request(
            "GET",
            "/api/v1/market-data/instruments/rates",
            params={"instrumentIds": ids_param},
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
