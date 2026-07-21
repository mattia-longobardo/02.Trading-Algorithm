"""Report periodici su filesystem locale del server, separati per utente."""

from __future__ import annotations

import hashlib
import os
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CADENCES = ("weekly", "monthly", "quarterly", "semiannual", "annual")
LABELS = {
    "weekly": "Weekly Report",
    "monthly": "Monthly Report",
    "quarterly": "Quarterly Report",
    "semiannual": "Semiannual Report",
    "annual": "Annual Report",
}


class ReportService:
    def __init__(self, repo, root: str | None = None):
        self.repo = repo
        self.root = Path(root or os.environ.get("REPORTS_DIR", "/app/reports"))

    def _user_root(self, user_id: str) -> Path:
        digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
        return self.root / digest

    @staticmethod
    def _period_end(cadence: str, today: date) -> date:
        if cadence == "weekly":
            return today + timedelta(days=6 - today.weekday())
        if cadence == "monthly":
            return date(today.year, today.month, monthrange(today.year, today.month)[1])
        if cadence == "quarterly":
            month = ((today.month - 1) // 3 + 1) * 3
            return date(today.year, month, monthrange(today.year, month)[1])
        if cadence == "semiannual":
            month = 6 if today.month <= 6 else 12
            return date(today.year, month, monthrange(today.year, month)[1])
        return date(today.year, 12, 31)

    def ensure_current(self, user_id: str) -> None:
        now = datetime.now(timezone.utc)
        for cadence in CADENCES:
            folder = self._user_root(user_id) / cadence
            folder.mkdir(parents=True, exist_ok=True)
            period_end = self._period_end(cadence, now.date())
            filename = f"{LABELS[cadence]} - {period_end:%Y%m%d}.md"
            path = folder / filename
            if path.exists():
                continue
            runs = self.repo.list_runs(limit=100)
            closed = self.repo.closed_positions()
            pnl = sum(float(row.realized_pnl_usd or 0) for row in closed)
            currency, rate = self._display_currency()
            pnl_line = f"- PnL realizzato: {pnl:,.2f} USD\n"
            if currency != "USD":
                pnl_line += f"- PnL realizzato ({currency}): {pnl * rate:,.2f} {currency}\n"
            content = (
                f"# {LABELS[cadence]} — {period_end:%Y-%m-%d}\n\n"
                f"Generato automaticamente da Trading Bot.\n\n"
                f"## Sintesi\n\n"
                f"- Periodo fino al: {period_end:%Y-%m-%d}\n"
                f"- Run registrate: {len(runs)}\n"
                f"- Trade chiusi: {len(closed)}\n"
                f"{pnl_line}"
                f"- Ultimo aggiornamento: {now.isoformat()} UTC\n"
            )
            path.write_text(content, encoding="utf-8")

    def _display_currency(self) -> tuple[str, float]:
        """Valuta di presentazione dalle impostazioni + tasso USD→valuta.

        I dati restano in USD (eToro ragiona in dollari): la valuta è solo un
        secondo taglio di lettura, aggiunto accanto all'importo in dollari.
        """
        try:
            from etoro_bot.services.fx import rate_for

            currency = str(self.repo.get_setting("currency") or "USD").upper()
            return currency, rate_for(currency)
        except Exception:  # DB o rete giù: il report resta in dollari
            return "USD", 1.0

    def list(self, user_id: str) -> list[dict]:
        self.ensure_current(user_id)
        items: list[dict] = []
        base = self._user_root(user_id)
        for cadence in CADENCES:
            for path in sorted((base / cadence).glob("*.md"), reverse=True):
                stat = path.stat()
                items.append(
                    {
                        "id": f"{cadence}/{path.name}",
                        "cadence": cadence,
                        "name": path.stem,
                        "filename": path.name,
                        "size_bytes": stat.st_size,
                        "updated_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                        "period_end": path.stem.rsplit(" - ", 1)[-1],
                    }
                )
        return items

    def read(self, user_id: str, report_id: str) -> tuple[str, Path]:
        cadence, separator, filename = report_id.partition("/")
        if not separator or cadence not in CADENCES or Path(filename).name != filename:
            raise FileNotFoundError(report_id)
        path = self._user_root(user_id) / cadence / filename
        if not path.is_file():
            raise FileNotFoundError(report_id)
        return path.read_text(encoding="utf-8"), path
