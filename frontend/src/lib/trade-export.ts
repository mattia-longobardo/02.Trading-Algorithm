import { type Trade } from "@/lib/types";

type CellValue = string | number | null | undefined;

interface ExportColumn {
  header: string;
  value: (trade: Trade) => CellValue;
}

const XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const ZIP_UTF8_FLAG = 0x0800;
const encoder = new TextEncoder();

interface ZipFile {
  name: string;
  data: Uint8Array;
}

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

function columnName(index: number): string {
  let n = index + 1;
  let name = "";
  while (n > 0) {
    const remainder = (n - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    n = Math.floor((n - 1) / 26);
  }
  return name;
}

function cell(value: CellValue, rowIndex: number, columnIndex: number): string {
  const ref = `${columnName(columnIndex)}${rowIndex}`;
  if (value === null || value === undefined) {
    return `<c r="${ref}" t="inlineStr"><is><t></t></is></c>`;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return `<c r="${ref}"><v>${value}</v></c>`;
  }
  return `<c r="${ref}" t="inlineStr"><is><t>${escapeXml(String(value))}</t></is></c>`;
}

function row(values: CellValue[], rowIndex: number): string {
  return `<row r="${rowIndex}">${values.map((value, index) => cell(value, rowIndex, index)).join("")}</row>`;
}

function worksheetXml(trades: Trade[]): string {
  const header = row(TRADE_EXPORT_COLUMNS.map((column) => column.header), 1);
  const body = trades
    .map((trade, index) =>
      row(TRADE_EXPORT_COLUMNS.map((column) => column.value(trade)), index + 2),
    )
    .join("");
  const lastColumn = columnName(TRADE_EXPORT_COLUMNS.length - 1);
  const lastRow = Math.max(trades.length + 1, 1);
  const range = `A1:${lastColumn}${lastRow}`;

  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"',
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
    `<dimension ref="${range}"/>`,
    '<sheetViews><sheetView workbookViewId="0"/></sheetViews>',
    '<sheetFormatPr defaultRowHeight="15"/>',
    '<sheetData>',
    header,
    body,
    '</sheetData>',
    `<autoFilter ref="${range}"/>`,
    '</worksheet>',
  ].join("");
}

function workbookXml(): string {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"',
    ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
    '<sheets><sheet name="Trade" sheetId="1" r:id="rId1"/></sheets>',
    '</workbook>',
  ].join("");
}

function workbookRelsXml(): string {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    '<Relationship Id="rId1"',
    ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"',
    ' Target="worksheets/sheet1.xml"/>',
    '</Relationships>',
  ].join("");
}

function rootRelsXml(): string {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    '<Relationship Id="rId1"',
    ' Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"',
    ' Target="xl/workbook.xml"/>',
    '</Relationships>',
  ].join("");
}

function contentTypesXml(): string {
  return [
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
    '<Default Extension="xml" ContentType="application/xml"/>',
    '<Override PartName="/xl/workbook.xml"',
    ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
    '<Override PartName="/xl/worksheets/sheet1.xml"',
    ' ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    '</Types>',
  ].join("");
}

function encode(text: string): Uint8Array {
  return encoder.encode(text);
}

const CRC32_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let i = 0; i < table.length; i += 1) {
    let c = i;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[i] = c >>> 0;
  }
  return table;
})();

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc = CRC32_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function writeUint16(view: DataView, offset: number, value: number): void {
  view.setUint16(offset, value, true);
}

function writeUint32(view: DataView, offset: number, value: number): void {
  view.setUint32(offset, value >>> 0, true);
}

function concat(parts: Uint8Array[], totalLength: number): Uint8Array {
  const out = new Uint8Array(totalLength);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function createZip(files: ZipFile[]): Uint8Array {
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let localSize = 0;
  let centralSize = 0;

  for (const file of files) {
    const name = encode(file.name);
    const checksum = crc32(file.data);
    const localHeader = new Uint8Array(30 + name.length);
    const localView = new DataView(localHeader.buffer);

    writeUint32(localView, 0, 0x04034b50);
    writeUint16(localView, 4, 20);
    writeUint16(localView, 6, ZIP_UTF8_FLAG);
    writeUint16(localView, 8, 0);
    writeUint16(localView, 10, 0);
    writeUint16(localView, 12, 0);
    writeUint32(localView, 14, checksum);
    writeUint32(localView, 18, file.data.length);
    writeUint32(localView, 22, file.data.length);
    writeUint16(localView, 26, name.length);
    writeUint16(localView, 28, 0);
    localHeader.set(name, 30);

    const centralHeader = new Uint8Array(46 + name.length);
    const centralView = new DataView(centralHeader.buffer);
    writeUint32(centralView, 0, 0x02014b50);
    writeUint16(centralView, 4, 20);
    writeUint16(centralView, 6, 20);
    writeUint16(centralView, 8, ZIP_UTF8_FLAG);
    writeUint16(centralView, 10, 0);
    writeUint16(centralView, 12, 0);
    writeUint16(centralView, 14, 0);
    writeUint32(centralView, 16, checksum);
    writeUint32(centralView, 20, file.data.length);
    writeUint32(centralView, 24, file.data.length);
    writeUint16(centralView, 28, name.length);
    writeUint16(centralView, 30, 0);
    writeUint16(centralView, 32, 0);
    writeUint16(centralView, 34, 0);
    writeUint16(centralView, 36, 0);
    writeUint32(centralView, 38, 0);
    writeUint32(centralView, 42, localSize);
    centralHeader.set(name, 46);

    localParts.push(localHeader, file.data);
    centralParts.push(centralHeader);
    localSize += localHeader.length + file.data.length;
    centralSize += centralHeader.length;
  }

  const endOfCentralDirectory = new Uint8Array(22);
  const endView = new DataView(endOfCentralDirectory.buffer);
  writeUint32(endView, 0, 0x06054b50);
  writeUint16(endView, 4, 0);
  writeUint16(endView, 6, 0);
  writeUint16(endView, 8, files.length);
  writeUint16(endView, 10, files.length);
  writeUint32(endView, 12, centralSize);
  writeUint32(endView, 16, localSize);
  writeUint16(endView, 20, 0);

  return concat(
    [...localParts, ...centralParts, endOfCentralDirectory],
    localSize + centralSize + endOfCentralDirectory.length,
  );
}

export function buildTradesExcelXlsx(trades: Trade[]): Uint8Array {
  return createZip([
    { name: "[Content_Types].xml", data: encode(contentTypesXml()) },
    { name: "_rels/.rels", data: encode(rootRelsXml()) },
    { name: "xl/workbook.xml", data: encode(workbookXml()) },
    { name: "xl/_rels/workbook.xml.rels", data: encode(workbookRelsXml()) },
    { name: "xl/worksheets/sheet1.xml", data: encode(worksheetXml(trades)) },
  ]);
}

export function buildTradesExcelFilename(fromDate: string, toDate: string): string {
  const from = fromDate || "inizio";
  const to = toDate || "fine";
  return `trades_${from}_${to}.xlsx`;
}

export function downloadTradesExcel(trades: Trade[], filename: string): void {
  const bytes = buildTradesExcelXlsx(trades);
  const buffer = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(buffer).set(bytes);
  const blob = new Blob([buffer], { type: XLSX_MIME_TYPE });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
