"""Client HTTP per l'eToro Public API.

Rotte e campi provengono da docs/etoro_api.md (spec verificate via MCP
ufficiale): mai inventare endpoint o campi. Il prefisso `demo/` si applica
SOLO alle rotte trading (execution + trading/info); market-data non ha
varianti demo/real.

Policy errori (docs §2): 429 → rispetta Retry-After; 5xx → backoff
esponenziale; 4xx (≠429) → EtoroError senza retry. Max 3 tentativi.
Le chiavi API non vengono mai loggate né incluse nei messaggi d'errore.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any

import requests

from etoro_bot.etoro.rate_limiter import RateLimiter

logger = logging.getLogger("etoro_bot.etoro")

BASE_URL = "https://public-api.etoro.com"

_MAX_ATTEMPTS = 3
_BACKOFF_BASE_S = 1.0
_ORDER_POLL_TIMEOUT_S = 30.0
_ORDER_POLL_INTERVAL_S = 1.0

ORDER_STATUS_FILLED = 3
# 4 Rejected, 7 Canceled, 8 Expired, 9 CanceledPartiallyFilled, 10 RejectedPartiallyFilled
_ORDER_STATUS_TERMINAL_KO = {4, 7, 8, 9, 10}


class EtoroError(Exception):
    """Errore API eToro: 4xx, retry esauriti, timeout ordine o risposta malformata."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _parse_retry_after(value: str | None) -> float:
    try:
        return max(float(value), 0.0) if value is not None else 1.0
    except ValueError:
        return 1.0


def _project(rows: list[dict], fields: list[str]) -> list[dict]:
    """Proiezione client-side sui campi richiesti (lista vuota = tutti)."""
    if not fields:
        return rows
    wanted = set(fields)
    return [{k: v for k, v in row.items() if k in wanted} for row in rows]


def _as_list(data: Any) -> list[dict]:
    """Trade history risponde con un array; tollera un eventuale wrapper dict."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
    return []


class EtoroClient:
    """Client sincrono (requests + stdlib) con rate limiting per pool e retry."""

    def __init__(
        self,
        api_key: str,
        user_key: str,
        environment: str = "demo",
        session: requests.Session | None = None,
        *,
        rate_limiter: RateLimiter | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        env = getattr(environment, "value", environment)
        if env not in ("demo", "real"):
            raise ValueError(f"environment non valido: {env!r} (atteso 'demo' o 'real')")
        self._environment = env
        self._api_key = api_key
        self._user_key = user_key
        self._session = session or requests.Session()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._timeout = timeout_s
        self._sleep = time.sleep  # iniettabile nei test
        self._clock = time.monotonic
        self._instrument_types: dict[int, str] | None = None
        self._stocks_industries: dict[int, str] | None = None

    @property
    def _trading_segment(self) -> str:
        """Segmento `demo/` per le sole rotte trading (execution + trading/info)."""
        return "demo/" if self._environment == "demo" else ""

    # ------------------------------------------------------------------ HTTP

    def _request(
        self,
        method: str,
        path: str,
        *,
        pool: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> Any:
        """Richiesta con header obbligatori, rate limiting e policy di retry.

        `request_id` è riusato identico su ogni tentativo: per gli ordini è la
        chiave di idempotenza (= referenceId nella lookup).
        """
        url = BASE_URL + path
        headers = {
            "x-api-key": self._api_key,
            "x-user-key": self._user_key,
            "x-request-id": request_id or str(uuid.uuid4()),
        }
        for attempt in range(_MAX_ATTEMPTS):
            self._rate_limiter.acquire(pool)
            try:
                resp = self._session.request(
                    method, url, params=params, json=json_body, headers=headers,
                    timeout=self._timeout,
                )
            except requests.RequestException as exc:
                if attempt < _MAX_ATTEMPTS - 1:
                    self._sleep(_BACKOFF_BASE_S * 2**attempt)
                    continue
                raise EtoroError(f"errore di rete su {method} {path}: {exc}") from exc
            status = resp.status_code
            if 200 <= status < 300:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise EtoroError(
                        f"risposta non JSON da {method} {path}", status_code=status
                    ) from exc
            if status == 429 and attempt < _MAX_ATTEMPTS - 1:
                self._sleep(_parse_retry_after(resp.headers.get("Retry-After")))
                continue
            if 500 <= status < 600 and attempt < _MAX_ATTEMPTS - 1:
                self._sleep(_BACKOFF_BASE_S * 2**attempt)
                continue
            # 4xx (≠429) al primo colpo, oppure 429/5xx a tentativi esauriti.
            # Mai includere gli header (chiavi API) nel messaggio.
            raise EtoroError(
                f"HTTP {status} {method} {path}: {(resp.text or '')[:300]}",
                status_code=status,
            )
        raise EtoroError(f"tentativi esauriti su {method} {path}")  # pragma: no cover

    # ----------------------------------------------------- market data (120/60s)

    def search_instruments(
        self, query_filters: dict, fields: list[str], page_size: int = 50
    ) -> list[dict]:
        """Ricerca/screening strumenti; `fields` è obbligatorio (docs §3.1).

        Ogni campo dello schema Instrument è usabile come filtro in
        `query_filters` (es. {"instrumentTypeID": 5}). Pagina fino a esaurire
        `totalItems`.
        """
        items: list[dict] = []
        page = 1
        while True:
            params: dict[str, Any] = {
                **query_filters,
                "fields": ",".join(fields),
                "pageSize": page_size,
                "pageNumber": page,
            }
            data = self._request(
                "GET", "/api/v1/market-data/search", pool="market-data", params=params
            )
            batch = data.get("items") or []
            items.extend(batch)
            total = data.get("totalItems")
            if not batch or len(batch) < page_size:
                break
            if isinstance(total, int) and len(items) >= total:
                break
            page += 1
        return items

    def get_instruments(self, instrument_ids: list[int], fields: list[str]) -> list[dict]:
        """Anagrafica strumenti (instrumentDisplayDatas, docs §3.2).

        `instrumentIds` accetta UN SOLO id per chiamata: con una lista separata
        da virgole l'API risponde 500, quindi si itera. Per caricare molti
        strumenti in un colpo solo usare `get_instruments_by_type`.
        L'endpoint non ha un parametro `fields`: la proiezione è client-side
        (lista vuota = tutti i campi).
        """
        rows: list[dict] = []
        for instrument_id in instrument_ids:
            data = self._request(
                "GET",
                "/api/v1/market-data/instruments",
                pool="market-data",
                params={"instrumentIds": int(instrument_id)},
            )
            rows.extend(data.get("instrumentDisplayDatas") or [])
        return _project(rows, fields)

    def get_instruments_by_type(self, instrument_type_id: int) -> list[dict]:
        """Intero catalogo di un tipo di strumento (5 = Stocks, 6 = ETF).

        Una sola chiamata restituisce tutte le anagrafiche del tipo, con
        `symbolFull` e `stocksIndustryID`: è il modo giusto per risolvere i
        simboli della watchlist, visto che `/search` sa filtrare ma restituisce
        soltanto `instrumentId`.
        """
        data = self._request(
            "GET",
            "/api/v1/market-data/instruments",
            pool="market-data",
            params={"instrumentTypeIds": int(instrument_type_id)},
        )
        return data.get("instrumentDisplayDatas") or []

    def get_rates(self, instrument_ids: list[int]) -> dict[int, dict]:
        """Prezzi correnti per instrumentID.

        Un id per chiamata: `instrumentIds` vuole un intero singolo e con una
        lista separata da virgole l'API risponde 400 ("is not a valid
        integer"). Gli id non quotati vengono semplicemente omessi dal
        risultato, così un simbolo senza prezzo non fa fallire l'intera run.
        """
        rates: dict[int, dict] = {}
        for instrument_id in instrument_ids:
            try:
                data = self._request(
                    "GET", "/api/v1/market-data/instruments/rates",
                    pool="market-data", params={"instrumentIds": int(instrument_id)},
                )
            except EtoroError:
                logger.warning("prezzo non disponibile per instrumentId=%s", instrument_id)
                continue
            for rate in data.get("rates") or []:
                rate_id = rate.get("instrumentID")
                if rate_id is not None:
                    rates[int(rate_id)] = rate
        return rates

    def get_candles(
        self,
        instrument_id: int,
        interval: str = "OneDay",
        count: int = 250,
        direction: str = "asc",
    ) -> list[dict]:
        """Candele storiche, appiattite in [{fromDate, open, high, low, close, volume}]."""
        path = (
            f"/api/v1/market-data/instruments/{instrument_id}"
            f"/history/candles/{direction}/{interval}/{count}"
        )
        data = self._request("GET", path, pool="market-data")
        # Il payload è {"interval": …, "candles": [{"instrumentId": …,
        # "candles": [...]}]}: non c'è nessun involucro "candlesResponse"
        # (che infatti restituiva sempre zero candele).
        groups = data.get("candles") or (data.get("candlesResponse") or {}).get("candles") or []
        if not groups:
            return []
        return [
            {key: candle.get(key) for key in ("fromDate", "open", "high", "low", "close", "volume")}
            for candle in groups[0].get("candles") or []
        ]

    def get_instrument_types(self) -> dict[int, str]:
        """Mapping instrumentTypeID -> descrizione (lookup statica, cache in memoria)."""
        if self._instrument_types is None:
            data = self._request(
                "GET", "/api/v1/market-data/instrument-types", pool="market-data"
            )
            self._instrument_types = {
                int(row["instrumentTypeID"]): row.get("instrumentTypeDescription", "")
                for row in data.get("instrumentTypes") or []
            }
        return self._instrument_types

    def get_stocks_industries(self) -> dict[int, str]:
        """Mapping industryID -> industryName (lookup statica, cache in memoria)."""
        if self._stocks_industries is None:
            data = self._request(
                "GET", "/api/v1/market-data/stocks-industries", pool="market-data"
            )
            self._stocks_industries = {
                int(row["industryID"]): row.get("industryName", "")
                for row in data.get("stocksIndustries") or []
            }
        return self._stocks_industries

    # ------------------------------------------------- trading info (letture)

    def get_portfolio(self) -> dict:
        """Portafoglio del conto: positions[] + credit (docs §4.1). Fonte reconcile."""
        data = self._request(
            "GET", f"/api/v1/trading/info/{self._trading_segment}portfolio",
            pool="trading-info",
        )
        return data.get("clientPortfolio") or {}

    def get_trade_history(
        self, min_date: datetime | None = None, page_size: int = 100
    ) -> list[dict]:
        """Trade chiusi con netProfit/closeRate/closeTimestamp per positionId (docs §4.2)."""
        start = (min_date or datetime(2010, 1, 1)).date().isoformat()
        trades: list[dict] = []
        page = 1
        while True:
            params = {"minDate": start, "page": page, "pageSize": page_size}
            data = self._request(
                "GET", f"/api/v1/trading/info/trade/{self._trading_segment}history",
                pool="default", params=params,
            )
            batch = _as_list(data)
            trades.extend(batch)
            if len(batch) < page_size:
                break
            page += 1
        return trades

    def lookup_order(
        self, order_id: int | None = None, reference_id: str | None = None
    ) -> dict:
        """Risolve un ordine in posizioni/stato (docs §5.3).

        Esattamente uno tra `order_id` e `reference_id` (= x-request-id
        dell'ordine): il reference_id permette il recovery idempotente dopo un
        crash senza conoscere l'orderId.
        """
        if (order_id is None) == (reference_id is None):
            raise ValueError("serve esattamente uno tra order_id e reference_id")
        params: dict[str, Any] = (
            {"orderId": order_id} if order_id is not None else {"referenceId": reference_id}
        )
        return self._request(
            "GET", f"/api/v2/trading/info/{self._trading_segment}orders:lookup",
            pool="trading-info", params=params,
        )

    # ------------------------------------------------- execution (20/60s)

    def open_position(self, instrument_id: int, amount_usd: float, request_id: str) -> dict:
        """Apre una posizione long a mercato e attende il fill (docs §5.1 + §5.3).

        `request_id` è la chiave di idempotenza (x-request-id = referenceId):
        DEVE arrivare dal chiamante (UUID5 deterministico della run).
        Ritorna {"position_id", "execution_price", "order_id"}.
        """
        body = {
            "action": "open",
            "transaction": "buy",
            "instrumentId": instrument_id,
            "settlementType": "real",
            "orderType": "mkt",
            "leverage": 1,
            "amount": amount_usd,
            "orderCurrency": "usd",
        }
        data = self._request(
            "POST", f"/api/v2/trading/execution/{self._trading_segment}orders",
            pool="execution", json_body=body, request_id=request_id,
        )
        order_id = data.get("orderId")
        if order_id is None:
            raise EtoroError(f"risposta open senza orderId (referenceId={request_id})")
        return self._wait_for_fill(order_id)

    def _wait_for_fill(self, order_id: int) -> dict:
        """Poll su orders:lookup finché Filled (status.id == 3), timeout ~30s."""
        deadline = self._clock() + _ORDER_POLL_TIMEOUT_S
        while True:
            info = self.lookup_order(order_id=order_id)
            status = info.get("status") or {}
            status_id = status.get("id")
            if status_id == ORDER_STATUS_FILLED:
                executions = info.get("positionExecutions") or []
                if not executions:
                    raise EtoroError(f"ordine {order_id} Filled ma senza positionExecutions")
                opening = executions[0].get("openingData") or {}
                return {
                    "position_id": executions[0].get("positionId"),
                    "execution_price": opening.get("avgPrice"),
                    "order_id": order_id,
                }
            if status_id in _ORDER_STATUS_TERMINAL_KO:
                raise EtoroError(
                    f"ordine {order_id} terminato con status "
                    f"{status.get('name') or status_id}: "
                    f"{status.get('errorCode')} {status.get('errorMessage')}"
                )
            if self._clock() >= deadline:
                raise EtoroError(
                    f"timeout in attesa del fill dell'ordine orderId={order_id}: "
                    "verificare l'esito con lookup_order"
                )
            self._sleep(_ORDER_POLL_INTERVAL_S)

    def close_position(self, position_id: int, instrument_id: int) -> dict:
        """Chiude totalmente una posizione a mercato (docs §5.2).

        UnitsToDeduct null = chiusura totale. Ritorna l'orderID di chiusura,
        da verificare (§4.3) e poi matchare in trade history per il netProfit.
        """
        body = {"InstrumentID": instrument_id, "UnitsToDeduct": None}
        data = self._request(
            "POST",
            f"/api/v1/trading/execution/{self._trading_segment}"
            f"market-close-orders/positions/{position_id}",
            pool="execution", json_body=body,
        )
        order = data.get("orderForClose") or {}
        return {
            "order_id": order.get("orderID"),
            "position_id": position_id,
            "status_id": order.get("statusID"),
        }
