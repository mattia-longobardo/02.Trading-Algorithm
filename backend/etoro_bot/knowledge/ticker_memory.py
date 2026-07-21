"""Memoria evolutiva per titolo, aggiornata a ogni fetch di news.

Per ogni ticker dell'universo il bot mantiene un file JSON in
`$STATE_DIR/ticker_memory/{TICKER}.json` con:

  - `entries`: le notizie recenti (deduplicate, con timestamp), potate per
    età (`retention_days`) e numero (`max_entries`) — le news vecchie escono
    da sole dalla memoria;
  - `summary`: una sintesi «viva» del titolo (temi persistenti, catalizzatori,
    rischi) riscritta dall'LLM a ogni aggiornamento partendo dalla sintesi
    precedente + le notizie nuove. Senza LLM (chiave assente, errore, o
    `use_llm: false`) la sintesi degrada alle ultime headline: la memoria
    funziona sempre, l'LLM la rende solo migliore.

La memoria è consumata dall'analista sentiment (contesto per candidato) e
esposta dall'API alla pagina Knowledge.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "retention_days": 30,
    "max_entries": 40,
    "use_llm": True,
}

_SUMMARY_MAX_WORDS = 150
_FALLBACK_HEADLINES = 5
_SAFE_TICKER_RE = re.compile(r"^[A-Z0-9.\-]{1,12}$")


def memory_config(settings: dict[str, Any] | None) -> dict[str, Any]:
    raw = ((settings or {}).get("knowledge") or {}).get("ticker_memory") or {}
    return {**DEFAULTS, **{k: raw[k] for k in raw if k in DEFAULTS}}


def _memory_dir() -> Path:
    return Path(os.environ.get("STATE_DIR", "/app/state")) / "ticker_memory"


def _memory_file(ticker: str) -> Path | None:
    symbol = ticker.strip().upper()
    if not _SAFE_TICKER_RE.match(symbol):  # il ticker finisce in un nome file
        return None
    return _memory_dir() / f"{symbol}.json"


def load_memory(ticker: str) -> dict | None:
    path = _memory_file(ticker)
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("memoria %s illeggibile: ignorata", ticker)
        return None


def all_memories() -> list[dict]:
    """Tutte le memorie persistite, ordinate per ticker."""
    directory = _memory_dir()
    if not directory.is_dir():
        return []
    memories = []
    for path in sorted(directory.glob("*.json")):
        try:
            memories.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return memories


def memory_context(ticker: str) -> str:
    """Contesto compatto per i prompt: sintesi + ultime headline; "" se assente."""
    memory = load_memory(ticker)
    if not memory:
        return ""
    parts = []
    summary = str(memory.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    latest = [
        f"({e.get('date', '?')}) {str(e.get('text') or '')[:160]}"
        for e in (memory.get("entries") or [])[-3:]
    ]
    if latest:
        parts.append("Ultime notizie: " + " | ".join(reversed(latest)))
    return "\n".join(parts)


# -- aggiornamento -----------------------------------------------------------


def _entry_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _fallback_summary(entries: list[dict]) -> str:
    headlines = [
        f"- ({e.get('date', '?')}) {str(e.get('text') or '')[:200]}"
        for e in entries[-_FALLBACK_HEADLINES:]
    ]
    return "Ultime notizie (più recenti in fondo):\n" + "\n".join(headlines)


def _llm_summary(
    ticker: str,
    previous_summary: str,
    fresh_entries: list[dict],
    settings: dict[str, Any],
    llm: Callable[..., str] | None,
) -> str | None:
    """Sintesi aggiornata via LLM; None su qualsiasi errore (→ fallback)."""
    fresh = "\n".join(
        f"- ({e.get('date', '?')}) [{e.get('source', '?')}] {str(e.get('text') or '')[:300]}"
        for e in fresh_entries
    )
    prompt = (
        f"Sei il curatore della memoria del titolo {ticker} per un bot di swing "
        "trading. Aggiorna la memoria integrando le notizie nuove in quella "
        "esistente: conserva i temi ancora rilevanti, aggiorna ciò che è "
        "cambiato, elimina ciò che è superato. Copri: temi persistenti, "
        "catalizzatori attesi, rischi. NON inventare fatti non presenti.\n\n"
        f"Memoria attuale:\n{previous_summary or '(vuota)'}\n\n"
        f"Notizie nuove:\n{fresh}\n\n"
        f"Rispondi SOLO con la memoria aggiornata, max {_SUMMARY_MAX_WORDS} parole."
    )
    try:
        if llm is None:
            from etoro_bot.graph.llm import call_llm

            llm = call_llm
        llm_cfg = (settings or {}).get("llm") or {}
        text = llm(
            system_blocks=[],
            user_prompt=prompt,
            model=str(llm_cfg.get("model", "gpt-5.6-terra")),
            max_tokens=int(llm_cfg.get("max_tokens", 2048)),
        )
        return text.strip() or None
    except Exception as exc:
        logger.warning("sintesi LLM per %s fallita (fallback headline): %s", ticker, exc)
        return None


def update_memories(
    items: list[dict],
    settings: dict[str, Any] | None = None,
    *,
    llm: Callable[..., str] | None = None,
    now: float | None = None,
) -> dict[str, int]:
    """Aggiorna le memorie dei ticker citati negli item news.

    Ritorna {ticker: nuove_entry}. Qualsiasi errore su un ticker logga e
    continua con gli altri: la memoria è un'aggiunta, mai un requisito.
    """
    cfg = memory_config(settings)
    if not cfg["enabled"]:
        return {}
    now = now if now is not None else time.time()

    from etoro_bot.knowledge.kb import parse_published_ts

    by_ticker: dict[str, list[dict]] = {}
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text or str(item.get("kind") or "news") != "news":
            continue
        ts = parse_published_ts(str(item.get("published_at") or "")) or now
        entry = {
            "id": _entry_id(text),
            "ts": ts,
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat(),
            "text": text,
            "source": str(item.get("source") or ""),
        }
        for ticker in item.get("tickers") or []:
            symbol = str(ticker).strip().upper()
            if symbol:
                by_ticker.setdefault(symbol, []).append(entry)

    updated: dict[str, int] = {}
    cutoff = now - float(cfg["retention_days"]) * 86400.0
    for symbol, fresh in by_ticker.items():
        path = _memory_file(symbol)
        if path is None:
            logger.warning("ticker %s non valido come nome memoria: saltato", symbol)
            continue
        try:
            memory = load_memory(symbol) or {"ticker": symbol, "summary": "", "entries": []}
            known = {e.get("id") for e in memory["entries"]}
            new_entries = [e for e in fresh if e["id"] not in known]
            if not new_entries:
                continue

            entries = memory["entries"] + sorted(new_entries, key=lambda e: e["ts"])
            entries = [e for e in entries if float(e.get("ts") or 0) >= cutoff]
            entries.sort(key=lambda e: float(e.get("ts") or 0))
            entries = entries[-int(cfg["max_entries"]):]

            summary = None
            if cfg["use_llm"]:
                summary = _llm_summary(
                    symbol, str(memory.get("summary") or ""), new_entries, settings or {}, llm
                )
            summary_source = "llm" if summary else "headline"
            memory.update(
                {
                    "ticker": symbol,
                    "entries": entries,
                    "summary": summary or _fallback_summary(entries),
                    "summary_source": summary_source,
                    "updated_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
                }
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
            updated[symbol] = len(new_entries)
        except Exception as exc:
            logger.warning("aggiornamento memoria %s fallito, continuo: %s", symbol, exc)
    if updated:
        logger.info(
            "ticker memory: aggiornati %d titoli (%s)",
            len(updated), ", ".join(sorted(updated)),
        )
    return updated
