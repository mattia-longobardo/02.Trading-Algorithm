"""Operator-driven add/remove on the active trading universe.

The bot regenerates the universe weekly. Between regenerations the
operator may want to nudge it — pin a conviction symbol that the GPT
shortlist missed, or remove one that no longer makes sense. This module
exposes the validated add/remove primitives the universe page calls.

The schema is provider-tagged: each broker has its own
``{category: [symbols]}`` map. The operator picks the provider in the UI;
we validate the symbol against that broker's catalogue and live quote feed.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from core.utils import (
    ALL_PROVIDERS,
    PROVIDER_ETORO,
    AppConfig,
    read_universe_file,
    write_universe_file,
)


VALID_CATEGORIES_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    PROVIDER_ETORO: ("STOCK", "CRYPTO"),
}


class UniverseValidationError(ValueError):
    """Raised when a candidate symbol fails validation."""


def _normalize_provider(provider: str | None) -> str:
    label = (provider or "").strip().lower() or PROVIDER_ETORO
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
    if category == "CRYPTO":
        # eToro uses native crypto tickers (e.g. BTC), no quote suffix.
        if "/" in raw or " " in raw:
            raise UniverseValidationError("eToro crypto symbol must be a plain ticker (e.g. BTC)")
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
        asset = broker.resolve_instrument(symbol)
    except Exception:
        logger.exception("eToro instrument resolution failed for %s; trusting price quote", symbol)
        return
    if asset is None:
        raise UniverseValidationError(f"{symbol} is not an eToro instrument")
    if not asset.get("tradable", True):
        raise UniverseValidationError(f"{symbol} is listed on eToro but not currently tradable")


def get_universe_with_metadata(
    brokers: Mapping[str, Any],
    logger: logging.Logger,
) -> dict[str, Any]:
    """Read the saved universe and decorate each symbol with a live price.

    Returned shape:
    ``{"etoro": {"STOCK": [entry, ...], "CRYPTO": [...]}}``
    """

    universe = read_universe_file()
    out: dict[str, dict[str, list[dict[str, Any]]]] = {
        provider: {category: [] for category in categories}
        for provider, categories in VALID_CATEGORIES_BY_PROVIDER.items()
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
