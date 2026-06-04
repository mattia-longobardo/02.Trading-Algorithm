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
