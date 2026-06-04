"""Trading workflow orchestration and script-managed trade persistence.

Multi-provider aware: every trade row carries a ``provider`` tag and the
manager dispatches all broker calls (entry order, position lookup, exit,
quote refresh, …) to the right client. The lifecycle logic itself
(TP / SL / trailing TP / trailing stop / GPT batch decisions) is shared.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Mapping

from clients.gpt_client import GPTClient
from core.db import db_cursor, fetch_all, fetch_one
from core.utils import (
    PROVIDER_ETORO,
    AppConfig,
    isoformat_utc,
    parse_datetime,
    utc_now,
)
from services.data_manager import DataManager


class TradeManager:
    """Coordinate broker orders, DB state, and GPT entry decisions."""

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        broker_clients: Mapping[str, Any] | None = None,
        data_manager: DataManager | None = None,
        gpt_client: GPTClient | None = None,
    ) -> None:
        self.config = config
        self.logger = logger.getChild("trade_manager")
        self._brokers: dict[str, Any] = dict(broker_clients) if isinstance(broker_clients, Mapping) else {}
        if data_manager is None:
            raise TypeError("TradeManager requires a data_manager")
        if gpt_client is None:
            raise TypeError("TradeManager requires a gpt_client")
        self.data_manager = data_manager
        self.gpt_client = gpt_client

    @property
    def brokers(self) -> dict[str, Any]:
        return self._brokers

    def broker(self, provider: str) -> Any | None:
        return self._brokers.get(provider)

    def _trade_provider(self, trade: dict[str, Any]) -> str:
        return str(trade.get("provider") or PROVIDER_ETORO).lower()

    def _trade_broker(self, trade: dict[str, Any]) -> Any | None:
        return self.broker(self._trade_provider(trade))

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _minutes_since(timestamp: datetime | None) -> float | None:
        if timestamp is None:
            return None
        return max((utc_now() - timestamp).total_seconds() / 60.0, 0.0)

    def _resolve_current_price(
        self,
        symbol: str,
        category: str,
        position: Any | None = None,
        fallback: float | None = None,
        provider: str = PROVIDER_ETORO,
    ) -> float:
        broker = self.broker(provider)
        try:
            if broker is None:
                raise RuntimeError(f"No broker registered for provider {provider}")
            return broker.get_latest_price(symbol, category)
        except Exception:
            current_price = self._as_float(getattr(position, "current_price", None)) if position is not None else None
            if current_price is not None:
                return current_price
            if fallback is not None:
                return fallback
            raise

    @staticmethod
    def _compute_trailing_stop_price(high_water_mark: float, trailing_stop_distance: float | None) -> float | None:
        if trailing_stop_distance is None or trailing_stop_distance <= 0:
            return None
        return round(high_water_mark - trailing_stop_distance, 8)

    @staticmethod
    def _compute_trailing_take_profit_price(
        high_water_mark: float,
        entry_price: float | None,
        trailing_take_profit_distance: float | None,
        trailing_take_profit_activation_pct: float | None,
        min_profit_buffer_pct: float = 0.0,
    ) -> float | None:
        """Compute the trailing TP trigger, floored at entry + min profit buffer.

        Without the floor, a trade with ``distance > (HWM − entry)`` would
        trigger below the entry price and close at a loss labelled
        ``TRAILING_TAKE_PROFIT``. The floor guarantees that whenever the
        trailing arms it will close, at worst, at a small minimum profit —
        which is what "take profit" is supposed to mean. The signal-side
        validator (`_validate_trailing_take_profit_pair`) keeps the floor
        from ever silently changing GPT's intent on healthy signals.
        """

        if (
            entry_price is None
            or entry_price <= 0
            or trailing_take_profit_distance is None
            or trailing_take_profit_distance <= 0
            or trailing_take_profit_activation_pct is None
            or trailing_take_profit_activation_pct <= 0
        ):
            return None
        activation_threshold = entry_price * (1 + trailing_take_profit_activation_pct / 100.0)
        if high_water_mark < activation_threshold:
            return None
        raw_trigger = high_water_mark - trailing_take_profit_distance
        floor = entry_price * (1 + max(min_profit_buffer_pct, 0.0) / 100.0)
        return round(max(raw_trigger, floor), 8)

    @staticmethod
    def _trailing_take_profit_pair_is_valid(
        entry_price: float | None,
        trailing_take_profit_distance: float | None,
        trailing_take_profit_activation_pct: float | None,
        min_profit_buffer_pct: float,
    ) -> bool:
        """Return True when (activation_pct, distance) lock in a profit at arming.

        Invariant: at the moment the trailing first arms, ``HWM == entry × (1
        + activation_pct/100)`` and the trigger is ``HWM − distance``. We
        require ``trigger ≥ entry × (1 + buffer/100)``, which simplifies to
        ``activation_pct ≥ buffer + (distance / entry) × 100``. A pair that
        violates this would arm with the trigger already below entry (loss
        territory) — the runtime floor would mask it but the trailing would
        not actually "trail" anything, so we reject such pairs at the source.
        """

        if entry_price is None or entry_price <= 0:
            return False
        if trailing_take_profit_distance is None or trailing_take_profit_activation_pct is None:
            # Caller is responsible for the "both null" case; here we only
            # validate when the pair is set.
            return False
        if trailing_take_profit_distance <= 0 or trailing_take_profit_activation_pct <= 0:
            return False
        distance_pct = (trailing_take_profit_distance / entry_price) * 100.0
        return trailing_take_profit_activation_pct >= distance_pct + max(min_profit_buffer_pct, 0.0)

    @staticmethod
    def _downside_close_reason(
        current_price: float,
        stop_loss: float | None,
        trailing_stop_price: float | None,
    ) -> str | None:
        if trailing_stop_price is not None and stop_loss is not None:
            if trailing_stop_price >= stop_loss and current_price <= trailing_stop_price:
                return "TRAILING_STOP"
            if current_price <= stop_loss:
                return "STOP_LOSS"
            if current_price <= trailing_stop_price:
                return "TRAILING_STOP"
            return None
        if stop_loss is not None and current_price <= stop_loss:
            return "STOP_LOSS"
        if trailing_stop_price is not None and current_price <= trailing_stop_price:
            return "TRAILING_STOP"
        return None

    @staticmethod
    def _trailing_take_profit_close_reason(
        current_price: float,
        trailing_take_profit_price: float | None,
    ) -> str | None:
        if trailing_take_profit_price is not None and current_price <= trailing_take_profit_price:
            return "TRAILING_TAKE_PROFIT"
        return None

    def get_trade(self, trade_id: int) -> dict[str, Any] | None:
        return fetch_one(self.config.db_trades, "SELECT * FROM trades WHERE id = ?", (trade_id,))

    def get_open_or_pending_trades(self) -> list[dict[str, Any]]:
        return fetch_all(
            self.config.db_trades,
            "SELECT * FROM trades WHERE status IN ('PENDING', 'OPEN') ORDER BY created_at",
        )

    def get_stale_pending_trades(self, min_age_days: int = 7) -> list[dict[str, Any]]:
        return fetch_all(
            self.config.db_trades,
            """
            SELECT *
            FROM trades
            WHERE status = 'PENDING'
              AND datetime(created_at) <= datetime('now', ?)
            ORDER BY created_at
            """,
            (f"-{int(min_age_days)} days",),
        )

    def get_symbol_trades(self, symbol: str, provider: str | None = None) -> list[dict[str, Any]]:
        if provider:
            return fetch_all(
                self.config.db_trades,
                """
                SELECT * FROM trades
                WHERE symbol = ? AND provider = ? AND status IN ('PENDING', 'OPEN')
                ORDER BY created_at
                """,
                (symbol, provider),
            )
        return fetch_all(
            self.config.db_trades,
            "SELECT * FROM trades WHERE symbol = ? AND status IN ('PENDING', 'OPEN') ORDER BY created_at",
            (symbol,),
        )

    def count_active_trades(self, category: str, provider: str | None = None) -> int:
        if provider:
            row = fetch_one(
                self.config.db_trades,
                """
                SELECT COUNT(*) AS count FROM trades
                WHERE category = ? AND provider = ? AND status IN ('PENDING', 'OPEN')
                """,
                (category, provider),
            )
        else:
            row = fetch_one(
                self.config.db_trades,
                "SELECT COUNT(*) AS count FROM trades WHERE category = ? AND status IN ('PENDING', 'OPEN')",
                (category,),
            )
        return int(row["count"]) if row else 0

    def compute_allocated_capital(self, provider: str = PROVIDER_ETORO) -> float:
        broker = self.broker(provider)
        if broker is None:
            return 0.0
        cash = broker.get_available_cash()
        slots = self.config.max_open_trades_stock + self.config.max_open_trades_crypto
        # The cash pool is shared between STOCK and CRYPTO, so we use the
        # aggregate count of this provider's active trades across categories.
        active = sum(
            1
            for t in self.get_open_or_pending_trades()
            if self._trade_provider(t) == provider
        )
        available_slots = max(slots - active, 1)
        allocated = round(cash / available_slots, 2)
        minimum = float(getattr(self.config, "etoro_min_trade_amount", 0.0) or 0.0)
        if minimum > 0 and 0 < allocated < minimum and cash >= minimum:
            return minimum
        return allocated

    def _cancel_pending_trade_record(
        self,
        trade: dict[str, Any],
        close_reason: str,
        *,
        reasoning: str | None = None,
        close_timestamp: datetime | None = None,
    ) -> None:
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET status = 'CANCELLED', close_reason = ?, close_timestamp = ?, reasoning = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    close_reason,
                    isoformat_utc(close_timestamp or utc_now()),
                    reasoning or trade.get("reasoning"),
                    trade["id"],
                ),
            )

    def _save_new_trade(
        self,
        category: str,
        symbol: str,
        signal: dict[str, Any],
        instrument_id: int,
        allocated_capital: float,
        provider: str = PROVIDER_ETORO,
    ) -> None:
        trailing_take_profit_distance = self._as_float(signal.get("trailing_take_profit_distance"))
        trailing_take_profit_activation_pct = self._as_float(signal.get("trailing_take_profit_activation_pct"))
        trailing_stop_distance = self._as_float(signal.get("trailing_stop_distance"))
        target_entry_price = float(signal["entry_price"])
        provisional_quantity = (allocated_capital / target_entry_price) if target_entry_price > 0 else 0.0
        account_currency = self.config.provider_account_currency(provider)
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                INSERT INTO trades (
                    symbol, category, direction, status, entry_price, target_entry_price, quantity, allocated_capital,
                    take_profit, trailing_take_profit_distance, trailing_take_profit_activation_pct,
                    stop_loss, trailing_stop_distance,
                    instrument_id, reasoning, confidence, trade_score,
                    provider, account_currency
                ) VALUES (?, ?, 'LONG', 'PENDING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    category,
                    target_entry_price,
                    target_entry_price,
                    provisional_quantity,
                    allocated_capital,
                    float(signal["take_profit"]),
                    trailing_take_profit_distance,
                    trailing_take_profit_activation_pct,
                    float(signal["stop_loss"]),
                    trailing_stop_distance,
                    int(instrument_id),
                    signal.get("reasoning"),
                    signal.get("confidence"),
                    self._as_float(signal.get("trade_score")),
                    provider,
                    account_currency,
                ),
            )
        self.logger.info("Stored new pending (emulated-limit) trade for %s on %s", symbol, provider)

    def _signal_has_required_levels(self, signal: dict[str, Any]) -> bool:
        for field in ("entry_price", "take_profit", "stop_loss"):
            value = signal.get(field)
            if not isinstance(value, (int, float)) or float(value) <= 0:
                self.logger.warning(
                    "GPT returned OPEN for %s with invalid %s=%s; skipping trade",
                    signal.get("symbol"),
                    field,
                    value,
                )
                return False
        trailing_take_profit_distance = signal.get("trailing_take_profit_distance")
        if trailing_take_profit_distance is not None:
            if not isinstance(trailing_take_profit_distance, (int, float)) or float(trailing_take_profit_distance) <= 0:
                self.logger.warning(
                    "GPT returned OPEN for %s with invalid trailing_take_profit_distance=%s; skipping trade",
                    signal.get("symbol"),
                    trailing_take_profit_distance,
                )
                return False
        trailing_take_profit_activation_pct = signal.get("trailing_take_profit_activation_pct")
        if trailing_take_profit_activation_pct is not None:
            if not isinstance(trailing_take_profit_activation_pct, (int, float)) or float(trailing_take_profit_activation_pct) <= 0:
                self.logger.warning(
                    "GPT returned OPEN for %s with invalid trailing_take_profit_activation_pct=%s; skipping trade",
                    signal.get("symbol"),
                    trailing_take_profit_activation_pct,
                )
                return False
        if (trailing_take_profit_distance is None) != (trailing_take_profit_activation_pct is None):
            self.logger.warning(
                "GPT returned OPEN for %s with mismatched trailing fields (distance=%s, activation_pct=%s); skipping trade",
                signal.get("symbol"),
                trailing_take_profit_distance,
                trailing_take_profit_activation_pct,
            )
            return False
        if trailing_take_profit_distance is not None and trailing_take_profit_activation_pct is not None:
            entry_price = float(signal["entry_price"])
            min_buffer = float(self.config.trailing_tp_min_profit_buffer_pct)
            if not self._trailing_take_profit_pair_is_valid(
                entry_price,
                float(trailing_take_profit_distance),
                float(trailing_take_profit_activation_pct),
                min_buffer,
            ):
                self.logger.warning(
                    "GPT returned OPEN for %s with a trailing-TP pair that would arm below entry "
                    "(entry=%s, distance=%s ≈ %.3f%%, activation_pct=%s, required min %s%% above distance%%); "
                    "skipping trade",
                    signal.get("symbol"),
                    entry_price,
                    trailing_take_profit_distance,
                    (float(trailing_take_profit_distance) / entry_price) * 100.0 if entry_price > 0 else 0.0,
                    trailing_take_profit_activation_pct,
                    min_buffer,
                )
                return False
        trailing_stop_distance = signal.get("trailing_stop_distance")
        if trailing_stop_distance is None:
            return True
        if not isinstance(trailing_stop_distance, (int, float)) or float(trailing_stop_distance) <= 0:
            self.logger.warning(
                "GPT returned OPEN for %s with invalid trailing_stop_distance=%s; skipping trade",
                signal.get("symbol"),
                trailing_stop_distance,
            )
            return False
        return True

    def _available_trade_slots(self, category: str, provider: str = PROVIDER_ETORO) -> int:
        if category == "STOCK":
            max_trades = int(self.config.max_open_trades_stock)
        else:
            max_trades = int(self.config.max_open_trades_crypto)
        return max(max_trades - self.count_active_trades(category, provider=provider), 0)

    def _build_batch_payloads(
        self,
        category: str,
        symbols: list[str],
        provider: str = PROVIDER_ETORO,
    ) -> list[dict[str, Any]]:
        broker = self.broker(provider)
        payloads: list[dict[str, Any]] = []
        for symbol in symbols:
            if self.get_symbol_trades(symbol, provider=provider):
                self.logger.debug("Skipping %s because an active trade already exists for the symbol", symbol)
                continue
            if broker is not None:
                try:
                    if broker.get_open_position(symbol) is not None:
                        self.logger.debug(
                            "Skipping %s because %s already reports an open position", symbol, provider
                        )
                        continue
                except Exception:
                    self.logger.warning(
                        "Position lookup failed for %s/%s; continuing", provider, symbol, exc_info=True
                    )
            candles = self.data_manager.get_symbol_history(symbol, limit=260)
            if not candles:
                self.logger.warning("No market data found for %s, skipping batch analysis", symbol)
                continue
            payloads.append(self.gpt_client.build_batch_symbol_entry(symbol, candles))
        return payloads

    def _rank_signals(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def sort_key(signal: dict[str, Any]) -> tuple[float, float]:
            score = self._as_float(signal.get("trade_score")) or 0.0
            confidence = self._as_float(signal.get("confidence")) or 0.0
            return (score, confidence)

        return sorted(signals, key=sort_key, reverse=True)

    def _open_trade_from_signal(
        self,
        category: str,
        symbol: str,
        signal: dict[str, Any],
        provider: str = PROVIDER_ETORO,
    ) -> bool:
        if self.get_symbol_trades(symbol, provider=provider):
            self.logger.debug("Skipping %s because an active trade already exists for the symbol", symbol)
            return False
        broker = self.broker(provider)
        if broker is None:
            self.logger.warning("Skipping %s because %s broker is not configured", symbol, provider)
            return False
        try:
            if broker.get_open_position(symbol) is not None:
                self.logger.debug(
                    "Skipping %s because %s already reports an open position", symbol, provider
                )
                return False
        except Exception:
            self.logger.warning(
                "Position lookup failed for %s/%s; continuing", provider, symbol, exc_info=True
            )
        if self._available_trade_slots(category, provider=provider) <= 0:
            self.logger.debug(
                "Skipping %s because no %s/%s slots are available", symbol, provider, category
            )
            return False
        if not self._signal_has_required_levels(signal):
            return False

        allocated_capital = self.compute_allocated_capital(provider=provider)
        if allocated_capital <= 0:
            self.logger.warning("Skipping %s because allocated capital is zero", symbol)
            return False
        instrument_id = broker.instrument_id_for_symbol(symbol)
        if instrument_id is None:
            self.logger.warning("Skipping %s because it is not a tradable %s instrument", symbol, provider)
            return False
        self._save_new_trade(category, symbol, signal, instrument_id, allocated_capital, provider=provider)
        return True

    def maybe_open_trade(self, category: str, symbol: str, provider: str = PROVIDER_ETORO) -> None:
        broker = self.broker(provider)
        if broker is None:
            return
        if self.get_symbol_trades(symbol, provider=provider):
            self.logger.debug("Skipping %s because an active trade already exists for the symbol", symbol)
            return
        try:
            if broker.get_open_position(symbol) is not None:
                self.logger.debug(
                    "Skipping %s because %s already reports an open position", symbol, provider
                )
                return
        except Exception:
            self.logger.warning(
                "Position lookup failed for %s/%s; continuing", provider, symbol, exc_info=True
            )
        if self._available_trade_slots(category, provider=provider) <= 0:
            self.logger.debug(
                "Skipping %s because the max number of active %s/%s trades has been reached",
                symbol,
                provider,
                category,
            )
            return

        candles = self.data_manager.get_symbol_history(symbol)
        if not candles:
            self.logger.warning("No market data found for %s, skipping new trade decision", symbol)
            return

        signal = self.gpt_client.request_new_signal(symbol, category, candles, [], provider=provider)
        if signal["action"] != "OPEN":
            self.logger.debug("GPT skipped %s", symbol)
            return
        self._open_trade_from_signal(category, symbol, signal, provider=provider)

    def _entry_fill_ceiling(self, target_entry_price: float) -> float:
        return target_entry_price * (1 + (int(self.config.crypto_entry_max_chase_bps) / 10_000.0))

    def sync_pending_trade(self, trade: dict[str, Any]) -> None:
        """Emulated limit entry: fill at market once price touches the target.

        No broker order rests while PENDING — each monitor tick polls the rate
        and, when the ask is at/below the target (within the chase tolerance),
        fires a market open and activates the trade. Unfilled trades are
        cancelled (a pure DB state change) once they age past the window.
        """

        broker = self._trade_broker(trade)
        if broker is None:
            return

        existing = broker.get_open_position(trade["symbol"])
        if existing is not None:
            self._activate_trade_from_position(trade, existing, None)
            return

        target = self._as_float(trade.get("target_entry_price")) or self._as_float(trade.get("entry_price"))
        if target is None or target <= 0:
            return

        age_minutes = self._minutes_since(parse_datetime(trade.get("created_at"))) or 0.0
        if age_minutes >= int(self.config.crypto_pending_cancel_minutes):
            self._cancel_pending_trade_record(trade, "ENTRY_TIMEOUT")
            self.logger.info(
                "Cancelled pending trade %s after %s min without touching target", trade["id"], round(age_minutes, 1)
            )
            return

        try:
            quote = broker.get_latest_quote(str(trade["symbol"]), str(trade["category"]))
        except Exception:
            self.logger.warning("Could not fetch quote for pending trade %s", trade["id"], exc_info=True)
            return
        ask = self._as_float(quote.get("ask_price")) or self._as_float(quote.get("bid_price"))
        if ask is None or ask <= 0:
            return
        if ask > self._entry_fill_ceiling(target):
            return  # wait for price to come down to the limit

        instrument_id = int(trade.get("instrument_id") or 0) or broker.instrument_id_for_symbol(trade["symbol"])
        if not instrument_id:
            self._cancel_pending_trade_record(trade, "INSTRUMENT_UNRESOLVED")
            return
        try:
            result = broker.open_market_position(
                instrument_id=int(instrument_id),
                symbol=str(trade["symbol"]),
                amount_usd=float(trade["allocated_capital"]),
                stop_loss_rate=float(trade["stop_loss"]),
                take_profit_rate=float(trade["take_profit"]),
                leverage=int(getattr(self.config, "etoro_default_leverage", 1) or 1),
            )
        except Exception:
            self.logger.exception("Market open failed for pending trade %s; cancelling", trade["id"])
            self._cancel_pending_trade_record(trade, "ENTRY_FAILED")
            return

        position = broker.get_open_position(trade["symbol"])
        self._activate_trade_from_position(trade, position, result)

    def _activate_trade_from_position(
        self, trade: dict[str, Any], position: Any, open_result: dict[str, Any] | None
    ) -> None:
        target = self._as_float(trade.get("target_entry_price")) or self._as_float(trade.get("entry_price")) or 0.0
        pos = position if isinstance(position, dict) else {}
        entry_price = self._as_float(pos.get("open_rate")) or target or float(trade["entry_price"])
        quantity = self._as_float(pos.get("units")) or float(trade["quantity"])
        position_id = str(pos.get("position_id") or (open_result or {}).get("position_id") or "") or None
        reference_id = str((open_result or {}).get("reference_id") or (open_result or {}).get("request_id") or "") or None

        current_price = self._resolve_current_price(
            trade["symbol"], trade["category"], position=None, fallback=entry_price,
            provider=self._trade_provider(trade),
        )
        high_water_mark = max(self._as_float(trade.get("high_water_mark")) or entry_price, entry_price, current_price)
        trailing_stop_price = self._compute_trailing_stop_price(
            high_water_mark, self._as_float(trade.get("trailing_stop_distance"))
        )
        trailing_take_profit_price = self._compute_trailing_take_profit_price(
            high_water_mark, entry_price,
            self._as_float(trade.get("trailing_take_profit_distance")),
            self._as_float(trade.get("trailing_take_profit_activation_pct")),
            self.config.trailing_tp_min_profit_buffer_pct,
        )
        pnl = (current_price - entry_price) * quantity
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET status = 'OPEN', open_timestamp = ?, entry_price = ?, quantity = ?, current_price = ?, pnl = ?,
                    high_water_mark = ?, trailing_take_profit_price = ?, trailing_stop_price = ?,
                    position_id = ?, order_reference_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    isoformat_utc(utc_now()), entry_price, quantity, current_price, pnl,
                    high_water_mark, trailing_take_profit_price, trailing_stop_price,
                    position_id, reference_id, trade["id"],
                ),
            )
        self.logger.info("Trade %s opened on eToro (position %s)", trade["id"], position_id)

    def review_stale_pending_trades(self, min_age_days: int = 7) -> None:
        stale_trades = self.get_stale_pending_trades(min_age_days=min_age_days)
        if not stale_trades:
            self.logger.debug("No stale pending trades found for GPT review")
            return

        for trade in stale_trades:
            try:
                self._review_single_stale_pending_trade(trade)
            except Exception:
                self.logger.exception("Failed to review stale pending trade %s", trade["id"])

    def _review_single_stale_pending_trade(self, trade: dict[str, Any]) -> None:
        symbol = str(trade["symbol"])
        candles = self.data_manager.get_symbol_history(symbol, limit=260)
        if not candles:
            self.logger.warning("No market data found for stale pending trade %s (%s); skipping GPT review", trade["id"], symbol)
            return

        review = self.gpt_client.request_pending_trade_review(
            trade, candles, provider=self._trade_provider(trade)
        )
        action = str(review.get("action", "")).upper()
        reasoning = str(review.get("reasoning", "")).strip()
        self.logger.info(
            "GPT stale pending review for trade %s (%s): %s - %s",
            trade["id"],
            symbol,
            action or "UNKNOWN",
            reasoning or "no reasoning provided",
        )

        if action != "CANCEL":
            return

        # Emulated-limit pending trades hold no resting broker order, so a
        # cancel is a pure record state change.
        self._cancel_pending_trade_record(
            trade,
            "STALE_PENDING_CANCELED",
            reasoning=reasoning or trade.get("reasoning"),
            close_timestamp=utc_now(),
        )
        self.logger.info("Cancelled stale pending trade %s after GPT cancel review", trade["id"])

    def _mark_trade_closed(
        self,
        trade: dict[str, Any],
        close_reason: str,
        close_price: float,
        close_timestamp: datetime | None = None,
    ) -> None:
        pnl = (close_price - float(trade["entry_price"])) * float(trade["quantity"])
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET status = 'CLOSED', close_price = ?, close_timestamp = ?, close_reason = ?, pending_close_reason = NULL,
                    pnl = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (close_price, isoformat_utc(close_timestamp or utc_now()), close_reason, pnl, trade["id"]),
            )
        self.logger.info("Trade %s closed with reason %s", trade["id"], close_reason)

    def _request_market_close(self, trade: dict[str, Any], close_reason: str, trigger_price: float) -> None:
        if trade.get("exit_order_id"):
            return
        broker = self._trade_broker(trade)
        position_id = trade.get("position_id")
        if broker is None or not position_id:
            self._mark_trade_closed(trade, close_reason, trigger_price)
            return
        try:
            order = broker.close_position_market(str(position_id))
        except Exception as exc:
            message = str(exc).lower()
            if "position" in message and ("not" in message or "exist" in message):
                self._mark_trade_closed(trade, close_reason, trigger_price)
                return
            raise
        order_id = str((order or {}).get("order_id") or "") or None
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET exit_order_id = ?, exit_requested_at = ?, pending_close_reason = ?,
                    current_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (order_id, isoformat_utc(utc_now()), close_reason, trigger_price, trade["id"]),
            )
        refreshed_trade = self.get_trade(trade["id"]) or trade
        self._sync_exit_order(refreshed_trade)

    def _close_trade_without_position(self, trade: dict[str, Any], close_reason: str | None = None) -> None:
        reason = close_reason or trade.get("pending_close_reason") or trade.get("close_reason") or "EXTERNAL_CLOSE"
        close_price = float(trade.get("current_price") or trade["entry_price"])
        self._mark_trade_closed(trade, reason, close_price)

    def _sync_exit_order(self, trade: dict[str, Any]) -> None:
        if not trade.get("exit_order_id"):
            return
        broker = self._trade_broker(trade)
        if broker is None:
            return
        position = broker.get_open_position(trade["symbol"])
        if position is None:
            close_price = self._as_float(trade.get("current_price")) or float(trade["entry_price"])
            self._mark_trade_closed(
                trade, str(trade.get("pending_close_reason") or "MARKET_EXIT"), close_price
            )
            return
        # Position still present: the market close is in flight; retry next tick.
        self.logger.debug("Exit for trade %s still pending (position open)", trade["id"])

    def refresh_open_trade_protections(self) -> None:
        open_trades = [
            trade
            for trade in self.get_open_or_pending_trades()
            if trade["status"] == "OPEN" and not trade.get("exit_order_id")
        ]
        if not open_trades:
            self.logger.debug("No open trades found for GPT protection review")
            return

        for trade in open_trades:
            try:
                self._refresh_single_open_trade_protection(trade)
            except Exception:
                self.logger.exception("Failed GPT protection review for open trade %s", trade["id"])

    def _refresh_single_open_trade_protection(self, trade: dict[str, Any]) -> None:
        symbol = str(trade["symbol"])
        candles = self.data_manager.get_symbol_history(symbol, limit=40)
        if not candles:
            self.logger.warning("No market data found for open trade %s (%s); skipping GPT protection review", trade["id"], symbol)
            return

        review = self.gpt_client.request_open_trade_protection_review(
            trade, candles, provider=self._trade_provider(trade)
        )
        proposed_distance = self._as_float(review.get("trailing_take_profit_distance"))
        raw_distance = review.get("trailing_take_profit_distance")
        if raw_distance is not None and proposed_distance is None:
            self.logger.warning(
                "GPT returned invalid trailing_take_profit_distance=%s for open trade %s; keeping previous value",
                raw_distance,
                trade["id"],
            )
            return
        if proposed_distance is not None and proposed_distance <= 0:
            self.logger.warning(
                "GPT returned non-positive trailing_take_profit_distance=%s for open trade %s; keeping previous value",
                proposed_distance,
                trade["id"],
            )
            return

        proposed_activation_pct = self._as_float(review.get("trailing_take_profit_activation_pct"))
        raw_activation_pct = review.get("trailing_take_profit_activation_pct")
        if raw_activation_pct is not None and proposed_activation_pct is None:
            self.logger.warning(
                "GPT returned invalid trailing_take_profit_activation_pct=%s for open trade %s; keeping previous value",
                raw_activation_pct,
                trade["id"],
            )
            return
        if proposed_activation_pct is not None and proposed_activation_pct <= 0:
            self.logger.warning(
                "GPT returned non-positive trailing_take_profit_activation_pct=%s for open trade %s; keeping previous value",
                proposed_activation_pct,
                trade["id"],
            )
            return
        if (proposed_distance is None) != (proposed_activation_pct is None):
            self.logger.warning(
                "GPT returned mismatched trailing fields (distance=%s, activation_pct=%s) for open trade %s; keeping previous values",
                proposed_distance,
                proposed_activation_pct,
                trade["id"],
            )
            return

        entry_price = float(trade["entry_price"])
        min_buffer = float(self.config.trailing_tp_min_profit_buffer_pct)
        if proposed_distance is not None and proposed_activation_pct is not None:
            if not self._trailing_take_profit_pair_is_valid(
                entry_price,
                proposed_distance,
                proposed_activation_pct,
                min_buffer,
            ):
                self.logger.warning(
                    "GPT proposed a trailing-TP pair that would arm below entry for trade %s (%s) "
                    "(entry=%s, distance=%s ≈ %.3f%%, activation_pct=%s, required min %s%% above distance%%); "
                    "keeping previous values",
                    trade["id"],
                    symbol,
                    entry_price,
                    proposed_distance,
                    (proposed_distance / entry_price) * 100.0 if entry_price > 0 else 0.0,
                    proposed_activation_pct,
                    min_buffer,
                )
                return

        current_distance = self._as_float(trade.get("trailing_take_profit_distance"))
        current_activation_pct = self._as_float(trade.get("trailing_take_profit_activation_pct"))
        if current_distance == proposed_distance and current_activation_pct == proposed_activation_pct:
            return

        current_high_water_mark = self._as_float(trade.get("high_water_mark")) or entry_price
        trailing_take_profit_price = self._compute_trailing_take_profit_price(
            current_high_water_mark,
            entry_price,
            proposed_distance,
            proposed_activation_pct,
            self.config.trailing_tp_min_profit_buffer_pct,
        )
        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET trailing_take_profit_distance = ?, trailing_take_profit_activation_pct = ?,
                    trailing_take_profit_price = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (proposed_distance, proposed_activation_pct, trailing_take_profit_price, trade["id"]),
            )
        self.logger.info(
            "Updated trailing take profit for trade %s (%s): distance %s -> %s, activation_pct %s -> %s",
            trade["id"],
            symbol,
            current_distance,
            proposed_distance,
            current_activation_pct,
            proposed_activation_pct,
        )

    def sync_open_trade(self, trade: dict[str, Any]) -> None:
        if trade.get("exit_order_id"):
            self._sync_exit_order(trade)
            return

        broker = self._trade_broker(trade)
        if broker is None:
            return
        position = broker.get_open_position(trade["symbol"])
        if position is None:
            self._close_trade_without_position(trade)
            return

        quantity = self._as_float(position.get("units")) or float(trade["quantity"])
        current_price = self._resolve_current_price(
            trade["symbol"],
            trade["category"],
            position=None,
            fallback=float(trade.get("current_price") or trade["entry_price"]),
            provider=self._trade_provider(trade),
        )
        entry_price = float(trade["entry_price"])
        stop_loss = self._as_float(trade.get("stop_loss"))
        take_profit = self._as_float(trade.get("take_profit"))
        trailing_take_profit_distance = self._as_float(trade.get("trailing_take_profit_distance"))
        trailing_take_profit_activation_pct = self._as_float(trade.get("trailing_take_profit_activation_pct"))
        high_water_mark = max(self._as_float(trade.get("high_water_mark")) or entry_price, current_price)
        trailing_take_profit_price = self._compute_trailing_take_profit_price(
            high_water_mark,
            entry_price,
            trailing_take_profit_distance,
            trailing_take_profit_activation_pct,
            self.config.trailing_tp_min_profit_buffer_pct,
        )
        trailing_stop_price = self._compute_trailing_stop_price(
            high_water_mark,
            self._as_float(trade.get("trailing_stop_distance")),
        )
        pnl = (current_price - entry_price) * quantity

        with db_cursor(self.config.db_trades) as cursor:
            cursor.execute(
                """
                UPDATE trades
                SET quantity = ?, current_price = ?, pnl = ?, high_water_mark = ?, trailing_take_profit_price = ?,
                    trailing_stop_price = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (quantity, current_price, pnl, high_water_mark, trailing_take_profit_price, trailing_stop_price, trade["id"]),
            )

        close_reason = self._trailing_take_profit_close_reason(current_price, trailing_take_profit_price)
        if close_reason:
            self._request_market_close(trade, close_reason, current_price)
            return

        if take_profit is not None and trailing_take_profit_price is None and current_price >= take_profit:
            self._request_market_close(trade, "TAKE_PROFIT", current_price)
            return
        close_reason = self._downside_close_reason(current_price, stop_loss, trailing_stop_price)
        if close_reason:
            self._request_market_close(trade, close_reason, current_price)

    def sync_broker_state(self) -> None:
        """Iterate every active trade and reconcile with the matching broker."""

        for trade in self.get_open_or_pending_trades():
            try:
                if trade["status"] == "PENDING":
                    self.sync_pending_trade(trade)
                elif trade["status"] == "OPEN":
                    self.sync_open_trade(trade)
            except Exception:
                self.logger.exception("Failed to sync trade %s", trade["id"])

    def _evaluate_provider_category(
        self,
        provider: str,
        category: str,
        symbols: list[str],
    ) -> None:
        try:
            available_slots = self._available_trade_slots(category, provider=provider)
            if available_slots <= 0:
                self.logger.debug(
                    "Skipping %s/%s batch evaluation because no slots are available",
                    provider,
                    category,
                )
                return

            symbol_payloads = self._build_batch_payloads(category, list(symbols), provider=provider)
            if not symbol_payloads:
                return

            batch_response = self.gpt_client.request_batch_trade_signals(
                category=category,
                symbol_payloads=symbol_payloads,
                existing_trades=[],
                max_new_trades=available_slots,
                provider=provider,
            )
            by_symbol = {payload["symbol"]: payload for payload in symbol_payloads}
            candidate_signals = [
                signal
                for signal in batch_response.get("signals", [])
                if signal.get("action") == "OPEN" and str(signal.get("symbol")) in by_symbol
            ]
            ranked_signals = self._rank_signals(candidate_signals)
            if ranked_signals:
                self.logger.info(
                    "Top %s/%s signals: %s",
                    provider,
                    category,
                    [
                        {
                            "symbol": signal.get("symbol"),
                            "trade_score": self._as_float(signal.get("trade_score")),
                            "confidence": self._as_float(signal.get("confidence")),
                        }
                        for signal in ranked_signals
                    ],
                )

            opened = 0
            for signal in ranked_signals:
                if self._available_trade_slots(category, provider=provider) <= 0:
                    break
                symbol = str(signal["symbol"])
                if self._open_trade_from_signal(category, symbol, signal, provider=provider):
                    opened += 1
            self.logger.info(
                "Opened %s new %s/%s trades in this cycle", opened, provider, category
            )
        except Exception:
            self.logger.exception("Failed to evaluate %s/%s universe batch", provider, category)

    def evaluate_cycle(self, universe: Mapping[str, Any]) -> None:
        """Iterate the provider-tagged universe and run a GPT cycle per provider/category."""

        for provider, categories in universe.items():
            if not isinstance(categories, dict):
                # Legacy flat dict — assume Alpaca.
                if isinstance(categories, list):
                    self._evaluate_provider_category(PROVIDER_ETORO, str(provider).upper(), list(categories))
                continue
            if self.broker(provider) is None:
                continue
            for category, symbols in categories.items():
                self._evaluate_provider_category(provider, str(category).upper(), list(symbols or []))

    def symbols_to_monitor(self, universe: Mapping[str, Any]) -> dict[str, dict[str, str]]:
        """Return ``{symbol: {category, provider}}`` for the data manager to refresh.

        The data manager understands the dict shape and dispatches to the
        right broker. Existing pending/open trades are always included so
        in-flight positions stay refreshed even if a symbol fell out of the
        universe.
        """

        monitored: dict[str, dict[str, str]] = {}
        for provider, categories in universe.items():
            if not isinstance(categories, dict):
                if isinstance(categories, list):
                    for sym in categories:
                        monitored[sym] = {"category": str(provider).upper(), "provider": PROVIDER_ETORO}
                continue
            for category, symbols in categories.items():
                cat = str(category).upper()
                for sym in symbols or []:
                    monitored[sym] = {"category": cat, "provider": str(provider)}
        for trade in self.get_open_or_pending_trades():
            monitored[trade["symbol"]] = {
                "category": str(trade["category"]),
                "provider": str(trade.get("provider") or PROVIDER_ETORO),
            }
        return monitored

    def weekly_summary(self) -> dict[str, Any]:
        rows = fetch_all(self.config.db_trades, "SELECT * FROM trades")
        # Include all OPEN and PENDING trades plus all CLOSED trades (cumulative PnL).
        # CANCELLED trades are excluded entirely.
        rows = [row for row in rows if row["status"] in {"OPEN", "PENDING", "CLOSED"}]
        closed = [row for row in rows if row["status"] == "CLOSED"]
        winners = [row for row in closed if (row.get("pnl") or 0) > 0]
        pnls = [row.get("pnl") or 0 for row in closed]
        best_trade = max(closed, key=lambda row: row.get("pnl") or float("-inf"), default=None)
        worst_trade = min(closed, key=lambda row: row.get("pnl") or float("inf"), default=None)
        most_traded = Counter(row["symbol"] for row in rows).most_common(5)
        pnl_by_category: dict[str, float] = {}
        for row in closed:
            pnl_by_category[row["category"]] = pnl_by_category.get(row["category"], 0.0) + float(row.get("pnl") or 0.0)
        return {
            "open_trades": [row for row in rows if row["status"] == "OPEN"],
            "pending_trades": [row for row in rows if row["status"] == "PENDING"],
            "closed_trades": closed,
            "pnl_total": round(sum(pnls), 2),
            "pnl_by_category": {key: round(value, 2) for key, value in pnl_by_category.items()},
            "win_rate": round(len(winners) / len(closed), 4) if closed else 0.0,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "most_traded_symbols": most_traded,
        }

    def period_summary(self, period_start: datetime, period_end: datetime) -> dict[str, Any]:
        """Summarise trading activity for a fixed time range.

        Trades closed within [period_start, period_end) contribute to PnL and
        win-rate metrics.  Every non-cancelled trade that was NOT closed during
        the period (still OPEN, PENDING, or closed outside the window) is
        returned as a carry-over with status "OPEN" so it flows into the next
        reporting period.
        """
        rows = fetch_all(self.config.db_trades, "SELECT * FROM trades")
        rows = [row for row in rows if row["status"] != "CANCELLED"]

        closed_in_period: list[dict[str, Any]] = []
        carry_over: list[dict[str, Any]] = []

        for row in rows:
            close_ts = parse_datetime(row.get("close_timestamp"))
            if row["status"] == "CLOSED" and close_ts is not None and period_start <= close_ts < period_end:
                closed_in_period.append(row)
            else:
                # Not closed within the period — carry over as open.
                carry = dict(row)
                carry["status"] = "OPEN"
                carry_over.append(carry)

        winners = [row for row in closed_in_period if (row.get("pnl") or 0) > 0]
        pnls = [row.get("pnl") or 0 for row in closed_in_period]
        best_trade = max(closed_in_period, key=lambda row: row.get("pnl") or float("-inf"), default=None)
        worst_trade = min(closed_in_period, key=lambda row: row.get("pnl") or float("inf"), default=None)
        all_in_scope = closed_in_period + carry_over
        most_traded = Counter(row["symbol"] for row in all_in_scope).most_common(5)
        pnl_by_category: dict[str, float] = {}
        for row in closed_in_period:
            pnl_by_category[row["category"]] = pnl_by_category.get(row["category"], 0.0) + float(row.get("pnl") or 0.0)
        return {
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "closed_trades": closed_in_period,
            "carry_over_trades": carry_over,
            "pnl_total": round(sum(pnls), 2),
            "pnl_by_category": {key: round(value, 2) for key, value in pnl_by_category.items()},
            "win_rate": round(len(winners) / len(closed_in_period), 4) if closed_in_period else 0.0,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "most_traded_symbols": most_traded,
        }
