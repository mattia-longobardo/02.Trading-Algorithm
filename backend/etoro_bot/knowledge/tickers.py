"""Rilevamento automatico dei ticker citati in un documento.

Chi carica un documento non deve dire quali titoli tocca: lo deduce il bot.
Il riconoscimento è deterministico (nessuna chiamata LLM, quindi nessun costo
e nessuna dipendenza dalle chiavi personali) e volutamente conservativo — un
falso positivo inquina il retrieval di un titolo per sempre, un falso negativo
si recupera con la ricerca semantica.

Due segnali, entrambi ancorati all'universo investibile configurato
(`watchlist` in settings.yaml):

1. **simbolo esplicito** — `$AAPL`, `(AAPL)`, `NASDAQ: AAPL`, o il simbolo
   isolato fra separatori. I simboli di 1-2 lettere (`V`, `F`) sono accettati
   solo con marcatore esplicito, altrimenti «V» in mezzo a una frase basterebbe
   a marcare Visa;
2. **nome societario** — «Apple», «Exxon Mobil», «Alphabet» … da una tabella di
   alias esplicita, con confine di parola e senza distinzione di maiuscole.
"""

from __future__ import annotations

import re
from functools import lru_cache

# Alias → ticker. Vale solo per i simboli presenti nell'universo configurato:
# la tabella può quindi restare generosa senza rischiare match fuori scope.
COMPANY_ALIASES: dict[str, tuple[str, ...]] = {
    "AAPL": ("apple", "apple inc"),
    "MSFT": ("microsoft",),
    "NVDA": ("nvidia",),
    "GOOGL": ("alphabet", "google"),
    "GOOG": ("alphabet", "google"),
    "AMZN": ("amazon",),
    "META": ("meta platforms", "facebook", "instagram", "whatsapp"),
    "TSLA": ("tesla",),
    "JPM": ("jpmorgan", "jp morgan", "j.p. morgan", "jpmorgan chase"),
    "V": ("visa",),
    "MA": ("mastercard",),
    "UNH": ("unitedhealth", "united health"),
    "XOM": ("exxon", "exxonmobil", "exxon mobil"),
    "CVX": ("chevron",),
    "SPY": ("s&p 500", "s&p500", "sp500", "spdr s&p 500"),
    "QQQ": ("nasdaq 100", "nasdaq-100", "invesco qqq"),
    "AMD": ("advanced micro devices",),
    "INTC": ("intel",),
    "NFLX": ("netflix",),
    "DIS": ("disney", "walt disney"),
    "BA": ("boeing",),
    "KO": ("coca-cola", "coca cola"),
    "PEP": ("pepsico", "pepsi"),
    "WMT": ("walmart",),
    "COST": ("costco",),
    "PFE": ("pfizer",),
    "JNJ": ("johnson & johnson", "johnson and johnson"),
    "BAC": ("bank of america",),
    "GS": ("goldman sachs",),
    "ORCL": ("oracle",),
    "CRM": ("salesforce",),
    "ADBE": ("adobe",),
    "AVGO": ("broadcom",),
    "QCOM": ("qualcomm",),
    "MU": ("micron",),
    "TSM": ("tsmc", "taiwan semiconductor"),
    "SHOP": ("shopify",),
    "UBER": ("uber",),
    "ABNB": ("airbnb",),
    "PYPL": ("paypal",),
    "SQ": ("block inc", "square inc"),
    "F": ("ford",),
    "GM": ("general motors",),
    "T": ("at&t",),
    "VZ": ("verizon",),
    "NKE": ("nike",),
    "SBUX": ("starbucks",),
    "MCD": ("mcdonald's", "mcdonalds"),
}

# Simboli così corti che, senza marcatore, coinciderebbero con parole comuni.
_AMBIGUOUS_MAX_LEN = 2

# $AAPL | (AAPL) | NASDAQ: AAPL | NYSE:AAPL | AAPL isolato fra separatori
_EXPLICIT_MARKERS = (
    r"\$(?P<sym>[A-Z]{1,5})\b",
    r"\((?P<sym>[A-Z]{1,5})\)",
    r"\b(?:NASDAQ|NYSE|AMEX|ARCA|BATS|TICKER|SYMBOL)\s*[:\-]\s*(?P<sym>[A-Z]{1,5})\b",
)
_EXPLICIT_CAPTURES = [re.compile(p) for p in _EXPLICIT_MARKERS]

_BARE_SYMBOL_RE = re.compile(r"(?<![A-Za-z0-9$.])([A-Z]{3,5})(?![A-Za-z0-9])")


@lru_cache(maxsize=1)
def default_universe() -> tuple[str, ...]:
    """Universo investibile da settings.yaml; vuoto se il file non c'è."""
    try:
        from etoro_bot.config import load_settings

        watchlist = load_settings().get("watchlist") or []
    except Exception:  # config illeggibile: si degrada a nessun rilevamento
        return ()
    return tuple(str(s).strip().upper() for s in watchlist if str(s).strip())


def _alias_pattern(symbols: frozenset[str]) -> re.Pattern[str] | None:
    pairs: list[tuple[str, str]] = []
    for symbol in symbols:
        for alias in COMPANY_ALIASES.get(symbol, ()):
            pairs.append((alias, symbol))
    if not pairs:
        return None
    # Alias più lunghi per primi: «exxon mobil» deve vincere su «exxon».
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    joined = "|".join(re.escape(alias) for alias, _ in pairs)
    return re.compile(rf"(?<![\w]){joined}(?![\w])", re.IGNORECASE)


@lru_cache(maxsize=32)
def _compiled(symbols: frozenset[str]) -> tuple[re.Pattern[str] | None, dict[str, str]]:
    lookup: dict[str, str] = {}
    for symbol in symbols:
        for alias in COMPANY_ALIASES.get(symbol, ()):
            lookup.setdefault(alias.lower(), symbol)
    return _alias_pattern(symbols), lookup


def detect_tickers(text: str, universe: tuple[str, ...] | None = None) -> list[str]:
    """Ticker citati in `text`, limitati all'universo investibile.

    Ritorna simboli unici in ordine di prima comparsa, così il chunk conserva
    l'ordine in cui il documento introduce i titoli.
    """
    if not text:
        return []
    symbols = frozenset(universe if universe is not None else default_universe())
    if not symbols:
        return []

    hits: list[tuple[int, str]] = []

    for pattern in _EXPLICIT_CAPTURES:
        for match in pattern.finditer(text):
            symbol = match.group("sym")
            if symbol in symbols:
                hits.append((match.start(), symbol))

    for match in _BARE_SYMBOL_RE.finditer(text):
        symbol = match.group(1)
        if symbol in symbols and len(symbol) > _AMBIGUOUS_MAX_LEN:
            hits.append((match.start(), symbol))

    alias_re, lookup = _compiled(symbols)
    if alias_re is not None:
        for match in alias_re.finditer(text):
            symbol = lookup.get(match.group(0).lower())
            if symbol:
                hits.append((match.start(), symbol))

    ordered: list[str] = []
    for _, symbol in sorted(hits, key=lambda hit: hit[0]):
        if symbol not in ordered:
            ordered.append(symbol)
    return ordered
