"""Operator-driven add/remove on the active trading universe.

The bot regenerates the universe weekly. Between regenerations the
operator may want to nudge it — pin a conviction symbol that the GPT
shortlist missed, or remove one that no longer makes sense. This module
exposes the validated add/remove primitives the universe page calls.
"""

from __future__ import annotations

import logging
from typing import Any

from clients.alpaca_client import AlpacaClient
from core.utils import AppConfig, read_universe_file, write_universe_file


VALID_CATEGORIES = ("STOCK", "CRYPTO")


class UniverseValidationError(ValueError):
    """Raised when a candidate symbol fails validation."""


def _normalize_category(category: str) -> str:
    label = (category or "").strip().upper()
    if label not in VALID_CATEGORIES:
        raise UniverseValidationError(
            f"Category must be one of {', '.join(VALID_CATEGORIES)}"
        )
    return label


def _normalize_symbol(symbol: str, category: str) -> str:
    raw = (symbol or "").strip().upper()
    if not raw:
        raise UniverseValidationError("Symbol is required")
    if category == "CRYPTO":
        # Alpaca uses pair format `BASE/QUOTE`. Accept both `BTCUSD`
        # (insert slash before last 3 chars) and `BTC/USD` directly.
        if "/" not in raw:
            if len(raw) > 3:
                raw = f"{raw[:-3]}/{raw[-3:]}"
            else:
                raise UniverseValidationError(
                    "Crypto symbol must use BASE/QUOTE format (e.g. BTC/USD)"
                )
    else:
        if "/" in raw or " " in raw:
            raise UniverseValidationError("Stock symbol cannot contain '/' or spaces")
    return raw


def _validate_symbol_with_alpaca(
    alpaca: AlpacaClient,
    symbol: str,
    category: str,
    logger: logging.Logger,
) -> None:
    """Confirm Alpaca knows about ``symbol`` and that we can fetch a price.

    Two-step check: the symbol must be quotable now (rejects delisted /
    halted assets) and an asset record must exist in the broker's
    catalogue (rejects typos). Either failure raises :class:`UniverseValidationError`.
    """

    try:
        price = alpaca.get_latest_price(symbol, category)
    except Exception as exc:
        logger.info("Universe add rejected %s/%s: no live price (%s)", category, symbol, exc)
        raise UniverseValidationError(
            f"Alpaca could not quote {symbol} — symbol may be delisted, halted, or unsupported"
        ) from exc
    if price is None or float(price) <= 0:
        raise UniverseValidationError(
            f"Alpaca returned a non-positive price for {symbol}"
        )

    # Best-effort asset existence check. Failures here are logged but not
    # blocking, because get_latest_price already proved the symbol is
    # quotable on the data feed.
    try:
        if category == "STOCK":
            assets = alpaca.list_assets("US_EQUITY")
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
        else:  # CRYPTO
            assets = alpaca.list_assets("CRYPTO")
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
        logger.exception("Asset catalogue check for %s failed; trusting price quote", symbol)


def get_universe_with_metadata(alpaca: AlpacaClient, logger: logging.Logger) -> dict[str, Any]:
    """Read the saved universe and decorate each symbol with a live price."""

    universe = read_universe_file()
    out: dict[str, list[dict[str, Any]]] = {"STOCK": [], "CRYPTO": []}
    for category in VALID_CATEGORIES:
        for symbol in universe.get(category, []) or []:
            entry: dict[str, Any] = {"symbol": symbol, "category": category}
            try:
                price = alpaca.get_latest_price(symbol, category)
                entry["last_price"] = float(price) if price is not None else None
                entry["quote_error"] = None
            except Exception as exc:
                logger.debug("Universe quote failed for %s/%s: %s", category, symbol, exc)
                entry["last_price"] = None
                entry["quote_error"] = str(exc)
            out[category].append(entry)
    return out


def add_symbol(
    config: AppConfig,
    alpaca: AlpacaClient,
    logger: logging.Logger,
    *,
    category: str,
    symbol: str,
) -> dict[str, Any]:
    """Validate the symbol and append it to the active universe (idempotent)."""

    cat = _normalize_category(category)
    sym = _normalize_symbol(symbol, cat)
    _validate_symbol_with_alpaca(alpaca, sym, cat, logger)

    universe = read_universe_file()
    universe.setdefault("STOCK", [])
    universe.setdefault("CRYPTO", [])

    existing = {s.upper() for s in universe.get(cat, []) or []}
    if sym in existing:
        return {"category": cat, "symbol": sym, "added": False, "already_present": True}

    universe[cat] = list(universe.get(cat) or []) + [sym]
    write_universe_file(universe)
    logger.info("Universe: added %s/%s manually", cat, sym)
    return {"category": cat, "symbol": sym, "added": True, "already_present": False}


def remove_symbol(
    config: AppConfig,
    logger: logging.Logger,
    *,
    category: str,
    symbol: str,
) -> dict[str, Any]:
    """Drop ``symbol`` from the named category. Idempotent."""

    cat = _normalize_category(category)
    sym = (symbol or "").strip().upper()
    if not sym:
        raise UniverseValidationError("Symbol is required")

    universe = read_universe_file()
    current = universe.get(cat) or []
    new_list = [s for s in current if s.upper() != sym]
    removed = len(new_list) != len(current)
    if removed:
        universe[cat] = new_list
        write_universe_file(universe)
        logger.info("Universe: removed %s/%s manually", cat, sym)
    return {"category": cat, "symbol": sym, "removed": removed}
