"""Nodo screener (codice): watchlist → strumenti eToro tradabili, solo stock/ETF.

Prima difesa sul tipo di asset (la seconda, indipendente, è il risk gate).
Massimo max_candidates_per_run candidati, ordinati per momentum a 5 sedute.

Come si risolvono i simboli
---------------------------
`/market-data/search` sa filtrare ma **ignora la proiezione `fields`**: qualunque
cosa si chieda, ogni item contiene solo `instrumentId`. Chiedergli
`internalSymbolFull` e confrontarlo col simbolo faceva quindi fallire ogni
confronto, e la run finiva con zero candidati senza un solo errore.

Si usa invece il catalogo per tipo (`/market-data/instruments?instrumentTypeIds=N`):
una chiamata sola restituisce tutte le anagrafiche, con `symbolFull` e
`stocksIndustryID`. Il confronto è esatto su `symbolFull`, il che scarta da sé
le quotazioni secondarie dello stesso titolo (AAPL → 1001, mentre AAPL.EUR su
Xetra e AAPL.24-7 restano fuori).
"""

from __future__ import annotations

import logging

from etoro_bot.domain import AssetType, Instrument
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.state import BotState

logger = logging.getLogger(__name__)

# instrumentTypeID dell'API: 5 = Stocks, 6 = ETF. Sono gli unici ammessi.
TYPE_IDS: dict[int, AssetType] = {5: AssetType.STOCK, 6: AssetType.ETF}

# Sedute usate per il momentum: 6 chiusure = 5 variazioni giornaliere.
MOMENTUM_CANDLES = 6


def _catalogue(deps: GraphDeps) -> dict[str, tuple[dict, AssetType]]:
    """Mappa symbolFull → (anagrafica, tipo) per stock ed ETF."""
    catalogue: dict[str, tuple[dict, AssetType]] = {}
    for type_id, asset_type in TYPE_IDS.items():
        for row in deps.client.get_instruments_by_type(type_id):
            symbol = str(row.get("symbolFull") or "").upper()
            if symbol:
                catalogue.setdefault(symbol, (row, asset_type))
    return catalogue


def _momentum(deps: GraphDeps, instrument_id: int) -> float:
    """Variazione percentuale sulle ultime 5 sedute; 0.0 se lo storico manca."""
    try:
        candles = deps.client.get_candles(
            instrument_id, interval="OneDay", count=MOMENTUM_CANDLES
        )
    except Exception as exc:
        logger.warning("screener: candele %s non disponibili: %s", instrument_id, exc)
        return 0.0
    closes = [c["close"] for c in candles if c.get("close")]
    if len(closes) < 2 or not closes[0]:
        return 0.0
    return (closes[-1] / closes[0] - 1.0) * 100.0


def screener(state: BotState, deps: GraphDeps) -> dict:
    # Universo effettivo: watchlist + titoli scoperti dinamicamente dalle news
    # (services.universe). Se la discovery non ha mai girato resta la watchlist.
    try:
        from etoro_bot.services.universe import effective_universe

        watchlist = [str(s).upper() for s in effective_universe(deps.settings)]
    except Exception as exc:
        logger.warning("screener: universo dinamico non disponibile: %s", exc)
        watchlist = [str(s).upper() for s in deps.settings.get("watchlist") or []]
    max_candidates = int(deps.settings.get("max_candidates_per_run", 6))

    errors: list[str] = []
    try:
        catalogue = _catalogue(deps)
    except Exception as exc:
        # Senza catalogo non c'è screening possibile: si dichiara l'errore
        # invece di restituire in silenzio zero candidati.
        logger.warning("screener: catalogo strumenti non caricato: %s", exc)
        return {"candidates": [], "errors": [f"screener catalogo: {exc}"]}

    industries: dict[int, str] = {}
    try:
        industries = deps.client.get_stocks_industries()
    except Exception as exc:  # il settore è informativo: si degrada a "unknown"
        logger.warning("screener: settori non disponibili: %s", exc)

    resolved: list[Instrument] = []
    for symbol in watchlist:
        entry = catalogue.get(symbol)
        if entry is None:
            logger.info("screener: %s non trovato fra stock ed ETF eToro", symbol)
            continue
        row, asset_type = entry
        sector = industries.get(int(row.get("stocksIndustryID") or 0), "") or "unknown"
        resolved.append(
            Instrument(
                instrument_id=int(row["instrumentID"]),
                symbol=symbol,
                display_name=row.get("instrumentDisplayName") or "",
                asset_type=asset_type,
                sector=sector,
            )
        )

    if not resolved:
        errors.append("screener: nessun simbolo della watchlist risolto")

    # Un prezzo corrente è la prova che lo strumento è quotabile adesso: senza
    # non ha senso proporlo, perché l'executor non saprebbe dimensionarlo.
    try:
        rates = deps.client.get_rates([inst.instrument_id for inst in resolved])
    except Exception as exc:
        logger.warning("screener: prezzi non disponibili: %s", exc)
        errors.append(f"screener prezzi: {exc}")
        rates = {}

    scored: list[tuple[float, Instrument]] = []
    for instrument in resolved:
        rate = rates.get(instrument.instrument_id) or {}
        price = rate.get("lastExecution") or rate.get("bid") or rate.get("ask")
        if not price:
            logger.info("screener: %s senza prezzo corrente, scartato", instrument.symbol)
            continue
        instrument.current_rate = float(price)
        scored.append((_momentum(deps, instrument.instrument_id), instrument))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    logger.info(
        "screener: %d simboli su %d con prezzo corrente, ne passano %d",
        len(scored), len(watchlist), min(max_candidates, len(scored)),
    )

    update: dict = {
        "candidates": [inst.model_dump(mode="json") for _, inst in scored[:max_candidates]]
    }
    if errors:
        update["errors"] = errors
    return update
