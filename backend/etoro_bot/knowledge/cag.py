"""CAG: contesto statico condiviso da tutti gli agenti, con prompt caching.

Il blocco system sfrutta il prompt caching automatico di OpenAI sui prefissi
ripetuti: per fare cache hit deve restare BYTE-IDENTICO tra le
chiamate, quindi la costruzione è deterministica — niente timestamp, niente
ordini casuali, solo il contenuto raw dei file di configurazione.
"""

from __future__ import annotations

import os
from pathlib import Path

from etoro_bot.config import CONFIG_DIR, load_settings

KNOWLEDGE_BASE_DIR = Path(
    os.environ.get("KNOWLEDGE_BASE_DIR", CONFIG_DIR.parent / "knowledge_base")
)
PLAYBOOK_FILENAME = "playbook.md"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def build_static_context() -> str:
    """Concatena in modo deterministico limiti di rischio, watchlist e playbook.

    Stesse configurazioni su disco → stessa stringa, byte per byte: è la
    condizione per il cache hit del prompt caching.
    """
    parts: list[str] = [
        "# Contesto statico del bot (limiti, universo, playbook)",
        "I limiti sotto sono i default di configurazione. I valori effettivi "
        "scelti dall'utente sono forniti nel contesto runtime e vengono sempre "
        "applicati dal risk manager deterministico.",
    ]

    risk_raw = _read_text(CONFIG_DIR / "risk_rules.yaml")
    if risk_raw:
        parts.append("## Default dei limiti di rischio (config/risk_rules.yaml)\n" + risk_raw)

    watchlist = load_settings().get("watchlist") or []
    if watchlist:
        parts.append("## Watchlist (universo investibile: solo stock ed ETF)\n"
                     + ", ".join(str(t) for t in watchlist))

    playbook = _read_text(KNOWLEDGE_BASE_DIR / PLAYBOOK_FILENAME)
    if playbook:
        parts.append("## Playbook operativo dell'utente\n" + playbook)

    return "\n\n".join(parts) + "\n"


def static_system_block() -> dict:
    """Blocco system condiviso dagli agenti (call_llm ne estrae il testo)."""
    return {
        "type": "text",
        "text": build_static_context(),
    }
