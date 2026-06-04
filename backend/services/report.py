"""Report generation — weekly, quarterly, bi-annual and annual."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.utils import AppConfig, utc_now, write_json_file
from services.trade_manager import TradeManager


class ReportGenerator:
    """Generate PDF and JSON summaries for recent trading performance."""

    def __init__(self, config: AppConfig, logger: logging.Logger, trade_manager: TradeManager) -> None:
        self.config = config
        self.logger = logger.getChild("report")
        self.trade_manager = trade_manager

    def generate_weekly_report(self) -> dict:
        report = self.trade_manager.weekly_summary()
        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%d_%H%M%S")
        pdf_path = report_dir / f"weekly_report_{stamp}.pdf"
        self._render_pdf_report(report, pdf_path, title="Weekly Trading Report")
        json_path = report_dir / f"weekly_report_{stamp}.json"
        write_json_file(json_path, report)
        self.logger.info("Generated weekly report at %s", pdf_path)
        return report

    def generate_quarterly_report(self) -> dict:
        """Generate a report for the calendar quarter that just ended."""
        now = utc_now()
        # Snap back to the start of the current quarter, which is the end of the previous one.
        current_quarter_start_month = ((now.month - 1) // 3) * 3 + 1
        period_end = datetime(now.year, current_quarter_start_month, 1, tzinfo=UTC)
        # The previous quarter started 3 months before period_end.
        if current_quarter_start_month == 1:
            period_start = datetime(now.year - 1, 10, 1, tzinfo=UTC)
        else:
            period_start = datetime(now.year, current_quarter_start_month - 3, 1, tzinfo=UTC)
        quarter_num = (period_start.month - 1) // 3 + 1
        label = f"Q{quarter_num} {period_start.year}"
        return self._generate_period_report("quarterly", label, period_start, period_end)

    def generate_biannual_report(self) -> dict:
        """Generate a report for the half-year that just ended."""
        now = utc_now()
        # Snap to the start of the current half, which is the end of the previous half.
        if now.month >= 7:
            # We are in H2 — the last completed half is H1 (Jan–Jun) of this year.
            period_start = datetime(now.year, 1, 1, tzinfo=UTC)
            period_end = datetime(now.year, 7, 1, tzinfo=UTC)
            label = f"H1 {now.year}"
        else:
            # We are in H1 — the last completed half is H2 (Jul–Dec) of the previous year.
            period_start = datetime(now.year - 1, 7, 1, tzinfo=UTC)
            period_end = datetime(now.year, 1, 1, tzinfo=UTC)
            label = f"H2 {now.year - 1}"
        return self._generate_period_report("biannual", label, period_start, period_end)

    def generate_annual_report(self) -> dict:
        """Generate a report for the calendar year that just ended."""
        now = utc_now()
        year = now.year - 1
        period_start = datetime(year, 1, 1, tzinfo=UTC)
        period_end = datetime(now.year, 1, 1, tzinfo=UTC)
        label = f"Annual {year}"
        return self._generate_period_report("annual", label, period_start, period_end)

    def _generate_period_report(
        self,
        report_type: str,
        label: str,
        period_start: datetime,
        period_end: datetime,
    ) -> dict:
        report = self.trade_manager.period_summary(period_start, period_end)
        report["label"] = label
        report_dir = Path(self.config.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = utc_now().strftime("%Y%m%d_%H%M%S")
        slug = label.lower().replace(" ", "_")
        pdf_path = report_dir / f"{report_type}_report_{slug}_{stamp}.pdf"
        self._render_pdf_report(report, pdf_path, title=f"{label} Trading Report", is_period=True)
        json_path = report_dir / f"{report_type}_report_{slug}_{stamp}.json"
        write_json_file(json_path, report)
        self.logger.info("Generated %s report (%s) at %s", report_type, label, pdf_path)
        return report

    def _render_pdf_report(
        self,
        report: dict[str, Any],
        destination: Path,
        *,
        title: str = "Trading Report",
        is_period: bool = False,
    ) -> None:
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=28,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_LEFT,
            spaceAfter=6,
        )
        subtitle_style = ParagraphStyle(
            "ReportSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#475569"),
            spaceAfter=14,
        )
        section_style = ParagraphStyle(
            "SectionHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#111827"),
            spaceAfter=8,
            spaceBefore=10,
        )
        body_style = ParagraphStyle(
            "BodyCopy",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#1f2937"),
        )
        metric_label_style = ParagraphStyle(
            "MetricLabel",
            parent=body_style,
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#64748b"),
            alignment=TA_LEFT,
        )
        metric_value_style = ParagraphStyle(
            "MetricValue",
            parent=body_style,
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_LEFT,
        )
        metric_sub_style = ParagraphStyle(
            "MetricSub",
            parent=body_style,
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#475569"),
            alignment=TA_LEFT,
        )
        table_cell_style = ParagraphStyle(
            "TableCell",
            parent=body_style,
            fontSize=8,
            leading=10,
        )
        table_cell_right_style = ParagraphStyle(
            "TableCellRight",
            parent=table_cell_style,
            alignment=TA_RIGHT,
        )

        document = SimpleDocTemplate(
            str(destination),
            pagesize=A4,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=title,
            author="Trading Algorithm",
        )

        story: list[Any] = []
        generated_at = utc_now().isoformat()
        story.append(Paragraph(title, title_style))
        story.append(Paragraph(f"Generated at {generated_at}", subtitle_style))
        story.append(self._build_summary_table(report, metric_label_style, metric_value_style, metric_sub_style, is_period=is_period))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Performance Overview", section_style))
        story.append(Paragraph(self._build_overview_text(report, is_period=is_period), body_style))
        story.append(Spacer(1, 6))
        story.append(Paragraph("PnL by Category", section_style))
        story.append(self._build_category_table(report, table_cell_style, table_cell_right_style))
        story.append(Paragraph("Most Traded Symbols", section_style))
        story.append(self._build_symbols_table(report, table_cell_style, table_cell_right_style))
        story.append(Paragraph("Trade Snapshot", section_style))
        story.append(self._build_trades_table(report, table_cell_style, table_cell_right_style, is_period=is_period))
        if is_period and report.get("carry_over_trades"):
            story.append(Paragraph("Carry-Over (Open into Next Period)", section_style))
            story.append(self._build_carry_over_table(report, table_cell_style, table_cell_right_style))

        document.build(story, onFirstPage=self._draw_page_chrome, onLaterPages=self._draw_page_chrome)

    def _build_summary_table(
        self,
        report: dict[str, Any],
        label_style: ParagraphStyle,
        value_style: ParagraphStyle,
        sub_style: ParagraphStyle,
        *,
        is_period: bool = False,
    ) -> Table:
        best_trade = report.get("best_trade") or {}
        worst_trade = report.get("worst_trade") or {}
        if is_period:
            carry_over_count = len(report.get("carry_over_trades", []))
            closed_count = len(report.get("closed_trades", []))
            active_subtitle = f"Closed {closed_count} | Carry-over {carry_over_count}"
            active_label = "Carry-Over"
            active_value = str(carry_over_count)
        else:
            active_label = "Open + Pending"
            active_value = str(len(report.get("open_trades", [])) + len(report.get("pending_trades", [])))
            active_subtitle = f"Closed {len(report.get('closed_trades', []))}"
        metrics = [
            (
                "Total PnL",
                self._format_number(report.get("pnl_total")),
                f"Win rate {self._format_percent(report.get('win_rate'))}",
            ),
            (
                active_label,
                active_value,
                active_subtitle,
            ),
            (
                "Best Trade",
                str(best_trade.get("symbol", "N/A")),
                self._format_number(best_trade.get("pnl")),
            ),
            (
                "Worst Trade",
                str(worst_trade.get("symbol", "N/A")),
                self._format_number(worst_trade.get("pnl")),
            ),
        ]
        rows = [
            [
                Paragraph(label, label_style),
                Paragraph(value, value_style),
                Paragraph(subtitle, sub_style),
            ]
            for label, value, subtitle in metrics
        ]
        table = Table(rows, colWidths=[34 * mm, 38 * mm, 42 * mm], hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
                    ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cbd5e1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        return table

    def _build_category_table(
        self,
        report: dict[str, Any],
        cell_style: ParagraphStyle,
        right_style: ParagraphStyle,
    ) -> Table:
        pnl_by_category = report.get("pnl_by_category", {}) or {}
        rows = [[Paragraph("Category", cell_style), Paragraph("PnL", right_style)]]
        if pnl_by_category:
            for category, value in sorted(pnl_by_category.items()):
                rows.append([Paragraph(str(category), cell_style), Paragraph(self._format_number(value), right_style)])
        else:
            rows.append([Paragraph("No closed trades", cell_style), Paragraph("-", right_style)])
        return self._styled_table(rows, [80 * mm, 35 * mm])

    def _build_symbols_table(
        self,
        report: dict[str, Any],
        cell_style: ParagraphStyle,
        right_style: ParagraphStyle,
    ) -> Table:
        rows = [[Paragraph("Symbol", cell_style), Paragraph("Trades", right_style)]]
        most_traded = report.get("most_traded_symbols", []) or []
        if most_traded:
            for symbol, count in most_traded:
                rows.append([Paragraph(str(symbol), cell_style), Paragraph(str(count), right_style)])
        else:
            rows.append([Paragraph("No activity", cell_style), Paragraph("-", right_style)])
        return self._styled_table(rows, [80 * mm, 35 * mm])

    def _build_trades_table(
        self,
        report: dict[str, Any],
        cell_style: ParagraphStyle,
        right_style: ParagraphStyle,
        *,
        is_period: bool = False,
    ) -> Table:
        rows = [
            [
                Paragraph("Symbol", cell_style),
                Paragraph("Category", cell_style),
                Paragraph("Status", cell_style),
                Paragraph("PnL", right_style),
            ]
        ]
        if is_period:
            trades = (report.get("closed_trades", []) or [])[:20]
        else:
            trades = [
                *(report.get("open_trades", []) or []),
                *(report.get("pending_trades", []) or []),
                *(report.get("closed_trades", []) or [])[:12],
            ]
        if trades:
            for trade in trades:
                rows.append(
                    [
                        Paragraph(str(trade.get("symbol", "N/A")), cell_style),
                        Paragraph(str(trade.get("category", "N/A")), cell_style),
                        Paragraph(str(trade.get("status", "N/A")), cell_style),
                        Paragraph(self._format_number(trade.get("pnl")), right_style),
                    ]
                )
        else:
            rows.append(
                [
                    Paragraph("No closed trades in this period", cell_style),
                    Paragraph("-", cell_style),
                    Paragraph("-", cell_style),
                    Paragraph("-", right_style),
                ]
            )
        return self._styled_table(rows, [45 * mm, 30 * mm, 30 * mm, 30 * mm], repeat_rows=1)

    def _build_carry_over_table(
        self,
        report: dict[str, Any],
        cell_style: ParagraphStyle,
        right_style: ParagraphStyle,
    ) -> Table:
        rows = [
            [
                Paragraph("Symbol", cell_style),
                Paragraph("Category", cell_style),
                Paragraph("Open Since", cell_style),
                Paragraph("Unrealised PnL", right_style),
            ]
        ]
        for trade in report.get("carry_over_trades", []) or []:
            open_ts = trade.get("open_timestamp") or trade.get("created_at") or "N/A"
            rows.append(
                [
                    Paragraph(str(trade.get("symbol", "N/A")), cell_style),
                    Paragraph(str(trade.get("category", "N/A")), cell_style),
                    Paragraph(str(open_ts)[:10], cell_style),
                    Paragraph(self._format_number(trade.get("pnl")), right_style),
                ]
            )
        return self._styled_table(rows, [45 * mm, 30 * mm, 35 * mm, 30 * mm], repeat_rows=1)

    def _styled_table(self, rows: list[list[Paragraph]], col_widths: list[float], repeat_rows: int = 1) -> Table:
        table = Table(rows, colWidths=col_widths, hAlign="LEFT", repeatRows=repeat_rows)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#cbd5e1")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return table

    def _build_overview_text(self, report: dict[str, Any], *, is_period: bool = False) -> str:
        best = report.get("best_trade") or {}
        worst = report.get("worst_trade") or {}
        if is_period:
            period_start = (report.get("period_start") or "")[:10]
            period_end = (report.get("period_end") or "")[:10]
            carry_count = len(report.get("carry_over_trades", []))
            closed_count = len(report.get("closed_trades", []))
            return (
                f"This report covers the period from {period_start} to {period_end}. "
                f"{closed_count} trades were closed during this period. "
                f"{carry_count} trades were not closed and carry over as open into the next period. "
                f"Best trade: {best.get('symbol', 'N/A')} with {self._format_number(best.get('pnl'))}. "
                f"Worst trade: {worst.get('symbol', 'N/A')} with {self._format_number(worst.get('pnl'))}."
            )
        return (
            f"This report summarizes cumulative trading activity up to this week. "
            f"There are {len(report.get('open_trades', []))} open trades, "
            f"{len(report.get('pending_trades', []))} pending trades and "
            f"{len(report.get('closed_trades', []))} closed trades in scope. "
            f"Best trade: {best.get('symbol', 'N/A')} with {self._format_number(best.get('pnl'))}. "
            f"Worst trade: {worst.get('symbol', 'N/A')} with {self._format_number(worst.get('pnl'))}."
        )

    @staticmethod
    def _format_number(value: Any) -> str:
        try:
            if value is None:
                return "N/A"
            return f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _format_percent(value: Any) -> str:
        try:
            if value is None:
                return "N/A"
            return f"{float(value) * 100:.2f}%"
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _draw_page_chrome(canvas: Any, document: Any) -> None:
        canvas.saveState()
        page_width, page_height = A4
        canvas.setFillColor(colors.HexColor("#0f172a"))
        canvas.rect(0, page_height - 18 * mm, page_width, 18 * mm, fill=1, stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 11)
        canvas.drawString(16 * mm, page_height - 11 * mm, "Trading Algorithm")
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(page_width - 16 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()
