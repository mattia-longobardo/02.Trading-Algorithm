"""Operator-driven add/remove on the active trading universe.

The bot regenerates the universe weekly. Between regenerations the
operator may want to nudge it — pin a conviction symbol that the GPT
shortlist missed, or remove one that no longer makes sense. This module
exposes the validated add/remove primitives the universe page calls.

The new schema is provider-tagged: each broker has its own
``{category: [symbols]}`` map and we never mix Alpaca and Binance symbols
together. The operator picks the provider in the UI; we validate the
symbol against that broker's catalogue and live quote feed.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from core.utils import (
    ALL_PROVIDERS,
    PROVIDER_ALPACA,
    PROVIDER_BINANCE,
    AppConfig,
    read_universe_file,
    write_universe_file,
)


VALID_CATEGORIES_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    PROVIDER_ALPACA: ("STOCK", "CRYPTO"),
    PROVIDER_BINANCE: ("CRYPTO",),
}


class UniverseValidationError(ValueError):
    """Raised when a candidate symbol fails validation."""


def _normalize_provider(provider: str | None) -> str:
    label = (provider or "").strip().lower() or PROVIDER_ALPACA
    if label not in ALL_PROVIDERS:
        raise UniverseValidationError(
            f"Provider must be one of {', '.join(ALL_PROVIDERS)}"
        )
    return label


def _normalize_category(provider: str, category: str) -> str:
    label = (category or "").strip().upper()
    valid = VALID_CATEGORIES_BY_PROVIDER.get(provider, ())
    if label not in valid:
        raise UniverseValidationError(
            f"Category must be one of {', '.join(valid)} for provider {provider}"
        )
    return label


def _normalize_symbol(symbol: str, provider: str, category: str, config: AppConfig) -> str:
    raw = (symbol or "").strip().upper()
    if not raw:
        raise UniverseValidationError("Symbol is required")
    if provider == PROVIDER_BINANCE:
        # Accept BTCUSDT, BTC/USDT or just BTC; normalize to BASE/<quote>
        # using the configured quote currency. Operators typing only the
        # base get the right pair without surprises.
        quote = (config.binance_quote_currency or "USDT").upper()
        clean = raw.replace("/", "")
        if clean.endswith(quote):
            base = clean[: -len(quote)]
        else:
            base = clean
        if not base:
            raise UniverseValidationError(
                f"Binance symbol must include a base asset (e.g. BTC/{quote})"
            )
        return f"{base}/{quote}"
    if category == "CRYPTO":
        # Alpaca pair format BASE/QUOTE.
        if "/" not in raw:
            if len(raw) > 3:
                raw = f"{raw[:-3]}/{raw[-3:]}"
            else:
                raise UniverseValidationError(
                    "Crypto symbol must use BASE/QUOTE format (e.g. BTC/USD)"
                )
        return raw
    if "/" in raw or " " in raw:
        raise UniverseValidationError("Stock symbol cannot contain '/' or spaces")
    return raw


def _validate_symbol_with_broker(
    broker: Any | None,
    symbol: str,
    provider: str,
    category: str,
    logger: logging.Logger,
) -> None:
    if broker is None:
        raise UniverseValidationError(
            f"{provider} client is not configured; cannot validate {symbol}"
        )

    try:
        price = broker.get_latest_price(symbol, category)
    except Exception as exc:
        logger.info(
            "Universe add rejected %s/%s/%s: no live price (%s)",
            provider,
            category,
            symbol,
            exc,
        )
        raise UniverseValidationError(
            f"{provider} could not quote {symbol} — symbol may be unsupported, halted, or delisted"
        ) from exc
    if price is None or float(price) <= 0:
        raise UniverseValidationError(
            f"{provider} returned a non-positive price for {symbol}"
        )

    try:
        if provider == PROVIDER_BINANCE:
            assets = broker.list_assets("CRYPTO")
            wanted = symbol.upper()
            for asset in assets:
                ticker = str(getattr(asset, "symbol", "") or "").upper()
                if ticker == wanted:
                    if not bool(getattr(asset, "tradable", True)):
                        raise UniverseValidationError(
                            f"{symbol} is listed but not currently tradable on Binance Spot"
                        )
                    return
            raise UniverseValidationError(
                f"{symbol} is not in the Binance Spot catalogue"
            )

        if category == "STOCK":
            assets = broker.list_assets("US_EQUITY")
            wanted = symbol.upper()
            for asset in assets:
                ticker = str(getattr(asset, "symbol", "") or "").upper()
                if ticker == wanted:
                    if not bool(getattr(asset, "tradable", True)):
                        raise UniverseValidationError(
                            f"{symbol} is listed but not currently tradable"
                        )
                    return
            raise UniverseValidationError(
                f"{symbol} is not in the Alpaca US_EQUITY catalogue"
            )
        # Alpaca CRYPTO
        assets = broker.list_assets("CRYPTO")
        wanted = symbol.upper()
        for asset in assets:
            ticker = str(getattr(asset, "symbol", "") or "").upper()
            if ticker == wanted:
                return
        raise UniverseValidationError(
            f"{symbol} is not in the Alpaca CRYPTO catalogue"
        )
    except UniverseValidationError:
        raise
    except Exception:
        logger.exception(
            "Asset catalogue check for %s/%s failed; trusting price quote", provider, symbol
        )


def get_universe_with_metadata(
    brokers: Mapping[str, Any],
    logger: logging.Logger,
) -> dict[str, Any]:
    """Read the saved universe and decorate each symbol with a live price.

    Returned shape:
    ``{"alpaca": {"STOCK": [entry, ...], "CRYPTO": [...]},
       "binance": {"CRYPTO": [...]}}``
    """

    universe = read_universe_file()
    out: dict[str, dict[str, list[dict[str, Any]]]] = {
        PROVIDER_ALPACA: {"STOCK": [], "CRYPTO": []},
        PROVIDER_BINANCE: {"CRYPTO": []},
    }
    for provider, categories in VALID_CATEGORIES_BY_PROVIDER.items():
        broker = brokers.get(provider)
        for category in categories:
            symbols = universe.get(provider, {}).get(category, []) or []
            for symbol in symbols:
                entry: dict[str, Any] = {
                    "symbol": symbol,
                    "category": category,
                    "provider": provider,
                }
                if broker is None:
                    entry["last_price"] = None
                    entry["quote_error"] = f"{provider} client not configured"
                else:
                    try:
                        price = broker.get_latest_price(symbol, category)
                        entry["last_price"] = float(price) if price is not None else None
                        entry["quote_error"] = None
                    except Exception as exc:
                        logger.debug(
                            "Universe quote failed for %s/%s/%s: %s",
                            provider,
                            category,
                            symbol,
                            exc,
                        )
                        entry["last_price"] = None
                        entry["quote_error"] = str(exc)
                out[provider][category].append(entry)
    return out


def add_symbol(
    config: AppConfig,
    brokers: Mapping[str, Any],
    logger: logging.Logger,
    *,
    provider: str,
    category: str,
    symbol: str,
) -> dict[str, Any]:
    """Validate the symbol and append it to the active universe (idempotent)."""

    prov = _normalize_provider(provider)
    cat = _normalize_category(prov, category)
    sym = _normalize_symbol(symbol, prov, cat, config)
    _validate_symbol_with_broker(brokers.get(prov), sym, prov, cat, logger)

    universe = read_universe_file()
    universe.setdefault(prov, {})
    existing_per_provider = universe[prov].setdefault(cat, [])
    existing_keys = {s.upper() for s in existing_per_provider}
    if sym in existing_keys:
        return {
            "provider": prov,
            "category": cat,
            "symbol": sym,
            "added": False,
            "already_present": True,
        }

    universe[prov][cat] = list(existing_per_provider) + [sym]
    write_universe_file(universe)
    logger.info("Universe: added %s/%s/%s manually", prov, cat, sym)
    return {
        "provider": prov,
        "category": cat,
        "symbol": sym,
        "added": True,
        "already_present": False,
    }


def remove_symbol(
    config: AppConfig,
    logger: logging.Logger,
    *,
    provider: str,
    category: str,
    symbol: str,
) -> dict[str, Any]:
    """Drop ``symbol`` from the named provider/category. Idempotent."""

    prov = _normalize_provider(provider)
    cat = _normalize_category(prov, category)
    sym = (symbol or "").strip().upper()
    if not sym:
        raise UniverseValidationError("Symbol is required")

    universe = read_universe_file()
    current = universe.get(prov, {}).get(cat) or []
    new_list = [s for s in current if s.upper() != sym]
    removed = len(new_list) != len(current)
    if removed:
        universe.setdefault(prov, {})[cat] = new_list
        write_universe_file(universe)
        logger.info("Universe: removed %s/%s/%s manually", prov, cat, sym)
    return {"provider": prov, "category": cat, "symbol": sym, "removed": removed}
