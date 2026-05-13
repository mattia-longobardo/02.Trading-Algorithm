"""Binance Spot trading and market data client.

Mirrors the surface area of :class:`clients.alpaca_client.AlpacaClient` so the
rest of the stack (trade_manager, universe_manager, data_manager, …) can
dispatch on the ``provider`` attribute and treat both brokers
interchangeably for the bits the bot actually uses (account equity, pair
listing, latest quote, OHLCV bars, marketable IOC entry, market exit).

The client speaks the public Binance Spot REST API directly via
``requests`` (already in the project's dependencies) so we don't add a new
SDK. Only signed endpoints (``/api/v3/account``, ``/api/v3/order``,
``/api/v3/openOrders``) require the HMAC-SHA256 signature; market data
endpoints are public.

Differences vs Alpaca worth knowing:

- Symbols on Binance are unstemmed pairs (``BTCUSDT``), not slash-separated
  (``BTC/USD``). The client normalizes both forms on input but always
  speaks the Binance-native form to the API.
- Binance does not have a "paper trading" mode; operators point this
  client at the testnet via ``BINANCE_BASE_URL`` if they want a sandbox.
- Binance Spot does not support broker-side bracket orders or trailing
  stops the way Alpaca does. The bot already manages TP / SL / trailing
  internally for crypto, so the absence here is fine — we expose
  ``supports_advanced_orders`` and ``supports_broker_side_trailing_stop``
  returning ``False`` to keep the trade lifecycle on the script-managed
  path.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import math
import time
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urlencode
from uuid import uuid4

import requests

from core.utils import AppConfig, retry, utc_now


_HTTP_TIMEOUT = 10.0
_RECV_WINDOW_MS = 5000
_DEFAULT_USER_AGENT = "trading-bot/2.0 (+binance)"


# (signer callable, key_type) where signer takes a query string and returns
# the signature value as a string ready to drop into the URL.
_SignerInfo = tuple[Callable[[str], str], str]


class BinanceAPIError(RuntimeError):
    """Raised when the Binance REST API returns an error payload."""

    def __init__(self, status_code: int, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        prefix = f"[{self.code}] " if self.code is not None else ""
        return f"{prefix}{self.args[0]}"


def _load_private_key_signer(pem_path: str, password: str | None) -> _SignerInfo:
    """Load a Binance Ed25519 or RSA private key and return a signer.

    Binance accepts both Ed25519 (recommended for new keys) and RSA-2048
    private keys. We auto-detect by introspecting the loaded key object so
    operators don't have to set a separate "key type" env variable. The
    signature in both cases is base64-encoded and URL-encoded before being
    appended to the request URL — Binance rejects unescaped ``+`` / ``/``.
    """

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

    path = Path(pem_path).expanduser()
    if not path.is_file():
        raise BinanceAPIError(
            500,
            f"Binance private key file not found at {path}. Check BINANCE_PRIVATE_KEY_PATH "
            "and ensure the file is mounted into the container.",
        )
    pem_bytes = path.read_bytes()
    password_bytes = password.encode("utf-8") if password else None
    try:
        private_key = serialization.load_pem_private_key(pem_bytes, password=password_bytes)
    except Exception as exc:
        raise BinanceAPIError(
            500,
            f"Failed to load Binance private key from {path}: {exc}. The file must "
            "contain an unencrypted (or BINANCE_PRIVATE_KEY_PASSWORD-protected) "
            "Ed25519 or RSA *private* key in PEM format — Binance signing requires "
            "the private half, not the public key uploaded to the exchange.",
        ) from exc

    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        ed_key = private_key

        def sign_ed25519(payload: str) -> str:
            raw = ed_key.sign(payload.encode("utf-8"))
            return quote_plus(base64.b64encode(raw).decode("ascii"))

        return sign_ed25519, "ed25519"

    if isinstance(private_key, rsa.RSAPrivateKey):
        rsa_key = private_key

        def sign_rsa(payload: str) -> str:
            raw = rsa_key.sign(
                payload.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
            return quote_plus(base64.b64encode(raw).decode("ascii"))

        return sign_rsa, "rsa"

    raise BinanceAPIError(
        500,
        f"Unsupported Binance private-key type: {type(private_key).__name__}. "
        "Use Ed25519 (preferred) or RSA-2048.",
    )


class _AssetRecord:
    """Tiny duck-type wrapper so universe_admin's getattr loop just works."""

    __slots__ = ("symbol", "name", "status", "tradable", "fractionable", "base_asset", "quote_asset")

    def __init__(
        self,
        symbol: str,
        name: str,
        status: str,
        tradable: bool,
        fractionable: bool,
        base_asset: str,
        quote_asset: str,
    ) -> None:
        self.symbol = symbol
        self.name = name
        self.status = status
        self.tradable = tradable
        self.fractionable = fractionable
        self.base_asset = base_asset
        self.quote_asset = quote_asset


class _OrderRecord:
    """Mirror enough of the Alpaca order object that callers don't branch."""

    __slots__ = (
        "id",
        "client_order_id",
        "symbol",
        "side",
        "type",
        "status",
        "qty",
        "filled_qty",
        "filled_avg_price",
        "limit_price",
        "submitted_at",
        "updated_at",
        "filled_at",
        "expired_at",
        "canceled_at",
        "legs",
    )

    def __init__(self, raw: dict[str, Any]) -> None:
        self.id = str(raw.get("orderId") or raw.get("clientOrderId") or "")
        self.client_order_id = str(raw.get("clientOrderId") or "")
        self.symbol = str(raw.get("symbol") or "")
        self.side = str(raw.get("side") or "")
        self.type = str(raw.get("type") or "")
        self.status = str(raw.get("status") or "")
        self.qty = _coerce_float(raw.get("origQty"))
        self.filled_qty = _coerce_float(raw.get("executedQty"))
        executed_quote = _coerce_float(raw.get("cummulativeQuoteQty"))
        if self.filled_qty and executed_quote:
            self.filled_avg_price = executed_quote / self.filled_qty
        else:
            self.filled_avg_price = _coerce_float(raw.get("price"))
        self.limit_price = _coerce_float(raw.get("price"))
        self.submitted_at = _epoch_ms_to_isoformat(raw.get("workingTime") or raw.get("time"))
        self.updated_at = _epoch_ms_to_isoformat(raw.get("updateTime") or raw.get("transactTime"))
        if str(self.status).lower() == "filled":
            self.filled_at = self.updated_at
        else:
            self.filled_at = None
        if str(self.status).lower() in ("expired",):
            self.expired_at = self.updated_at
        else:
            self.expired_at = None
        if str(self.status).lower() in ("canceled", "cancelled"):
            self.canceled_at = self.updated_at
        else:
            self.canceled_at = None
        # Binance Spot orders have no native "legs" — we expose an empty list
        # so callers iterating ``order.legs`` don't blow up.
        self.legs: list[Any] = []


def _coerce_float(value: Any) -> float | None:
    if value in (None, "", 0):
        if value == 0:
            return 0.0
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _epoch_ms_to_isoformat(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).isoformat()


class BinanceClient:
    """Thin wrapper around the Binance Spot REST API."""

    provider = "binance"

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger.getChild("binance")
        self.api_key = config.binance_api_key
        self.secret_key = config.binance_secret_key.encode("utf-8") if config.binance_secret_key else b""
        self.base_url = config.binance_base_url.rstrip("/")
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": _DEFAULT_USER_AGENT,
                "Accept": "application/json",
            }
        )
        # Pick the signing strategy at boot. Asymmetric keys take precedence
        # over HMAC so an operator can leave a stale BINANCE_SECRET_KEY in
        # .env without it shadowing the new SSH-style key. The signer is
        # held as a tiny closure so the request path stays branch-free.
        self._signer: Callable[[str], str]
        self.key_type: str
        if config.binance_private_key_path:
            self._signer, self.key_type = _load_private_key_signer(
                config.binance_private_key_path,
                config.binance_private_key_password or None,
            )
            self.logger.info(
                "Binance signing with %s private key from %s",
                self.key_type,
                config.binance_private_key_path,
            )
        elif self.secret_key:
            secret = self.secret_key

            def hmac_sign(payload: str) -> str:
                return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()

            self._signer = hmac_sign
            self.key_type = "hmac"
            self.logger.info("Binance signing with HMAC-SHA256 secret")
        else:
            # Will trip in _signed_request, but we still build the client
            # so public endpoints (no signing) keep working.
            def _missing(payload: str) -> str:  # pragma: no cover - defensive
                raise BinanceAPIError(401, "Binance credentials are not configured")

            self._signer = _missing
            self.key_type = "none"
        # ``_exchange_info`` and ``_quote_currency_lookup`` are warm-loaded on
        # first use and reused — Binance ratelimits ``/exchangeInfo`` more
        # aggressively than the public ticker endpoint.
        self._exchange_info_cache: dict[str, dict[str, Any]] | None = None
        self._exchange_info_fetched_at: float = 0.0

    # -- low-level HTTP ---------------------------------------------------

    def _public_get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = self._session.get(url, params=params or {}, timeout=_HTTP_TIMEOUT)
        except requests.RequestException as exc:
            raise BinanceAPIError(0, f"Network error contacting Binance: {exc}") from exc
        return self._decode_response(response)

    def _signed_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        if not self.api_key or self.key_type == "none":
            raise BinanceAPIError(401, "Binance credentials are not configured")
        params = dict(params or {})
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = _RECV_WINDOW_MS
        query = urlencode(params, doseq=True)
        # The signer returns the signature in URL-ready form: hex for HMAC,
        # URL-encoded base64 for Ed25519 / RSA. Binance accepts both as the
        # ``signature`` query parameter.
        signature = self._signer(query)
        url = f"{self.base_url}{path}?{query}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key}
        try:
            response = self._session.request(
                method.upper(), url, headers=headers, timeout=_HTTP_TIMEOUT
            )
        except requests.RequestException as exc:
            raise BinanceAPIError(0, f"Network error contacting Binance: {exc}") from exc
        return self._decode_response(response)

    @staticmethod
    def _decode_response(response: requests.Response) -> Any:
        try:
            payload = response.json() if response.content else None
        except ValueError:
            payload = None
        if response.status_code >= 400:
            code: int | None = None
            message = f"HTTP {response.status_code}"
            if isinstance(payload, dict):
                if "msg" in payload:
                    message = str(payload.get("msg"))
                if "code" in payload:
                    try:
                        code = int(payload.get("code") or 0)
                    except (TypeError, ValueError):
                        code = None
            raise BinanceAPIError(response.status_code, message, code=code)
        return payload

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def is_insufficient_balance_error(exc: Exception) -> bool:
        if isinstance(exc, BinanceAPIError):
            if exc.code in (-2010, -1013):
                return True
        return "insufficient" in str(exc).lower()

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        """Return the Binance-native form (``BTCUSDT``) for any reasonable input."""

        return str(symbol).replace("/", "").upper().strip()

    @staticmethod
    def display_symbol(symbol: str, quote_currency: str) -> str:
        """Return the human-friendly form ``BTC/USDT`` when possible."""

        raw = BinanceClient.normalize_symbol(symbol)
        quote = (quote_currency or "USDT").upper().strip()
        if raw.endswith(quote):
            base = raw[: -len(quote)]
            if base:
                return f"{base}/{quote}"
        return raw

    def _exchange_info(self) -> dict[str, dict[str, Any]]:
        """Cached map ``BTCUSDT -> raw symbol record``."""

        now = time.monotonic()
        if self._exchange_info_cache is not None and (now - self._exchange_info_fetched_at) < 600:
            return self._exchange_info_cache
        payload = self._public_get("/api/v3/exchangeInfo")
        symbols: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            symbols = list(payload.get("symbols") or [])
        cache: dict[str, dict[str, Any]] = {}
        for record in symbols:
            symbol = str(record.get("symbol", "")).upper()
            if not symbol:
                continue
            cache[symbol] = record
        self._exchange_info_cache = cache
        self._exchange_info_fetched_at = now
        return cache

    def _symbol_filters(self, symbol: str) -> dict[str, dict[str, Any]]:
        record = self._exchange_info().get(self.normalize_symbol(symbol)) or {}
        out: dict[str, dict[str, Any]] = {}
        for entry in record.get("filters") or []:
            filter_type = str(entry.get("filterType") or "").upper()
            if filter_type:
                out[filter_type] = dict(entry)
        return out

    def _step_size(self, symbol: str) -> float:
        filters = self._symbol_filters(symbol)
        lot = filters.get("LOT_SIZE") or {}
        try:
            step = float(lot.get("stepSize") or 0.0)
        except (TypeError, ValueError):
            step = 0.0
        return step or 0.000001

    def _tick_size(self, symbol: str) -> float:
        filters = self._symbol_filters(symbol)
        price_filter = filters.get("PRICE_FILTER") or {}
        try:
            tick = float(price_filter.get("tickSize") or 0.0)
        except (TypeError, ValueError):
            tick = 0.0
        return tick or 0.00000001

    @staticmethod
    def _quantize(value: float, increment: float) -> float:
        if increment <= 0:
            return value
        # Decimal arithmetic so the result lands exactly on the tick grid —
        # float math here produces values like 69196.04000000001 that Binance
        # rejects with -1111 "too much precision".
        inc = Decimal(str(increment))
        val = Decimal(str(value))
        return float((val / inc).to_integral_value(rounding=ROUND_DOWN) * inc)

    # -- public, high-level API mirroring AlpacaClient --------------------

    @retry()
    def get_account(self) -> dict[str, Any]:
        self.logger.debug("Fetching Binance account details")
        return self._signed_request("GET", "/api/v3/account") or {}

    def _account_balances(self) -> list[dict[str, Any]]:
        account = self.get_account()
        balances = account.get("balances") if isinstance(account, dict) else None
        if not isinstance(balances, list):
            return []
        return balances

    def get_available_cash(self) -> float:
        quote = (self.config.binance_quote_currency or "USDT").upper().strip()
        for balance in self._account_balances():
            if str(balance.get("asset", "")).upper() == quote:
                free = _coerce_float(balance.get("free"))
                return float(free or 0.0)
        return 0.0

    def get_account_equity(self) -> float:
        """Sum of ``free + locked`` balances priced in the quote currency.

        Spot wallets across many small assets are valued via their pair price
        against the quote currency; assets that don't have a pair (e.g. an
        airdropped token without a USDT market) are ignored. Cash sitting in
        the quote currency itself is summed at face value.
        """

        quote = (self.config.binance_quote_currency or "USDT").upper().strip()
        balances = self._account_balances()
        total = 0.0
        for balance in balances:
            asset = str(balance.get("asset", "")).upper()
            if not asset:
                continue
            free = _coerce_float(balance.get("free")) or 0.0
            locked = _coerce_float(balance.get("locked")) or 0.0
            amount = free + locked
            if amount <= 0:
                continue
            if asset == quote:
                total += amount
                continue
            symbol = f"{asset}{quote}"
            try:
                price = self._latest_pair_price(symbol)
            except BinanceAPIError:
                # No direct pair against the quote currency — skip.
                continue
            if price > 0:
                total += amount * price
        return round(total, 8)

    @retry()
    def list_assets(self, asset_class: str) -> list[_AssetRecord]:
        """Return the list of tradable spot pairs.

        ``asset_class`` is accepted for parity with the Alpaca interface but
        only ``CRYPTO`` is supported on Binance Spot — anything else returns
        an empty list so universe-side STOCK code paths remain harmless.
        """

        if (asset_class or "").upper() != "CRYPTO":
            return []
        info = self._exchange_info()
        quote = (self.config.binance_quote_currency or "USDT").upper().strip()
        out: list[_AssetRecord] = []
        for symbol, record in info.items():
            quote_asset = str(record.get("quoteAsset") or "").upper()
            if quote_asset != quote:
                continue
            base_asset = str(record.get("baseAsset") or "").upper()
            status = str(record.get("status") or "").upper()
            tradable = status == "TRADING" and bool(record.get("isSpotTradingAllowed"))
            permissions = record.get("permissions") or []
            if isinstance(permissions, list) and permissions and "SPOT" not in permissions:
                tradable = False
            display = f"{base_asset}/{quote_asset}" if base_asset and quote_asset else symbol
            out.append(
                _AssetRecord(
                    symbol=display,
                    name=base_asset or symbol,
                    status=status.lower(),
                    tradable=tradable,
                    fractionable=True,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                )
            )
        out.sort(key=lambda a: a.symbol)
        return out

    @retry()
    def list_orders(self, status: Any = None, nested: bool = False) -> list[_OrderRecord]:
        rows = self._signed_request("GET", "/api/v3/openOrders") or []
        return [_OrderRecord(row) for row in rows if isinstance(row, dict)]

    @retry()
    def get_order(self, order_id: str) -> _OrderRecord:
        # Binance requires ``symbol`` to query an order. We don't have it
        # here, so we look up via the orderId index (we retain the mapping
        # via client_order_id → symbol in the wrapper). When the trade
        # manager calls us, it does so with the order's id and the trade
        # row carries the symbol; pass-through helpers in trade_manager
        # supply that context. As a fallback we scan open orders.
        for row in self._signed_request("GET", "/api/v3/openOrders") or []:
            if str(row.get("orderId")) == str(order_id) or str(row.get("clientOrderId")) == str(order_id):
                return _OrderRecord(row)
        raise BinanceAPIError(404, f"Order {order_id} not found")

    def get_order_for_symbol(self, symbol: str, order_id: str) -> _OrderRecord:
        params = {"symbol": self.normalize_symbol(symbol)}
        if str(order_id).isdigit():
            params["orderId"] = int(order_id)
        else:
            params["origClientOrderId"] = str(order_id)
        raw = self._signed_request("GET", "/api/v3/order", params=params) or {}
        return _OrderRecord(raw)

    @retry()
    def get_open_position(self, symbol: str) -> _AssetRecord | None:
        """Return a synthetic "position" object when the asset balance > 0.

        We expose ``qty`` / ``current_price`` / ``avg_entry_price`` so
        callers in :mod:`services.trade_manager` can use the same access
        pattern they use for Alpaca positions.
        """

        normalized = self.normalize_symbol(symbol)
        info = self._exchange_info().get(normalized) or {}
        base_asset = str(info.get("baseAsset") or "").upper()
        if not base_asset and normalized:
            quote = (self.config.binance_quote_currency or "USDT").upper().strip()
            if normalized.endswith(quote):
                base_asset = normalized[: -len(quote)]
        if not base_asset:
            return None
        for balance in self._account_balances():
            asset = str(balance.get("asset", "")).upper()
            if asset != base_asset:
                continue
            free = _coerce_float(balance.get("free")) or 0.0
            locked = _coerce_float(balance.get("locked")) or 0.0
            qty = free + locked
            if qty <= 0:
                return None
            try:
                current_price = self._latest_pair_price(normalized)
            except BinanceAPIError:
                current_price = 0.0
            return _Position(
                symbol=symbol,
                qty=qty,
                current_price=current_price,
                avg_entry_price=current_price or 0.0,
            )
        return None

    def _latest_pair_price(self, symbol: str) -> float:
        normalized = self.normalize_symbol(symbol)
        payload = self._public_get("/api/v3/ticker/price", params={"symbol": normalized})
        if not isinstance(payload, dict):
            raise BinanceAPIError(0, f"Unexpected price payload for {normalized}")
        price = _coerce_float(payload.get("price"))
        if not price or price <= 0:
            raise BinanceAPIError(404, f"Latest price unavailable for {normalized}")
        return float(price)

    @retry()
    def get_latest_price(self, symbol: str, category: str) -> float:
        return self._latest_pair_price(symbol)

    @retry()
    def get_latest_quote(self, symbol: str, category: str) -> dict[str, float | None]:
        normalized = self.normalize_symbol(symbol)
        payload = self._public_get("/api/v3/ticker/bookTicker", params={"symbol": normalized})
        if not isinstance(payload, dict):
            raise BinanceAPIError(0, f"Unexpected quote payload for {normalized}")
        return {
            "bid_price": _coerce_float(payload.get("bidPrice")),
            "ask_price": _coerce_float(payload.get("askPrice")),
            "bid_size": _coerce_float(payload.get("bidQty")),
            "ask_size": _coerce_float(payload.get("askQty")),
        }

    @retry()
    def cancel_order(self, order_id: str) -> None:
        # Binance requires ``symbol`` to cancel; the trade_manager passes
        # the order through this method from a row that knows the symbol,
        # so the dispatcher there calls :meth:`cancel_order_for_symbol`
        # directly. This shim is kept for parity with the Alpaca interface.
        raise BinanceAPIError(400, "Use cancel_order_for_symbol on Binance")

    def cancel_order_for_symbol(self, symbol: str, order_id: str) -> None:
        params = {"symbol": self.normalize_symbol(symbol)}
        if str(order_id).isdigit():
            params["orderId"] = int(order_id)
        else:
            params["origClientOrderId"] = str(order_id)
        self.logger.info("Cancelling Binance order %s for %s", order_id, symbol)
        self._signed_request("DELETE", "/api/v3/order", params=params)

    def supports_advanced_orders(self, category: str, quantity: float | None = None) -> bool:
        return False

    def supports_broker_side_trailing_stop(self, category: str, quantity: float | None = None) -> bool:
        return False

    def cancel_order_chain(self, order_id: str) -> None:
        # No bracket legs on Binance Spot — nothing to cascade.
        return None

    def replace_bracket_exit_orders(
        self,
        parent_order_id: str,
        take_profit: float | None = None,
        stop_loss: float | None = None,
    ) -> dict[str, Any]:
        # No-op on Binance — TP/SL are handled script-side.
        return {}

    def _resolve_reference_price(self, symbol: str, target_entry_price: float) -> tuple[float, dict[str, float | None]]:
        quote: dict[str, float | None] = {}
        try:
            quote = self.get_latest_quote(symbol, "CRYPTO")
        except Exception as exc:
            self.logger.warning(
                "Could not fetch latest Binance quote for %s; falling back to latest trade price: %s",
                symbol,
                exc,
            )
        ask_price = float(quote.get("ask_price") or 0.0) if quote else 0.0
        if ask_price > 0:
            return ask_price, quote
        return self.get_latest_price(symbol, "CRYPTO"), quote

    def _round_limit_price(self, price: float, symbol: str) -> float:
        tick = self._tick_size(symbol)
        if tick <= 0:
            return float(price)
        return round(self._quantize(price, tick), 12)

    def _calculate_quantity(self, symbol: str, price: float, allocated_capital: float) -> float:
        if price <= 0:
            raise ValueError("price must be positive")
        raw = allocated_capital / price
        step = self._step_size(symbol)
        return self._quantize(raw, step)

    def _entry_collar_bps(self) -> int:
        return int(self.config.binance_entry_limit_collar_bps)

    def _entry_max_chase_bps(self) -> int:
        return int(self.config.binance_entry_max_chase_bps)

    @retry()
    def place_limit_entry_order(
        self,
        symbol: str,
        category: str,
        entry_price: float,
        allocated_capital: float,
    ) -> dict[str, Any]:
        live_reference_price, quote = self._resolve_reference_price(symbol, entry_price)
        max_acceptable = entry_price * (1 + (self._entry_max_chase_bps() / 10_000.0))
        if live_reference_price > max_acceptable:
            raise ValueError(
                f"Live ask {live_reference_price:.8f} is too far above target {entry_price:.8f} for {symbol}"
            )
        marketable_limit = max(
            entry_price,
            live_reference_price * (1 + (self._entry_collar_bps() / 10_000.0)),
        )
        submitted_entry_price = self._round_limit_price(marketable_limit, symbol)
        qty = self._calculate_quantity(symbol, submitted_entry_price, allocated_capital)
        if qty <= 0:
            raise ValueError(
                f"Allocated capital {allocated_capital} is insufficient to buy any quantity of {symbol} at {submitted_entry_price}"
            )
        normalized = self.normalize_symbol(symbol)
        client_order_id = f"entry-{normalized}-{uuid4().hex[:18]}".replace("/", "-")
        # Binance Spot supports ``timeInForce=IOC`` for LIMIT orders, mirroring
        # Alpaca's marketable-IOC entry behavior for crypto.
        params = {
            "symbol": normalized,
            "side": "BUY",
            "type": "LIMIT",
            "timeInForce": "IOC",
            "quantity": _format_decimal(qty),
            "price": _format_decimal(submitted_entry_price),
            "newClientOrderId": client_order_id,
            "newOrderRespType": "FULL",
        }
        self.logger.info(
            "Submitting marketable Binance IOC entry for %s at limit %s (target %s, live %s)",
            symbol,
            submitted_entry_price,
            entry_price,
            live_reference_price,
        )
        raw = self._signed_request("POST", "/api/v3/order", params=params) or {}
        order = _OrderRecord(raw)
        return {
            "order": order,
            "quantity": qty,
            "client_order_id": client_order_id,
            "submitted_entry_price": submitted_entry_price,
            "target_entry_price": entry_price,
            "live_quote": quote,
        }

    @retry()
    def place_limit_bracket_order(
        self,
        symbol: str,
        category: str,
        entry_price: float,
        take_profit: float,
        stop_loss: float,
        allocated_capital: float,
    ) -> dict[str, Any]:
        # No native brackets on Spot — the bot manages TP/SL itself.
        return self.place_limit_entry_order(
            symbol=symbol,
            category=category,
            entry_price=entry_price,
            allocated_capital=allocated_capital,
        )

    @retry()
    def place_market_exit_order(self, symbol: str, quantity: float, category: str) -> _OrderRecord:
        normalized = self.normalize_symbol(symbol)
        step = self._step_size(symbol)
        qty = self._quantize(float(quantity), step) if step else float(quantity)
        if qty <= 0:
            raise ValueError(f"Cannot submit Binance exit for {symbol} with non-positive quantity")
        client_order_id = f"exit-{normalized}-{uuid4().hex[:18]}".replace("/", "-")
        params = {
            "symbol": normalized,
            "side": "SELL",
            "type": "MARKET",
            "quantity": _format_decimal(qty),
            "newClientOrderId": client_order_id,
            "newOrderRespType": "FULL",
        }
        self.logger.info("Submitting Binance market exit for %s qty=%s", symbol, qty)
        raw = self._signed_request("POST", "/api/v3/order", params=params) or {}
        return _OrderRecord(raw)

    @retry()
    def close_position_market(self, symbol: str) -> _OrderRecord:
        position = self.get_open_position(symbol)
        if position is None:
            raise BinanceAPIError(404, f"No open Binance position for {symbol}")
        return self.place_market_exit_order(symbol, float(position.qty), "CRYPTO")

    @retry()
    def get_multi_bars(
        self,
        symbols: list[str],
        category: str,
        start: datetime,
        end: datetime | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        end = end or utc_now()
        normalized_inputs = [str(s).upper().strip() for s in symbols if str(s).strip()]
        if not normalized_inputs:
            return {}
        out: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in normalized_inputs}
        for symbol in normalized_inputs:
            try:
                out[symbol] = self._get_klines(symbol, start, end)
            except BinanceAPIError as exc:
                self.logger.warning("Binance klines failed for %s: %s", symbol, exc)
                out[symbol] = []
        return out

    @retry()
    def get_bars(self, symbol: str, category: str, start: datetime, end: datetime | None = None) -> list[dict[str, Any]]:
        normalized = str(symbol).upper().strip()
        return self.get_multi_bars([normalized], category, start, end).get(normalized, [])

    def _get_klines(self, symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        normalized = self.normalize_symbol(symbol)
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)
        cursor = start_ms
        rows: list[dict[str, Any]] = []
        while cursor < end_ms:
            params = {
                "symbol": normalized,
                "interval": "1d",
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }
            payload = self._public_get("/api/v3/klines", params=params)
            if not isinstance(payload, list) or not payload:
                break
            for candle in payload:
                if not isinstance(candle, list) or len(candle) < 6:
                    continue
                ts_ms, open_p, high_p, low_p, close_p, volume_p = candle[:6]
                rows.append(
                    {
                        "symbol": symbol,
                        "timestamp": _epoch_ms_to_isoformat(ts_ms) or "",
                        "open": float(open_p),
                        "high": float(high_p),
                        "low": float(low_p),
                        "close": float(close_p),
                        "volume": float(volume_p),
                    }
                )
            last_ts = int(payload[-1][0])
            if last_ts <= cursor:
                break
            cursor = last_ts + 1
            if len(payload) < 1000:
                break
        return rows

    @retry()
    def get_24h_ticker(self) -> list[dict[str, Any]]:
        """Top-of-day stats across every Binance pair (used by universe selection)."""

        payload = self._public_get("/api/v3/ticker/24hr")
        if not isinstance(payload, list):
            return []
        return [row for row in payload if isinstance(row, dict)]

    def infer_close_reason(self, order: Any) -> str:
        order_type = str(getattr(order, "type", "")).lower()
        status = str(getattr(order, "status", "")).lower()
        if "stop" in order_type and status == "filled":
            return "STOP_LOSS"
        if "limit" in order_type and status == "filled":
            return "TAKE_PROFIT"
        return "GPT_SIGNAL"


class _Position:
    """Synthetic position object that mirrors the Alpaca attributes the bot reads."""

    __slots__ = ("symbol", "qty", "current_price", "avg_entry_price", "asset_id")

    def __init__(self, symbol: str, qty: float, current_price: float, avg_entry_price: float) -> None:
        self.symbol = symbol
        self.qty = qty
        self.current_price = current_price
        self.avg_entry_price = avg_entry_price
        self.asset_id = symbol


def _format_decimal(value: float) -> str:
    """Stringify a float without scientific notation for Binance's API.

    Goes through ``Decimal(str(value))`` so the output reflects Python's
    shortest-roundtrip repr of the float, not its full binary expansion —
    otherwise a quantized price like ``69196.04`` leaks back as
    ``69196.040000000001`` and Binance rejects it with ``-1111`` ("price has
    too much precision").
    """

    if value == 0:
        return "0"
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    text = format(dec, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
