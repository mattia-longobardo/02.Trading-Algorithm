from datetime import date
from types import SimpleNamespace

from etoro_bot.services.reports import CADENCES, ReportService


class FakeRepo:
    def list_runs(self, limit=100):
        return [SimpleNamespace(run_id="run-1")]

    def closed_positions(self):
        return [SimpleNamespace(realized_pnl_usd=12.5)]


def test_period_end_names_are_stable_per_cadence():
    today = date(2026, 7, 21)
    assert ReportService._period_end("weekly", today) == date(2026, 7, 26)
    assert ReportService._period_end("monthly", today) == date(2026, 7, 31)
    assert ReportService._period_end("quarterly", today) == date(2026, 9, 30)
    assert ReportService._period_end("semiannual", today) == date(2026, 12, 31)
    assert ReportService._period_end("annual", today) == date(2026, 12, 31)


def test_ensure_current_preserves_existing_history(tmp_path):
    service = ReportService(FakeRepo(), root=str(tmp_path))
    user_id = "user@example.com"
    old_folder = service._user_root(user_id) / "weekly"
    old_folder.mkdir(parents=True)
    old = old_folder / "Weekly Report - 20260719.md"
    old.write_text("storico", encoding="utf-8")

    service.ensure_current(user_id)
    reports = service.list(user_id)

    assert old.read_text(encoding="utf-8") == "storico"
    assert len(reports) == len(CADENCES) + 1
    assert all(item["period_end"] for item in reports)
