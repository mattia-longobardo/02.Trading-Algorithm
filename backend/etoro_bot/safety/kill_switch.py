"""Kill switch fuori dal grafo: file KILL_SWITCH o env ETORO_BOT_KILL=1.

Nessuna dipendenza da DB, rete o LLM: deve funzionare sempre, anche con
Postgres giù. Controllato dall'executor prima di OGNI singolo ordine.
"""

from __future__ import annotations

import os
from pathlib import Path

KILL_SWITCH_FILENAME = "KILL_SWITCH"


def _kill_switch_path() -> Path:
    return Path(os.environ.get("KILL_SWITCH_DIR", ".")) / KILL_SWITCH_FILENAME


def kill_switch_active() -> bool:
    if os.environ.get("ETORO_BOT_KILL") == "1":
        return True
    return _kill_switch_path().exists()


def engage_kill_switch(reason: str = "manual") -> Path:
    path = _kill_switch_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reason + "\n", encoding="utf-8")
    return path


def release_kill_switch() -> bool:
    """Rimuove il file. L'env ETORO_BOT_KILL non è rimovibile da codice: vince sempre."""
    path = _kill_switch_path()
    if path.exists():
        path.unlink()
        return True
    return False
