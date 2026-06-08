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

    Quotes are fetched in a single batched call per provider when the broker
    exposes the batch API (``instrument_id_for_symbol`` +
    ``get_rates_by_instruments``). This collapses what used to be one HTTP
    round-trip per symbol — the dominant cost behind the universe page's slow
    load — into one request for the whole provider. Brokers without the batch
    API fall back to the per-symbol path.
    """

    universe = read_universe_file()
    out: dict[str, dict[str, list[dict[str, Any]]]] = {
        provider: {category: [] for category in categories}
        for provider, categories in VALID_CATEGORIES_BY_PROVIDER.items()
    }
    for provider, categories in VALID_CATEGORIES_BY_PROVIDER.items():
        broker = brokers.get(provider)
        symbols_by_category = {
            category: (universe.get(provider, {}).get(category, []) or [])
            for category in categories
        }
        out[provider] = _quote_universe_provider(broker, provider, symbols_by_category, logger)
    return out


def _quote_universe_provider(
    broker: Any,
    provider: str,
    symbols_by_category: Mapping[str, list[str]],
    logger: logging.Logger,
) -> dict[str, list[dict[str, Any]]]:
    """Decorate every symbol of one provider with a live price.

    When the broker exposes the batched-rates API, all symbols across every
    category are resolved and quoted in a *single* HTTP round-trip; otherwise
    we fall back to the per-symbol path.
    """

    def _entry(symbol: str, category: str, **extra: Any) -> dict[str, Any]:
        return {"symbol": symbol, "category": category, "provider": provider, **extra}

    if broker is None:
        return {
            category: [
                _entry(symbol, category, last_price=None,
                       quote_error=f"{provider} client not configured")
                for symbol in symbols
            ]
            for category, symbols in symbols_by_category.items()
        }

    supports_batch = callable(getattr(broker, "instrument_id_for_symbol", None)) and callable(
        getattr(broker, "get_rates_by_instruments", None)
    )
    if not supports_batch:
        out: dict[str, list[dict[str, Any]]] = {}
        for category, symbols in symbols_by_category.items():
            rows: list[dict[str, Any]] = []
            for symbol in symbols:
                try:
                    price = broker.get_latest_price(symbol, category)
                    rows.append(_entry(symbol, category,
                                       last_price=float(price) if price is not None else None,
                                       quote_error=None))
                except Exception as exc:
                    logger.debug("Universe quote failed for %s/%s/%s: %s",
                                 provider, category, symbol, exc)
                    rows.append(_entry(symbol, category, last_price=None, quote_error=str(exc)))
            out[category] = rows
        return out

    # --- batched fast path: one resolve sweep + one rates GET for the provider
    instrument_ids: dict[tuple[str, str], int] = {}
    resolve_errors: dict[tuple[str, str], str] = {}
    for category, symbols in symbols_by_category.items():
        for symbol in symbols:
            try:
                iid = broker.instrument_id_for_symbol(symbol)
            except Exception as exc:  # a bad resolve shouldn't sink the whole page
                logger.debug("Universe resolve failed for %s/%s/%s: %s",
                             provider, category, symbol, exc)
                resolve_errors[(category, symbol)] = str(exc)
                continue
            if iid is None:
                resolve_errors[(category, symbol)] = "unknown instrument"
            else:
                instrument_ids[(category, symbol)] = int(iid)

    batch_error: str | None = None
    rate_map: dict[int, dict] = {}
    if instrument_ids:
        try:
            rate_map = broker.get_rates_by_instruments(sorted(set(instrument_ids.values())))
        except Exception as exc:  # whole-batch failure: degrade to no prices, not a 500
            logger.debug("Universe batch rates failed for %s: %s", provider, exc)
            batch_error = str(exc)

    out = {}
    for category, symbols in symbols_by_category.items():
        rows = []
        for symbol in symbols:
            key = (category, symbol)
            if key in resolve_errors:
                rows.append(_entry(symbol, category, last_price=None,
                                   quote_error=resolve_errors[key]))
                continue
            rate = rate_map.get(instrument_ids[key], {})
            # Mirror get_latest_price's preference: last → ask → bid.
            price = rate.get("lastExecution") or rate.get("ask") or rate.get("bid")
            if price:
                rows.append(_entry(symbol, category, last_price=float(price), quote_error=None))
            else:
                rows.append(_entry(symbol, category, last_price=None,
                                   quote_error=batch_error or "no rate"))
        out[category] = rows
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
