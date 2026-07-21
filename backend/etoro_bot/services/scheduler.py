"""Scheduler del bot: fetch news 15 minuti prima della run, run all'orario
configurato (default 08:30, lun-ven). L'orario è riletto a ogni tick così un
cambio dalle Impostazioni vale senza riavvio.

L'esecuzione è **sempre in UTC**: `schedule_utc` è un orario UTC e anche il
filtro `weekdays_only` guarda il giorno UTC. L'impostazione `timezone` non
tocca lo scheduling — serve solo alla UI per mostrare gli orari nel fuso
dell'utente, così l'ora di run non si sposta con l'ora legale.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger("etoro_bot.scheduler")


def _parse_hhmm(value: str) -> tuple[int, int]:
    hh, mm = value.split(":")
    return int(hh), int(mm)


def next_run_at(settings: dict[str, Any]) -> str:
    """Prossima esecuzione schedulata in ISO 8601 UTC."""
    hh, mm = _parse_hhmm(str(settings.get("schedule_utc", "08:30")))
    weekdays_only = bool(settings.get("weekdays_only", True))
    now = datetime.now(timezone.utc)
    candidate = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    while weekdays_only and candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def start_scheduler(get_settings, run_job, news_job):
    """Avvia APScheduler. get_settings() è richiamata a ogni minuto per leggere
    l'orario effettivo (DB > yaml); run_job/news_job sono callable senza argomenti.
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    state: dict[str, str | None] = {"last_run_day": None, "last_news_day": None}

    def tick() -> None:
        try:
            settings = get_settings()
        except Exception:
            log.warning("settings non disponibili, tick saltato", exc_info=True)
            return
        now = datetime.now(timezone.utc)
        if bool(settings.get("weekdays_only", True)) and now.weekday() >= 5:
            return
        today = now.date().isoformat()

        run_hh, run_mm = _parse_hhmm(str(settings.get("schedule_utc", "08:30")))
        news_time = now.replace(hour=run_hh, minute=run_mm) - timedelta(minutes=15)

        if (
            state["last_news_day"] != today
            and (now.hour, now.minute) >= (news_time.hour, news_time.minute)
        ):
            state["last_news_day"] = today
            _safe(news_job, "news")

        if state["last_run_day"] != today and (now.hour, now.minute) >= (run_hh, run_mm):
            state["last_run_day"] = today
            _safe(run_job, "run")

    def _safe(job, name: str) -> None:
        try:
            job()
        except Exception:
            log.exception("job schedulato '%s' fallito", name)

    scheduler.add_job(tick, "interval", minutes=1, id="etoro-bot-tick")
    scheduler.start()
    return scheduler
