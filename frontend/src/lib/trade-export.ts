import { type Trade } from "@/lib/types";

type CellValue = string | number | null | undefined;

interface ExportColumn {
  header: string;
  value: (trade: Trade) => CellValue;
}

const EXCEL_XML_TYPE = "application/vnd.ms-excel;charset=utf-8";

function tradePnlValue(trade: Trade): number {
  if (trade.status === "OPEN") return trade.unrealized_pnl ?? 0;
  return (trade.realized_pnl ?? 0) + (trade.unrealized_pnl ?? 0);
}

function tradePnlPercentValue(trade: Trade): number | null {
  if (trade.status === "OPEN" && trade.unrealized_pnl_pct !== undefined) {
    return trade.unrealized_pnl_pct;
  }
  if (!trade.allocated_capital) return null;
  return (tradePnlValue(trade) / trade.allocated_capital) * 100;
}

function timestampValue(trade: Trade): string | null {
  return trade.close_timestamp ?? trade.open_timestamp ?? trade.created_at ?? null;
}

const TRADE_EXPORT_COLUMNS: ExportColumn[] = [
  { header: "ID", value: (trade) => trade.id },
  { header: "Simbolo", value: (trade) => trade.symbol },
  { header: "Categoria", value: (trade) => trade.category },
  { header: "Direzione", value: (trade) => trade.direction },
  { header: "Stato", value: (trade) => trade.status },
  { header: "Timestamp", value: timestampValue },
  { header: "Aperto", value: (trade) => trade.open_timestamp },
  { header: "Chiuso", value: (trade) => trade.close_timestamp },
  { header: "Prezzo entry", value: (trade) => trade.entry_price },
  { header: "Target entry", value: (trade) => trade.target_entry_price },
  { header: "Prezzo attuale", value: (trade) => trade.current_price },
  { header: "Prezzo uscita", value: (trade) => trade.close_price },
  { header: "Quantita", value: (trade) => trade.quantity },
  { header: "Capitale allocato", value: (trade) => trade.allocated_capital },
  { header: "PnL", value: tradePnlValue },
  { header: "PnL %", value: tradePnlPercentValue },
  { header: "PnL realizzato", value: (trade) => trade.realized_pnl },
  { header: "PnL non realizzato", value: (trade) => trade.unrealized_pnl },
  { header: "Take profit", value: (trade) => trade.take_profit },
  { header: "Stop loss", value: (trade) => trade.stop_loss },
  { header: "Trailing TP dist", value: (trade) => trade.trailing_take_profit_distance },
  { header: "Trailing TP arm %", value: (trade) => trade.trailing_take_profit_activation_pct },
  { header: "Trailing TP trigger", value: (trade) => trade.trailing_take_profit_price },
  { header: "High water mark", value: (trade) => trade.high_water_mark },
  { header: "Trailing stop dist", value: (trade) => trade.trailing_stop_distance },
  { header: "Trailing stop trigger", value: (trade) => trade.trailing_stop_price },
  { header: "Motivo chiusura", value: (trade) => trade.close_reason },
  { header: "Instrument ID", value: (trade) => trade.instrument_id },
  { header: "Position ID", value: (trade) => trade.position_id },
  { header: "Order reference ID", value: (trade) => trade.order_reference_id },
  { header: "Confidence", value: (trade) => trade.confidence },
  { header: "Trade score", value: (trade) => trade.trade_score },
  { header: "Valuta", value: (trade) => trade.account_currency },
  { header: "Creato", value: (trade) => trade.created_at },
  { header: "Aggiornato", value: (trade) => trade.updated_at },
  { header: "Reasoning", value: (trade) => trade.reasoning },
];

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function cell(value: CellValue): string {
  if (value === null || value === undefined) {
    return '<Cell><Data ss:Type="String"></Data></Cell>';
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return `<Cell><Data ss:Type="Number">${value}</Data></Cell>`;
  }
  return `<Cell><Data ss:Type="String">${escapeXml(String(value))}</Data></Cell>`;
}

function row(values: CellValue[]): string {
  return `<Row>${values.map(cell).join("")}</Row>`;
}

export function buildTradesExcelXml(trades: Trade[]): string {
  const header = row(TRADE_EXPORT_COLUMNS.map((column) => column.header));
  const body = trades.map((trade) => row(TRADE_EXPORT_COLUMNS.map((column) => column.value(trade)))).join("");

  return [
    '<?xml version="1.0"?>',
    '<?mso-application progid="Excel.Sheet"?>',
    '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"',
    ' xmlns:o="urn:schemas-microsoft-com:office:office"',
    ' xmlns:x="urn:schemas-microsoft-com:office:excel"',
    ' xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"',
    ' xmlns:html="http://www.w3.org/TR/REC-html40">',
    '<Worksheet ss:Name="Trade">',
    "<Table>",
    header,
    body,
    "</Table>",
    "</Worksheet>",
    "</Workbook>",
  ].join("");
}

export function buildTradesExcelFilename(fromDate: string, toDate: string): string {
  const from = fromDate || "inizio";
  const to = toDate || "fine";
  return `trades_${from}_${to}.xls`;
}

export function downloadTradesExcel(trades: Trade[], filename: string): void {
  const blob = new Blob([buildTradesExcelXml(trades)], { type: EXCEL_XML_TYPE });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
