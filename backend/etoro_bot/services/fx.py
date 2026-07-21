"""Cambi valuta per la visualizzazione.

eToro ragiona in dollari: equity, cash, PnL e prezzi arrivano dall'API in USD
e in USD restano nel journal (`*_usd` su Postgres). La valuta scelta nelle
Impostazioni è quindi puramente di *presentazione*: qui si espone il tasso
USD→valuta e la UI converte al momento del rendering. Nessun dato storico
viene riscritto, così cambiare valuta non falsa i numeri già registrati.

Sorgente: Frankfurter (https://frankfurter.dev) — tassi di riferimento BCE,
pubblici, senza API key, aggiornati una volta al giorno nei giorni feriali.
Il servizio degrada in modo sicuro: cache in memoria, cache su disco in
`STATE_DIR` per sopravvivere ai riavvii e, in ultima istanza, `stale: true`
con la sola identità USD→USD (la UI mostra allora importi in dollari).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("etoro_bot.fx")

API_URL = "https://api.frankfurter.dev/v1/latest"
BASE_CURRENCY = "USD"
CACHE_TTL = timedelta(hours=6)
CACHE_FILENAME = "fx_rates.json"

# Valute principali, tutte coperte dai tassi di riferimento BCE.
SUPPORTED_CURRENCIES: tuple[str, ...] = (
    "USD", "EUR", "GBP", "CHF", "JPY", "CAD", "AUD", "NZD",
    "SEK", "NOK", "DKK", "PLN", "CZK", "HUF", "RON", "BGN",
    "CNY", "HKD", "SGD", "INR", "KRW", "BRL", "MXN", "ZAR",
    "TRY", "ILS", "ISK", "PHP", "IDR", "MYR", "THB",
)

CURRENCY_LABELS: dict[str, str] = {
    "USD": "Dollaro USA", "EUR": "Euro", "GBP": "Sterlina britannica",
    "CHF": "Franco svizzero", "JPY": "Yen giapponese", "CAD": "Dollaro canadese",
    "AUD": "Dollaro australiano", "NZD": "Dollaro neozelandese",
    "SEK": "Corona svedese", "NOK": "Corona norvegese", "DKK": "Corona danese",
    "PLN": "Złoty polacco", "CZK": "Corona ceca", "HUF": "Fiorino ungherese",
    "RON": "Leu rumeno", "BGN": "Lev bulgaro", "CNY": "Yuan cinese",
    "HKD": "Dollaro di Hong Kong", "SGD": "Dollaro di Singapore",
    "INR": "Rupia indiana", "KRW": "Won sudcoreano", "BRL": "Real brasiliano",
    "MXN": "Peso messicano", "ZAR": "Rand sudafricano", "TRY": "Lira turca",
    "ILS": "Shekel israeliano", "ISK": "Corona islandese",
    "PHP": "Peso filippino", "IDR": "Rupia indonesiana",
    "MYR": "Ringgit malese", "THB": "Baht thailandese",
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None


def _cache_path() -> Path:
    return Path(os.environ.get("STATE_DIR", os.environ.get("KILL_SWITCH_DIR", "."))) / CACHE_FILENAME


def _normalise(rates: dict[str, Any]) -> dict[str, float]:
    """Tiene solo le valute supportate e garantisce l'identità USD→USD."""
    clean = {
        code: float(value)
        for code, value in rates.items()
        if code in SUPPORTED_CURRENCIES and isinstance(value, (int, float)) and value > 0
    }
    clean[BASE_CURRENCY] = 1.0
    return clean


def _fetch_remote() -> dict[str, float]:
    import requests

    symbols = ",".join(c for c in SUPPORTED_CURRENCIES if c != BASE_CURRENCY)
    response = requests.get(
        API_URL, params={"base": BASE_CURRENCY, "symbols": symbols}, timeout=10
    )
    response.raise_for_status()
    return _normalise(response.json().get("rates") or {})


def _read_disk() -> dict[str, Any] | None:
    path = _cache_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rates = _normalise(payload.get("rates") or {})
        if len(rates) < 2:
            return None
        return {"rates": rates, "fetched_at": str(payload.get("fetched_at") or "")}
    except (OSError, ValueError):
        log.warning("cache cambi su disco illeggibile: %s", path, exc_info=True)
        return None


def _write_disk(entry: dict[str, Any]) -> None:
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(entry), encoding="utf-8")
    except OSError:
        log.warning("cache cambi non scrivibile: %s", path, exc_info=True)


def _age(entry: dict[str, Any]) -> timedelta | None:
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched


def get_rates(*, force: bool = False) -> dict[str, Any]:
    """Tassi USD→valuta. Non solleva mai: al peggio ritorna stale con solo USD."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _read_disk()

        fresh_enough = (
            not force
            and _cache is not None
            and (_age(_cache) or CACHE_TTL * 2) < CACHE_TTL
        )
        if not fresh_enough:
            try:
                entry = {
                    "rates": _fetch_remote(),
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                }
                _cache = entry
                _write_disk(entry)
            except Exception:
                # Rete giù o Frankfurter irraggiungibile: si tiene l'ultimo
                # tasso noto e lo si marca stale, senza rompere la dashboard.
                log.warning("tassi di cambio non aggiornabili", exc_info=True)

        if _cache is None:
            return {
                "base": BASE_CURRENCY,
                "rates": {BASE_CURRENCY: 1.0},
                "fetched_at": None,
                "stale": True,
                "source": "frankfurter",
            }

        age = _age(_cache)
        return {
            "base": BASE_CURRENCY,
            "rates": dict(_cache["rates"]),
            "fetched_at": _cache.get("fetched_at") or None,
            "stale": age is None or age > CACHE_TTL,
            "source": "frankfurter",
        }


def rate_for(currency: str) -> float:
    """Moltiplicatore USD→`currency`; 1.0 se sconosciuto (fallback in dollari)."""
    if currency == BASE_CURRENCY:
        return 1.0
    return float(get_rates()["rates"].get(currency, 1.0))


def convert(amount_usd: float | None, currency: str) -> float | None:
    return None if amount_usd is None else amount_usd * rate_for(currency)


def reset_cache() -> None:
    """Svuota la cache in memoria (usata dai test)."""
    global _cache
    with _lock:
        _cache = None
