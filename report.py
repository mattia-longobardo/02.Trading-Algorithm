"""Weekly report generation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from trade_manager import TradeManager
from utils import AppConfig, utc_now


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
        json_path = report_dir / f"weekly_report_{stamp}.json"
        pdf_path = report_dir / f"weekly_report_{stamp}.pdf"
        json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
        self._render_pdf_report(report, pdf_path)
        self.logger.info("Generated weekly report at %s and %s", json_path, pdf_path)
        return report

    def _render_pdf_report(self, report: dict[str, Any], destination: Path) -> None:
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
            title="Weekly Trading Report",
            author="Trading Algorithm",
        )

        story: list[Any] = []
        generated_at = utc_now().isoformat()
        story.append(Paragraph("Weekly Trading Report", title_style))
        story.append(Paragraph(f"Generated at {generated_at}", subtitle_style))
        story.append(self._build_summary_table(report, metric_label_style, metric_value_style, metric_sub_style))
        story.append(Spacer(1, 8))
        story.append(Paragraph("Performance Overview", section_style))
        story.append(Paragraph(self._build_overview_text(report), body_style))
        story.append(Spacer(1, 6))
        story.append(Paragraph("PnL by Category", section_style))
        story.append(self._build_category_table(report, table_cell_style, table_cell_right_style))
        story.append(Paragraph("Most Traded Symbols", section_style))
        story.append(self._build_symbols_table(report, table_cell_style, table_cell_right_style))
        story.append(Paragraph("Trade Snapshot", section_style))
        story.append(self._build_trades_table(report, table_cell_style, table_cell_right_style))

        document.build(story, onFirstPage=self._draw_page_chrome, onLaterPages=self._draw_page_chrome)

    def _build_summary_table(
        self,
        report: dict[str, Any],
        label_style: ParagraphStyle,
        value_style: ParagraphStyle,
        sub_style: ParagraphStyle,
    ) -> Table:
        best_trade = report.get("best_trade") or {}
        worst_trade = report.get("worst_trade") or {}
        metrics = [
            (
                "Total PnL",
                self._format_number(report.get("pnl_total")),
                f"Win rate {self._format_percent(report.get('win_rate'))}",
            ),
            (
                "Open + Pending",
                str(len(report.get("open_trades", [])) + len(report.get("pending_trades", []))),
                f"Closed {len(report.get('closed_trades', []))} | Cancelled {len(report.get('cancelled_trades', []))}",
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
    ) -> Table:
        rows = [
            [
                Paragraph("Symbol", cell_style),
                Paragraph("Category", cell_style),
                Paragraph("Status", cell_style),
                Paragraph("PnL", right_style),
            ]
        ]
        trades = [
            *(report.get("open_trades", []) or []),
            *(report.get("pending_trades", []) or []),
            *(report.get("cancelled_trades", []) or [])[:8],
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
                    Paragraph("No trades available", cell_style),
                    Paragraph("-", cell_style),
                    Paragraph("-", cell_style),
                    Paragraph("-", right_style),
                ]
            )
        return self._styled_table(rows, [45 * mm, 30 * mm, 30 * mm, 30 * mm], repeat_rows=1)

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

    def _build_overview_text(self, report: dict[str, Any]) -> str:
        best = report.get("best_trade") or {}
        worst = report.get("worst_trade") or {}
        return (
            f"This report summarizes the last seven days of trading activity. "
            f"There are {len(report.get('open_trades', []))} open trades, "
            f"{len(report.get('pending_trades', []))} pending trades and "
            f"{len(report.get('closed_trades', []))} closed trades plus "
            f"{len(report.get('cancelled_trades', []))} cancelled trades in scope. "
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
