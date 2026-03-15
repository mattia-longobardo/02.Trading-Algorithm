"""Weekly report generation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from trade_manager import TradeManager
from utils import utc_now


class ReportGenerator:
    """Generate text and JSON summaries for recent trading performance."""

    def __init__(self, logger: logging.Logger, trade_manager: TradeManager) -> None:
        self.logger = logger.getChild("report")
        self.trade_manager = trade_manager

    def generate_weekly_report(self) -> dict:
        report = self.trade_manager.weekly_summary()
        report_dir = Path("reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%d_%H%M%S")
        json_path = report_dir / f"weekly_report_{stamp}.json"
        txt_path = report_dir / f"weekly_report_{stamp}.txt"
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        txt_path.write_text(self._render_text_report(report), encoding="utf-8")
        self.logger.info("Generated weekly report at %s", json_path)
        return report

    def _render_text_report(self, report: dict) -> str:
        best = report.get("best_trade") or {}
        worst = report.get("worst_trade") or {}
        return "\n".join(
            [
                "Weekly Trading Report",
                f"Generated at: {utc_now().isoformat()}",
                f"Open trades: {len(report.get('open_trades', []))}",
                f"Pending trades: {len(report.get('pending_trades', []))}",
                f"Closed trades: {len(report.get('closed_trades', []))}",
                f"Total PnL: {report.get('pnl_total', 0)}",
                f"PnL by category: {report.get('pnl_by_category', {})}",
                f"Win rate: {report.get('win_rate', 0)}",
                f"Best trade: {best.get('symbol', 'N/A')} ({best.get('pnl', 'N/A')})",
                f"Worst trade: {worst.get('symbol', 'N/A')} ({worst.get('pnl', 'N/A')})",
                f"Most traded symbols: {report.get('most_traded_symbols', [])}",
            ]
        )
