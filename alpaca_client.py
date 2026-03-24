"""Alpaca trading and market data client wrappers."""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from alpaca.common.exceptions import APIError
from alpaca.data.historical.crypto import CryptoHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.enums import DataFeed
from alpaca.data.requests import CryptoBarsRequest, CryptoLatestTradeRequest, StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetClass, OrderClass, OrderSide, OrderStatus, OrderType, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetAssetsRequest, GetOrderByIdRequest, GetOrdersRequest, LimitOrderRequest, MarketOrderRequest, ReplaceOrderRequest, StopLossRequest, TakeProfitRequest, TrailingStopOrderRequest

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
        non_marginable_buying_power = float(getattr(account, "non_marginable_buying_power", 0.0) or 0.0)
        cash = float(getattr(account, "cash", 0.0) or 0.0)
        if non_marginable_buying_power > 0:
            return min(non_marginable_buying_power, cash) if cash > 0 else non_marginable_buying_power
        return cash

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
        return self.trading_client.get_order_by_id(order_id, filter=GetOrderByIdRequest(nested=True))

    @staticmethod
    def _normalized_symbol_key(symbol: str) -> str:
        return str(symbol).replace("/", "").upper().strip()

    def _position_matches_symbol(self, position: Any, symbol: str) -> bool:
        candidate_keys = {
            self._normalized_symbol_key(symbol),
            str(symbol).upper().strip(),
        }
        for attr_name in ("symbol", "asset_symbol"):
            value = getattr(position, attr_name, None)
            if value and self._normalized_symbol_key(str(value)) in candidate_keys:
                return True
        return False

    @staticmethod
    def _is_missing_position_error(exc: Exception) -> bool:
        if isinstance(exc, APIError) and exc.status_code == 404:
            return True
        message = str(exc).lower()
        return (
            "position does not exist" in message
            or "symbol not found" in message
            or "not found" in message
        )

    @staticmethod
    def is_insufficient_balance_error(exc: Exception) -> bool:
        if isinstance(exc, APIError):
            try:
                if exc.code == 40310000:
                    return True
            except Exception:
                pass
        return "insufficient balance" in str(exc).lower()

    @retry()
    def list_open_positions(self) -> list[Any]:
        self.logger.debug("Listing Alpaca open positions")
        return self.trading_client.get_all_positions()

    def _find_open_position_by_scan(self, symbol: str) -> Any | None:
        for position in self.list_open_positions():
            if self._position_matches_symbol(position, symbol):
                return position
        return None

    @retry()
    def get_open_position(self, symbol: str) -> Any | None:
        if "/" in symbol:
            return self._find_open_position_by_scan(symbol)
        try:
            return self.trading_client.get_open_position(symbol)
        except Exception as exc:
            if self._is_missing_position_error(exc):
                scanned = self._find_open_position_by_scan(symbol)
                if scanned is not None:
                    return scanned
                return None
            raise

    @retry()
    def get_latest_price(self, symbol: str, category: str) -> float:
        self.logger.debug("Fetching latest price for %s (%s)", symbol, category)
        if category == "STOCK":
            request = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=DataFeed.IEX)
            response = self.stock_data_client.get_stock_latest_trade(request)
        else:
            request = CryptoLatestTradeRequest(symbol_or_symbols=symbol)
            response = self.crypto_data_client.get_crypto_latest_trade(request)

        if isinstance(response, dict):
            trade = response.get(symbol) or response.get(str(symbol).upper())
        else:
            trade = response
        price = getattr(trade, "price", None)
        if price is None:
            raise ValueError(f"Latest price unavailable for {symbol}")
        return float(price)

    @retry()
    def close_position_market(self, symbol: str) -> Any:
        self.logger.info("Closing position at market for %s", symbol)
        if "/" in symbol:
            position = self._find_open_position_by_scan(symbol)
            asset_id = getattr(position, "asset_id", None) if position is not None else None
            if asset_id:
                return self.trading_client.close_position(str(asset_id))
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

    def _order_type_name(self, order: Any) -> str:
        return str(getattr(order, "type", getattr(order, "order_type", ""))).lower()

    def _order_status_name(self, order: Any) -> str:
        status = getattr(order, "status", "")
        return str(getattr(status, "value", status)).lower()

    def _is_cancelable_order(self, order: Any) -> bool:
        return self._order_status_name(order) not in {"filled", "canceled", "cancelled", "expired", "rejected", "replaced"}

    def _classify_exit_leg(self, order: Any) -> str | None:
        order_type = self._order_type_name(order)
        if "stop" in order_type:
            return "stop_loss"
        if "limit" in order_type:
            return "take_profit"
        return None

    def get_order_legs(self, order_id: str) -> dict[str, Any]:
        order = self.get_order(order_id)
        classified: dict[str, Any] = {"parent": order}
        for leg in getattr(order, "legs", None) or []:
            leg_kind = self._classify_exit_leg(leg)
            if leg_kind and leg_kind not in classified:
                classified[leg_kind] = leg
        return classified

    def cancel_order_chain(self, order_id: str) -> None:
        orders = self.get_order_legs(order_id)
        for leg_name in ("take_profit", "stop_loss"):
            leg = orders.get(leg_name)
            if leg and self._is_cancelable_order(leg):
                self.cancel_order(str(getattr(leg, "id")))
        parent = orders["parent"]
        if self._is_cancelable_order(parent):
            self.cancel_order(str(getattr(parent, "id")))

    def replace_bracket_exit_orders(
        self,
        parent_order_id: str,
        take_profit: float | None = None,
        stop_loss: float | None = None,
    ) -> dict[str, Any]:
        orders = self.get_order_legs(parent_order_id)
        replacements: dict[str, Any] = {}
        if take_profit is not None:
            take_profit_leg = orders.get("take_profit")
            if take_profit_leg is None:
                raise ValueError(f"Bracket order {parent_order_id} has no take-profit leg to replace")
            replacements["take_profit"] = self.replace_order(
                str(getattr(take_profit_leg, "id")),
                limit_price=take_profit,
            )
        if stop_loss is not None:
            stop_loss_leg = orders.get("stop_loss")
            if stop_loss_leg is None:
                raise ValueError(f"Bracket order {parent_order_id} has no stop-loss leg to replace")
            replacements["stop_loss"] = self.replace_order(
                str(getattr(stop_loss_leg, "id")),
                stop_price=stop_loss,
            )
        return replacements

    def _time_in_force_for_category(self, category: str) -> TimeInForce:
        return TimeInForce.GTC if category == "CRYPTO" else TimeInForce.DAY

    def _protection_time_in_force_for_category(self, category: str) -> TimeInForce:
        return TimeInForce.GTC

    def _calculate_quantity(self, symbol_price: float, allocated_capital: float, category: str) -> float:
        if symbol_price <= 0:
            raise ValueError("symbol_price must be positive")
        raw_qty = allocated_capital / symbol_price
        if category == "STOCK":
            return math.floor(raw_qty * 1000000) / 1000000
        return math.floor(raw_qty * 1000000) / 1000000

    def supports_advanced_orders(self, category: str, quantity: float | None = None) -> bool:
        if category == "CRYPTO":
            return False
        if quantity is None:
            return True
        return float(quantity).is_integer()

    def supports_broker_side_trailing_stop(self, category: str, quantity: float | None = None) -> bool:
        if category == "CRYPTO":
            return False
        if quantity is None:
            return True
        return float(quantity).is_integer()

    @retry()
    def place_limit_entry_order(
        self,
        symbol: str,
        category: str,
        entry_price: float,
        allocated_capital: float,
    ) -> dict[str, Any]:
        qty = self._calculate_quantity(entry_price, allocated_capital, category)
        if qty <= 0:
            raise ValueError(f"Allocated capital {allocated_capital} is insufficient to buy any quantity of {symbol} at {entry_price}")
        client_order_id = f"entry-{symbol.replace('/', '-')}-{uuid4().hex[:18]}"
        order = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=self._time_in_force_for_category(category),
            limit_price=entry_price,
            client_order_id=client_order_id,
        )
        self.logger.info("Submitting simple limit entry order for %s (%s)", symbol, category)
        submitted = self.trading_client.submit_order(order_data=order)
        return {"order": submitted, "quantity": qty, "client_order_id": client_order_id}

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
        qty = self._calculate_quantity(entry_price, allocated_capital, category)
        if qty <= 0:
            raise ValueError(f"Allocated capital {allocated_capital} is insufficient to buy any quantity of {symbol} at {entry_price}")
        client_order_id = f"bot-{symbol.replace('/', '-')}-{uuid4().hex[:18]}"
        if self.supports_advanced_orders(category, qty):
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
        else:
            order = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=OrderSide.BUY,
                time_in_force=self._time_in_force_for_category(category),
                limit_price=entry_price,
                client_order_id=client_order_id,
            )
            self.logger.info(
                "Submitting simple limit entry for %s (%s); advanced bracket order not available for this quantity/category",
                symbol,
                category,
            )
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
    def place_trailing_stop_order(self, symbol: str, quantity: float, category: str, trail_price: float) -> dict[str, Any]:
        if trail_price <= 0:
            raise ValueError("trail_price must be positive")
        client_order_id = f"trail-{symbol.replace('/', '-')}-{uuid4().hex[:18]}"
        order = TrailingStopOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=OrderSide.SELL,
            type=OrderType.TRAILING_STOP,
            time_in_force=self._protection_time_in_force_for_category(category),
            trail_price=trail_price,
            client_order_id=client_order_id,
        )
        self.logger.info("Submitting trailing stop order for %s with trail price %s", symbol, trail_price)
        submitted = self.trading_client.submit_order(order_data=order)
        return {"order": submitted, "client_order_id": client_order_id}

    @retry()
    def replace_trailing_stop_order(self, order_id: str, trail_price: float) -> Any:
        if trail_price <= 0:
            raise ValueError("trail_price must be positive")
        self.logger.info("Replacing trailing stop order %s with trail price %s", order_id, trail_price)
        request = ReplaceOrderRequest(trail=trail_price)
        return self.trading_client.replace_order_by_id(order_id, order_data=request)

    @retry()
    def get_bars(self, symbol: str, category: str, start: datetime, end: datetime | None = None) -> list[dict[str, Any]]:
        end = end or utc_now()
        if category == "STOCK":
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start,
                end=end,
                feed=DataFeed.IEX,
            )
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

        order_type = self._order_type_name(order)
        if "trailing" in order_type and self._order_status_name(order) == str(OrderStatus.FILLED).lower():
            return "TRAILING_STOP"
        legs = getattr(order, "legs", None) or []
        for leg in legs:
            leg_type = self._order_type_name(leg)
            status = self._order_status_name(leg)
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
