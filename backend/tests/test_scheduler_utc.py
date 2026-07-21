"""Lo scheduling è sempre in UTC: `timezone` è solo presentazione."""

from datetime import datetime, timezone

import pytest

from etoro_bot.services import scheduler


class _FrozenDatetime(datetime):
    """datetime con un now() fissato, per rendere il test indipendente dall'orologio."""

    frozen = datetime(2026, 7, 21, 6, 0, tzinfo=timezone.utc)  # martedì

    @classmethod
    def now(cls, tz=None):
        return cls.frozen if tz is None else cls.frozen.astimezone(tz)


@pytest.fixture()
def frozen_clock(monkeypatch):
    monkeypatch.setattr(scheduler, "datetime", _FrozenDatetime)


@pytest.mark.parametrize("zone", ["Europe/Rome", "UTC", "Asia/Tokyo", "America/New_York"])
def test_next_run_is_the_same_instant_in_every_timezone(frozen_clock, zone):
    """Cambiare il fuso di visualizzazione non sposta l'ora di esecuzione."""
    settings = {"schedule_utc": "08:30", "timezone": zone, "weekdays_only": True}
    assert scheduler.next_run_at(settings) == "2026-07-21T08:30:00+00:00"


def test_time_already_passed_rolls_to_next_day(frozen_clock):
    settings = {"schedule_utc": "05:00", "timezone": "Europe/Rome", "weekdays_only": True}
    assert scheduler.next_run_at(settings) == "2026-07-22T05:00:00+00:00"


def test_weekend_is_skipped_on_utc_days(monkeypatch):
    class _Friday(_FrozenDatetime):
        frozen = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)  # venerdì pomeriggio

    monkeypatch.setattr(scheduler, "datetime", _Friday)
    settings = {"schedule_utc": "08:30", "timezone": "Europe/Rome", "weekdays_only": True}
    assert scheduler.next_run_at(settings) == "2026-07-27T08:30:00+00:00"  # lunedì
