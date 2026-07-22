"""Scoperta dinamica dell'universo investibile: interessanti ma affidabili.

La watchlist di settings.yaml resta il nucleo fisso. In aggiunta, a ogni fetch
news il bot nomina nuovi candidati e li fa passare da uno screening di
affidabilità deterministico.

La nomination ha due modalità (`universe_discovery.mode`):

  - **llm** (default): un analista di scouting LLM legge il digest delle news
    del giorno e propone candidati con tesi e confidence — può fare
    read-through (una notizia sui data center può candidare un fornitore mai
    citato). L'LLM propone, il codice dispone: ogni proposta deve risolversi
    sul catalogo eToro e superare lo screening. Le citazioni regex restano
    come corroborazione (bonus di punteggio) e come fallback automatico se
    l'LLM non è disponibile.
  - **regex**: solo citazioni esplicite nelle news (`$AAPL` / `(AAPL)` /
    `NASDAQ: AAPL`, o il nome societario del catalogo eToro).

Screening di affidabilità (identico nelle due modalità):

  - quotato su eToro come stock/ETF, con prezzo corrente;
  - prezzo ≥ min_price_usd (niente penny stock);
  - storico ≥ min_history_days candele giornaliere (niente IPO fresche);
  - controvalore medio scambiato ≥ min_avg_dollar_volume_usd (liquidità);
  - volatilità annualizzata ≤ max_annualized_vol_pct (niente titoli impazziti);
  - spread bid/ask ≤ max_spread_pct quando calcolabile.

I sopravvissuti sono ordinati per interesse (confidence LLM + momentum 5/20
sedute + corroborazione buzz; in modalità regex: buzz + momentum). I primi
`size` diventano l'universo dinamico, persistito in
`$STATE_DIR/discovered_universe.json` e unito alla watchlist da
`effective_universe()` (screener, rilevamento ticker, feed per-ticker, CAG).

Isteresi anti-churn: un titolo già nell'universo resta anche senza riconferma
per `keep_misses - 1` refresh consecutivi, purché continui a superare lo
screening di affidabilità; esce subito se lo screening lo boccia.

Il modulo NON importa fetch_news (le news arrivano dal chiamante): evita un
import circolare, dato che fetch_news usa `effective_universe` per i feed.

CLI (chiavi da env ETORO_API_KEY/ETORO_USER_KEY):
    python -m etoro_bot.services.universe
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

STATE_FILENAME = "discovered_universe.json"

# instrumentTypeID dell'API eToro: 5 = Stocks, 6 = ETF (come nello screener).
_TYPE_IDS = {5: "stock", 6: "etf"}

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "mode": "llm",                      # llm (scout + fallback regex) | regex
    "size": 5,                          # titoli dinamici oltre alla watchlist
    "min_mentions": 2,                  # item news distinti per la candidatura (regex)
    "max_evaluated": 20,                # candidati ammessi allo screening (bounded API calls)
    "llm_max_proposals": 10,            # tetto alle proposte dello scout LLM
    "min_confidence": 0.5,              # confidence minima di una proposta LLM
    "keep_misses": 3,                   # refresh senza riconferma prima di uscire
    "min_price_usd": 5.0,
    "min_history_days": 120,
    "min_avg_dollar_volume_usd": 20_000_000,
    "max_annualized_vol_pct": 60.0,
    "max_spread_pct": 1.0,
    "news_half_life_days": 3.0,         # peso citazioni: dimezza ogni N giorni
    "max_age_days": 7,                  # stato più vecchio: ignorato (discovery ferma)
}

# Suffissi legali da rimuovere per ottenere l'alias «colloquiale» del nome.
_LEGAL_SUFFIX_RE = re.compile(
    r"\s+(inc\.?|corp\.?|corporation|company|co\.?|ltd\.?|plc|sa|nv|ag|se|"
    r"group|holdings?|technologies|technology)\.?$",
    re.IGNORECASE,
)

# Citazioni esplicite di simbolo: $AAPL | (AAPL) | NASDAQ: AAPL …
_EXPLICIT_SYMBOL_RES = (
    re.compile(r"\$(?P<sym>[A-Z]{1,6})\b"),
    re.compile(r"\((?P<sym>[A-Z]{1,6})\)"),
    re.compile(r"\b(?:NASDAQ|NYSE|AMEX|ARCA|BATS|TICKER|SYMBOL)\s*[:\-]\s*(?P<sym>[A-Z]{1,6})\b"),
)


def _state_dir() -> Path:
    return Path(os.environ.get("STATE_DIR", "/app/state"))


def state_file() -> Path:
    return _state_dir() / STATE_FILENAME


def discovery_config(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Config effettiva: default sovrascritti da `universe_discovery` in settings."""
    raw = (settings or {}).get("universe_discovery") or {}
    return {**DEFAULTS, **{k: raw[k] for k in raw if k in DEFAULTS}}


# -- lettura stato -----------------------------------------------------------


def load_discovery_state(settings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Stato persistito, o None se assente/corrotto/scaduto/disabilitato."""
    cfg = discovery_config(settings)
    if not cfg["enabled"]:
        return None
    path = state_file()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    generated = str(state.get("generated_at") or "")
    try:
        age_days = (
            datetime.now(timezone.utc) - datetime.fromisoformat(generated)
        ).total_seconds() / 86400.0
    except ValueError:
        return None
    if age_days > float(cfg["max_age_days"]):
        logger.info("universo dinamico scaduto (%.1f giorni): ignorato", age_days)
        return None
    return state


def discovered_instruments(settings: dict[str, Any] | None = None) -> list[dict]:
    state = load_discovery_state(settings)
    return list(state.get("tickers") or []) if state else []


def effective_universe(settings: dict[str, Any] | None) -> list[str]:
    """Watchlist + universo dinamico, senza duplicati, watchlist per prima."""
    universe = [str(s).upper() for s in (settings or {}).get("watchlist") or []]
    for row in discovered_instruments(settings):
        symbol = str(row.get("symbol") or "").upper()
        if symbol and symbol not in universe:
            universe.append(symbol)
    return universe


def discovered_aliases(settings: dict[str, Any] | None = None) -> dict[str, tuple[str, ...]]:
    """Alias (nome societario) dei titoli scoperti, per il rilevamento ticker."""
    aliases: dict[str, tuple[str, ...]] = {}
    for row in discovered_instruments(settings):
        symbol = str(row.get("symbol") or "").upper()
        name = str(row.get("display_name") or "").strip()
        if not symbol or not name:
            continue
        variants = [name.lower()]
        stripped = _LEGAL_SUFFIX_RE.sub("", name).strip()
        if len(stripped) >= 4 and stripped.lower() not in variants:
            variants.append(stripped.lower())
        aliases[symbol] = tuple(variants)
    return aliases


# -- nomination dalle news ---------------------------------------------------


def _published_age_days(item: dict, now: float) -> float:
    """Età in giorni dell'item news; 0 se la data manca (appena scaricato)."""
    from etoro_bot.knowledge.kb import parse_published_ts

    ts = parse_published_ts(str(item.get("published_at") or ""))
    if ts is None:
        return 0.0
    return max(0.0, (now - ts) / 86400.0)


def _name_alias_patterns(
    catalogue: dict[str, dict],
) -> list[tuple[re.Pattern[str], str]]:
    """Pattern (compilati) nome societario → simbolo, per l'intero catalogo.

    Due varianti per strumento: il nome completo (case-insensitive) e il nome
    senza suffisso legale, quest'ultimo case-SENSITIVE e lungo ≥ 4: «Target
    Corp» matcha «Target» ma non «price target», perché la maiuscola è parte
    del pattern.
    """
    patterns: list[tuple[re.Pattern[str], str]] = []
    for symbol, row in catalogue.items():
        name = str(row.get("instrumentDisplayName") or "").strip()
        if len(name) < 5:
            continue
        patterns.append(
            (re.compile(rf"(?<!\w){re.escape(name)}(?!\w)", re.IGNORECASE), symbol)
        )
        stripped = _LEGAL_SUFFIX_RE.sub("", name).strip()
        if stripped != name and len(stripped) >= 4 and stripped[0].isupper():
            patterns.append((re.compile(rf"(?<!\w){re.escape(stripped)}(?!\w)"), symbol))
    return patterns


def nominate(
    news_items: list[dict],
    catalogue: dict[str, dict],
    *,
    half_life_days: float,
    exclude: set[str],
    now: float | None = None,
) -> dict[str, dict]:
    """Simbolo → {mentions, buzz} dai testi delle news.

    `buzz` è la somma dei pesi di recency (0.5^(età/half_life)); `mentions` è
    il numero di item distinti che citano il titolo. Le citazioni «nude»
    (AAPL senza marcatore) NON contano: contro un catalogo di migliaia di
    simboli produrrebbero falsi positivi sistematici (CEO, IPO, AI…).
    """
    now = now if now is not None else time.time()
    name_patterns = _name_alias_patterns(catalogue)
    scores: dict[str, dict] = {}
    for item in news_items:
        text = str(item.get("text") or "")
        if not text:
            continue
        cited: set[str] = set()
        for pattern in _EXPLICIT_SYMBOL_RES:
            for match in pattern.finditer(text):
                symbol = match.group("sym")
                if symbol in catalogue:
                    cited.add(symbol)
        for pattern, symbol in name_patterns:
            if symbol not in cited and pattern.search(text):
                cited.add(symbol)
        # I ticker già assegnati all'item (feed per-ticker) contano come citazione.
        for symbol in item.get("tickers") or []:
            if str(symbol).upper() in catalogue:
                cited.add(str(symbol).upper())
        if not cited:
            continue
        weight = 0.5 ** (_published_age_days(item, now) / max(half_life_days, 0.1))
        for symbol in cited - exclude:
            entry = scores.setdefault(symbol, {"mentions": 0, "buzz": 0.0})
            entry["mentions"] += 1
            entry["buzz"] += weight
    return scores


# -- scout LLM ---------------------------------------------------------------

_DIGEST_MAX_ITEMS = 80
_DIGEST_ITEM_CHARS = 220


class ScoutProposal(BaseModel):
    """Una proposta dello scout LLM, validata prima di qualsiasi uso."""

    symbol: str
    company: str = ""
    thesis: str = ""
    news_refs: list[int] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


def _news_digest(news_items: list[dict]) -> str:
    """Digest numerato delle news del giorno, limitato per stare in una chiamata.

    Gli item sono interleave-ati per fonte (round-robin): con molti feed il
    tetto _DIGEST_MAX_ITEMS non deve far vedere allo scout solo i primi feed
    della configurazione, ma un campione di tutte le fonti.
    """
    by_source: dict[str, list[dict]] = {}
    for item in news_items:
        if str(item.get("text") or "").strip():
            by_source.setdefault(str(item.get("source") or "?"), []).append(item)
    interleaved: list[dict] = []
    while len(interleaved) < _DIGEST_MAX_ITEMS and any(by_source.values()):
        for source in list(by_source):
            if by_source[source] and len(interleaved) < _DIGEST_MAX_ITEMS:
                interleaved.append(by_source[source].pop(0))
    return "\n".join(
        f"[{i}] ({item.get('source', '?')}) "
        f"{str(item.get('text') or '').strip()[:_DIGEST_ITEM_CHARS]}"
        for i, item in enumerate(interleaved, start=1)
    )


def llm_scout(
    news_items: list[dict],
    settings: dict[str, Any] | None,
    current_universe: list[str],
    llm: Callable[..., str] | None = None,
) -> list[ScoutProposal]:
    """Chiede all'LLM i candidati del giorno; solleva su qualsiasi errore.

    Il chiamante intercetta l'eccezione e ricade sulla nomination regex: lo
    scout è il segnale primario, mai un requisito. Gli item malformati nella
    risposta vengono scartati in silenzio (stesso pattern degli analisti).
    """
    cfg = discovery_config(settings)
    digest = _news_digest(news_items)
    if not digest:
        return []
    prompt = (
        "Sei l'analista di SCOUTING di un bot di swing trading long-only su "
        "stock/ETF (orizzonte giorni/settimane). Dal digest di news di oggi "
        f"proponi da 3 a {int(cfg['llm_max_proposals'])} titoli QUOTATI che "
        "meritano di entrare nell'universo di monitoraggio: opportunità "
        "interessanti del momento ma affidabili (niente micro-cap, niente "
        "titoli illiquidi). Puoi proporre titoli non citati esplicitamente se "
        "una notizia li impatta (filiera, concorrenza, settore). NON proporre "
        f"titoli già nell'universo attuale: {', '.join(current_universe) or 'nessuno'}.\n"
        "Per ogni proposta indica in news_refs gli indici [i] delle notizie "
        "da cui deriva la tesi.\n\n"
        "Rispondi SOLO con un array JSON:\n"
        '[{"symbol": "...", "company": "...", "thesis": "<max 30 parole>", '
        '"news_refs": [<indici>], "confidence": <0..1>}]\n\n'
        f"Digest di oggi:\n{digest}"
    )
    if llm is None:
        from etoro_bot.graph.llm import call_llm

        llm = call_llm
    llm_cfg = (settings or {}).get("llm") or {}
    from etoro_bot.graph.llm import extract_json

    raw = llm(
        system_blocks=[],
        user_prompt=prompt,
        model=str(llm_cfg.get("model", "gpt-5.6-terra")),
        max_tokens=int(llm_cfg.get("max_tokens", 2048)),
    )
    data = extract_json(raw)
    proposals: list[ScoutProposal] = []
    for item in data if isinstance(data, list) else []:
        try:
            proposal = ScoutProposal.model_validate(item)
        except ValidationError:
            continue  # item malformato: scartato
        proposal.symbol = proposal.symbol.strip().upper()
        if proposal.symbol:
            proposals.append(proposal)
    return proposals[: int(cfg["llm_max_proposals"])]


def _normalized_name(name: str) -> str:
    stripped = _LEGAL_SUFFIX_RE.sub("", name.strip())
    return re.sub(r"[^a-z0-9]+", " ", stripped.lower()).strip()


def _catalogue_by_name(catalogue: dict[str, dict]) -> dict[str, str]:
    """Nome societario normalizzato → simbolo, per risolvere le proposte LLM."""
    by_name: dict[str, str] = {}
    for symbol, row in catalogue.items():
        name = _normalized_name(str(row.get("instrumentDisplayName") or ""))
        if name:
            by_name.setdefault(name, symbol)
    return by_name


def resolve_proposal(
    proposal: ScoutProposal, catalogue: dict[str, dict], by_name: dict[str, str]
) -> str | None:
    """Simbolo eToro della proposta: match sul symbol, poi sul nome societario."""
    if proposal.symbol in catalogue:
        return proposal.symbol
    return by_name.get(_normalized_name(proposal.company))


# -- screening di affidabilità ----------------------------------------------


def _annualized_vol_pct(closes: list[float]) -> float | None:
    """Volatilità annualizzata (%) dei log-return giornalieri, ultime ~60 sedute."""
    window = closes[-61:]
    returns = [
        math.log(b / a) for a, b in zip(window, window[1:]) if a and b and a > 0 and b > 0
    ]
    if len(returns) < 20:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252) * 100.0


def _momentum_pct(closes: list[float], sessions: int) -> float:
    if len(closes) < sessions + 1 or not closes[-(sessions + 1)]:
        return 0.0
    return (closes[-1] / closes[-(sessions + 1)] - 1.0) * 100.0


def _evaluate(client: Any, row: dict, cfg: dict[str, Any]) -> dict | None:
    """Screening di affidabilità di un candidato; None se il titolo non passa."""
    instrument_id = int(row["instrumentID"])
    symbol = str(row.get("symbolFull") or "").upper()

    rates = client.get_rates([instrument_id])
    rate = rates.get(instrument_id) or {}
    price = rate.get("lastExecution") or rate.get("bid") or rate.get("ask")
    if not price:
        return None
    price = float(price)
    if price < float(cfg["min_price_usd"]):
        return None

    bid, ask = rate.get("bid"), rate.get("ask")
    if bid and ask and float(ask) > float(bid) > 0:
        spread_pct = (float(ask) - float(bid)) / ((float(ask) + float(bid)) / 2) * 100.0
        if spread_pct > float(cfg["max_spread_pct"]):
            return None
    else:
        spread_pct = None

    candles = client.get_candles(
        instrument_id, interval="OneDay", count=int(cfg["min_history_days"]) + 10
    )
    closes = [float(c["close"]) for c in candles if c.get("close")]
    if len(closes) < int(cfg["min_history_days"]):
        return None

    vol_pct = _annualized_vol_pct(closes)
    if vol_pct is not None and vol_pct > float(cfg["max_annualized_vol_pct"]):
        return None

    # Controvalore medio scambiato (ultime 20 sedute). Se il feed candele non
    # riporta i volumi il controllo è non valutabile e non boccia da solo.
    volumes = [
        float(c["close"]) * float(c["volume"])
        for c in candles[-20:]
        if c.get("close") and c.get("volume")
    ]
    avg_dollar_volume = sum(volumes) / len(volumes) if volumes else None
    if avg_dollar_volume is not None and avg_dollar_volume < float(
        cfg["min_avg_dollar_volume_usd"]
    ):
        return None

    return {
        "symbol": symbol,
        "display_name": row.get("instrumentDisplayName") or "",
        "instrument_id": instrument_id,
        "asset_type": _TYPE_IDS.get(int(row.get("instrumentTypeID") or 0), "stock"),
        "price": price,
        "spread_pct": round(spread_pct, 4) if spread_pct is not None else None,
        "annualized_vol_pct": round(vol_pct, 2) if vol_pct is not None else None,
        "avg_dollar_volume_usd": round(avg_dollar_volume) if avg_dollar_volume else None,
        "momentum_5d_pct": round(_momentum_pct(closes, 5), 2),
        "momentum_20d_pct": round(_momentum_pct(closes, 20), 2),
    }


def _momentum_norm(candidate: dict) -> float:
    m5 = max(-10.0, min(10.0, candidate["momentum_5d_pct"])) / 10.0
    m20 = max(-20.0, min(20.0, candidate["momentum_20d_pct"])) / 20.0
    return ((m5 + m20) / 2 + 1.0) / 2.0


def _interest_score(candidate: dict, buzz: float, max_buzz: float) -> float:
    """Interesse ∈ [0,1] in modalità regex: 60% buzz, 40% momentum 5/20 sedute."""
    buzz_norm = buzz / max_buzz if max_buzz > 0 else 0.0
    return round(0.6 * buzz_norm + 0.4 * _momentum_norm(candidate), 4)


def _llm_interest_score(
    candidate: dict, confidence: float, buzz: float, max_buzz: float
) -> float:
    """Interesse ∈ [0,1] in modalità llm: 50% confidence dello scout, 30%
    momentum 5/20 sedute, 20% corroborazione dalle citazioni esplicite."""
    buzz_norm = buzz / max_buzz if max_buzz > 0 else 0.0
    return round(0.5 * confidence + 0.3 * _momentum_norm(candidate) + 0.2 * buzz_norm, 4)


# -- refresh -----------------------------------------------------------------


def refresh_universe(
    client: Any,
    settings: dict[str, Any] | None,
    news_items: list[dict],
    *,
    llm: Callable[..., str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Esegue la discovery e persiste lo stato; ritorna lo stato scritto.

    Modalità llm: lo scout propone, le regex corroborano; se lo scout fallisce
    si ricade sulla nomination regex. Qualsiasi errore degrada a universo
    dinamico invariato SENZA sollevare: la discovery è un'aggiunta, la
    watchlist resta sempre operativa.
    """
    cfg = discovery_config(settings)
    if not cfg["enabled"]:
        logger.info("universe discovery disabilitata")
        return {"enabled": False, "tickers": []}

    watchlist = {str(s).upper() for s in (settings or {}).get("watchlist") or []}
    previous = {
        str(t.get("symbol") or "").upper(): t for t in discovered_instruments(settings)
    }
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        catalogue: dict[str, dict] = {}
        for type_id in _TYPE_IDS:
            for row in client.get_instruments_by_type(type_id):
                symbol = str(row.get("symbolFull") or "").upper()
                if symbol and "instrumentID" in row:
                    catalogue.setdefault(symbol, {**row, "instrumentTypeID": type_id})

        regex_scores = nominate(
            news_items,
            catalogue,
            half_life_days=float(cfg["news_half_life_days"]),
            exclude=watchlist,
            now=now,
        )

        # Nomination: scout LLM (primario) con fallback automatico alle regex.
        rejected: list[dict] = []
        candidates: dict[str, dict] = {}  # symbol → {confidence, thesis, news_refs}
        mode_used = "regex"
        if str(cfg["mode"]).lower() == "llm":
            try:
                proposals = llm_scout(
                    news_items, settings,
                    sorted(watchlist | set(previous)), llm=llm,
                )
                by_name = _catalogue_by_name(catalogue)
                for proposal in proposals:
                    symbol = resolve_proposal(proposal, catalogue, by_name)
                    if symbol is None:
                        rejected.append({
                            "symbol": proposal.symbol or proposal.company,
                            "reason": "non risolto sul catalogo eToro",
                        })
                        continue
                    if symbol in watchlist:
                        rejected.append({"symbol": symbol, "reason": "già in watchlist"})
                        continue
                    if proposal.confidence < float(cfg["min_confidence"]):
                        rejected.append({
                            "symbol": symbol,
                            "reason": f"confidence {proposal.confidence:.2f} sotto soglia",
                        })
                        continue
                    known = candidates.get(symbol)
                    if known is None or proposal.confidence > known["confidence"]:
                        candidates[symbol] = {
                            "confidence": proposal.confidence,
                            "thesis": proposal.thesis,
                            "news_refs": proposal.news_refs,
                        }
                mode_used = "llm"
            except Exception as exc:
                logger.warning("scout LLM non disponibile (fallback regex): %s", exc)
        if mode_used == "regex":
            for symbol, entry in regex_scores.items():
                if entry["mentions"] >= int(cfg["min_mentions"]):
                    candidates[symbol] = {"confidence": None, "thesis": "", "news_refs": []}

        def _priority(symbol: str) -> float:
            confidence = candidates[symbol]["confidence"]
            if confidence is not None:
                return confidence
            return regex_scores.get(symbol, {}).get("buzz", 0.0)

        order = sorted(candidates, key=_priority, reverse=True)[: int(cfg["max_evaluated"])]

        max_buzz = max(
            (regex_scores.get(s, {}).get("buzz", 0.0) for s in order), default=0.0
        )
        survivors: list[dict] = []
        for symbol in order:
            try:
                candidate = _evaluate(client, catalogue[symbol], cfg)
            except Exception as exc:
                logger.warning("universe: valutazione %s fallita: %s", symbol, exc)
                continue
            if candidate is None:
                rejected.append({
                    "symbol": symbol, "reason": "screening di affidabilità non superato",
                })
                continue
            meta = candidates[symbol]
            buzz = regex_scores.get(symbol, {}).get("buzz", 0.0)
            candidate["mentions"] = regex_scores.get(symbol, {}).get("mentions", 0)
            candidate["buzz"] = round(buzz, 4)
            if mode_used == "llm":
                candidate["confidence"] = meta["confidence"]
                candidate["thesis"] = meta["thesis"]
                candidate["news_refs"] = meta["news_refs"]
                candidate["source"] = "llm+regex" if buzz > 0 else "llm"
                candidate["score"] = _llm_interest_score(
                    candidate, meta["confidence"], buzz, max_buzz
                )
            else:
                candidate["thesis"] = ""
                candidate["source"] = "regex"
                candidate["score"] = _interest_score(candidate, buzz, max_buzz)
            survivors.append(candidate)

        survivors.sort(key=lambda c: c["score"], reverse=True)
        selected = survivors[: int(cfg["size"])]
        selected_symbols = {c["symbol"] for c in selected}
        for candidate in selected:
            prev = previous.get(candidate["symbol"]) or {}
            candidate["first_seen"] = prev.get("first_seen") or now_iso
            candidate["last_confirmed"] = now_iso
            candidate["misses"] = 0

        # Isteresi: chi era nell'universo e non è stato riconfermato resta per
        # keep_misses-1 refresh, purché superi ancora lo screening.
        holdovers: list[dict] = []
        for symbol, prev in previous.items():
            if symbol in selected_symbols or symbol in watchlist:
                continue
            misses = int(prev.get("misses") or 0) + 1
            if misses >= int(cfg["keep_misses"]):
                rejected.append({
                    "symbol": symbol,
                    "reason": f"uscito: nessuna riconferma per {misses} refresh",
                })
                continue
            row = catalogue.get(symbol)
            try:
                still_reliable = row is not None and _evaluate(client, row, cfg) is not None
            except Exception:
                still_reliable = False
            if not still_reliable:
                rejected.append({
                    "symbol": symbol,
                    "reason": "uscito: screening di affidabilità non più superato",
                })
                continue
            holdovers.append({**prev, "misses": misses})
        holdovers.sort(key=lambda c: float(c.get("score") or 0.0), reverse=True)

        state = {
            "generated_at": now_iso,
            "enabled": True,
            "mode": mode_used,
            "nominated": len(candidates),
            "evaluated": len(order),
            "tickers": selected + holdovers[: int(cfg["size"])],
            "rejected": rejected[:20],
        }
    except Exception as exc:
        logger.warning("universe discovery fallita (universo dinamico invariato): %s", exc)
        return {"enabled": True, "error": str(exc), "tickers": discovered_instruments(settings)}

    try:
        path = state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        logger.warning("universe: stato non persistito: %s", exc)

    logger.info(
        "universe discovery: %d citati, %d valutati, %d selezionati (%s)",
        state["nominated"], state["evaluated"], len(state["tickers"]),
        ", ".join(t["symbol"] for t in state["tickers"]) or "nessuno",
    )
    return state


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from etoro_bot.config import load_settings
    from etoro_bot.etoro.client import EtoroClient
    from etoro_bot.knowledge.fetch_news import fetch_all

    cli_settings = load_settings()
    cli_client = EtoroClient(
        api_key=os.environ.get("ETORO_API_KEY", ""),
        user_key=os.environ.get("ETORO_USER_KEY", ""),
        environment=str(cli_settings.get("environment", "demo")),
    )
    result = refresh_universe(cli_client, cli_settings, fetch_all(cli_settings))
    print(json.dumps(result, ensure_ascii=False, indent=2))
