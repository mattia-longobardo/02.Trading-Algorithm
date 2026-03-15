"""Alpaca trading and market data client wrappers."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, OrderClass, OrderSide, OrderStatus, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetAssetsRequest, GetOrdersRequest, LimitOrderRequest, MarketOrderRequest, ReplaceOrderRequest, StopLossRequest, TakeProfitRequest

from utils import AppConfig, retry, utc_now


class AlpacaClient:
    """Thin wrapper around alpaca-py with retries and normalization."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger.getChild("alpaca")
        self.trading_client = TradingClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
            paper=config.paper,
            raw_data=False,
        )
        self.stock_data_client = StockHistoricalDataClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
        )
        self.crypto_data_client = CryptoHistoricalDataClient(
            api_key=config.alpaca_api_key,
            secret_key=config.alpaca_secret_key,
        )

    @retry()
    def get_account(self) -> Any:
        self.logger.debug("Fetching Alpaca account details")
        return self.trading_client.get_account()

    def get_available_cash(self) -> float:
        account = self.get_account()
        return float(getattr(account, "cash", 0.0) or 0.0)

    @retry()
    def list_assets(self, asset_class: str) -> list[Any]:
        request = GetAssetsRequest(asset_class=AssetClass[asset_class])
        self.logger.debug("Listing Alpaca assets for class %s", asset_class)
        return self.trading_client.get_all_assets(request)

    @retry()
    def list_orders(self, status: QueryOrderStatus = QueryOrderStatus.ALL, nested: bool = True) -> list[Any]:
        request = GetOrdersRequest(status=status, nested=nested, after=utc_now() - timedelta(days=30))
        return self.trading_client.get_orders(filter=request)

    @retry()
    def get_order(self, order_id: str) -> Any:
        self.logger.debug("Fetching order %s", order_id)
        return self.trading_client.get_order_by_id(order_id, nested=True)

    @retry()
    def get_open_position(self, symbol: str) -> Any | None:
        try:
            return self.trading_client.get_open_position(symbol)
        except Exception as exc:
            if "position does not exist" in str(exc).lower():
                return None
            raise

    @retry()
    def close_position_market(self, symbol: str) -> Any:
        self.logger.info("Closing position at market for %s", symbol)
        return self.trading_client.close_position(symbol)

    @retry()
    def cancel_order(self, order_id: str) -> None:
        self.logger.info("Cancelling order %s", order_id)
        self.trading_client.cancel_order_by_id(order_id)

    @retry()
    def replace_order(self, order_id: str, limit_price: float | None = None, stop_price: float | None = None) -> Any:
        self.logger.info("Replacing order %s", order_id)
        request = ReplaceOrderRequest(limit_price=limit_price, stop_price=stop_price)
        return self.trading_client.replace_order_by_id(order_id, order_data=request)

    def _time_in_force_for_category(self, category: str) -> TimeInForce:
        return TimeInForce.GTC if category == "CRYPTO" else TimeInForce.DAY

    def _calculate_quantity(self, symbol_price: float, allocated_capital: float) -> float:
        if symbol_price <= 0:
            raise ValueError("symbol_price must be positive")
        raw_qty = allocated_capital / symbol_price
        return math.floor(raw_qty * 1000000) / 1000000

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
        qty = self._calculate_quantity(entry_price, allocated_capital)
        client_order_id = f"bot-{symbol.replace('/', '-')}-{uuid4().hex[:18]}"
        order = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=self._time_in_force_for_category(category),
            limit_price=entry_price,
            order_class=OrderClass.BRACKET,
            take_profit=TakeProfitRequest(limit_price=take_profit),
            stop_loss=StopLossRequest(stop_price=stop_loss),
            client_order_id=client_order_id,
            extended_hours=False,
        )
        self.logger.info("Submitting bracket order for %s (%s)", symbol, category)
        submitted = self.trading_client.submit_order(order_data=order)
        return {"order": submitted, "quantity": qty, "client_order_id": client_order_id}

    @retry()
    def place_market_exit_order(self, symbol: str, quantity: float, category: str) -> Any:
        order = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            time_in_force=self._time_in_force_for_category(category),
            client_order_id=f"exit-{symbol.replace('/', '-')}-{uuid4().hex[:18]}",
        )
        self.logger.info("Submitting market exit order for %s", symbol)
        return self.trading_client.submit_order(order_data=order)

    @retry()
    def get_bars(self, symbol: str, category: str, start: datetime, end: datetime | None = None) -> list[dict[str, Any]]:
        end = end or utc_now()
        if category == "STOCK":
            request = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start, end=end)
            bars = self.stock_data_client.get_stock_bars(request)
        else:
            request = CryptoBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day, start=start, end=end)
            bars = self.crypto_data_client.get_crypto_bars(request)

        frame = bars.df.reset_index() if hasattr(bars, "df") else []
        normalized: list[dict[str, Any]] = []
        if len(frame) == 0:
            return normalized
        for _, row in frame.iterrows():
            normalized.append(
                {
                    "symbol": symbol,
                    "timestamp": row["timestamp"].to_pydatetime().astimezone(UTC).isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
        self.logger.debug("Downloaded %s bars for %s", len(normalized), symbol)
        return normalized

    def infer_close_reason(self, order: Any) -> str:
        """Infer the close reason from nested orders when possible."""

        legs = getattr(order, "legs", None) or []
        for leg in legs:
            leg_type = str(getattr(leg, "type", "")).lower()
            status = str(getattr(leg, "status", "")).lower()
            if status != str(OrderStatus.FILLED).lower():
                continue
            if "limit" in leg_type:
                return "TAKE_PROFIT"
            if "stop" in leg_type:
                return "STOP_LOSS"
        return "GPT_SIGNAL"

    def supports_eur(self, symbol: str) -> bool:
        """Best-effort currency support check."""

        if self.config.currency != "EUR":
            return False
        if "/" in symbol and symbol.endswith("/USD"):
            return False
        return False
