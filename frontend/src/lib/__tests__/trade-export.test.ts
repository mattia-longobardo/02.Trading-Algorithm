import { describe, expect, it } from "vitest";
import { buildTradesExcelFilename, buildTradesExcelXlsx } from "@/lib/trade-export";
import { type Trade } from "@/lib/types";

const BASE_TRADE: Trade = {
  id: 42,
  symbol: "AAA",
  category: "STOCK",
  direction: "LONG",
  status: "CLOSED",
  entry_price: 100,
  target_entry_price: null,
  quantity: 10,
  allocated_capital: 1000,
  take_profit: 120,
  trailing_take_profit_distance: null,
  trailing_take_profit_activation_pct: null,
  stop_loss: 90,
  trailing_stop_distance: null,
  high_water_mark: null,
  trailing_take_profit_price: null,
  trailing_stop_price: null,
  open_timestamp: "2026-06-01T09:00:00Z",
  close_timestamp: "2026-06-10T15:30:00Z",
  close_price: 112,
  current_price: 112,
  pnl: null,
  realized_pnl: 120,
  unrealized_pnl: 3.45,
  close_reason: "target",
  instrument_id: 1001,
  position_id: "pos-1",
  order_reference_id: "ord-1",
  reasoning: "Momentum & breakout <confirmed>",
  confidence: 0.8,
  account_currency: "EUR",
  created_at: "2026-06-01T08:55:00Z",
  updated_at: "2026-06-10T15:30:00Z",
  trade_score: 72,
};

describe("trade export", () => {
  it("builds an Excel-compatible filename from the selected period", () => {
    expect(buildTradesExcelFilename("2026-06-01", "2026-06-21")).toBe(
      "trades_2026-06-01_2026-06-21.xlsx",
    );
  });

  it("serializes trades as a real XLSX zip package with numeric cells", () => {
    const bytes = buildTradesExcelXlsx([BASE_TRADE]);
    const decoded = new TextDecoder().decode(bytes);

    expect(Array.from(bytes.slice(0, 4))).toEqual([0x50, 0x4b, 0x03, 0x04]);
    expect(decoded).toContain("[Content_Types].xml");
    expect(decoded).toContain("xl/worksheets/sheet1.xml");
    expect(decoded).toContain('<sheet name="Trade" sheetId="1" r:id="rId1"/>');
    expect(decoded).toContain('<c r="B1" t="inlineStr"><is><t>Simbolo</t></is></c>');
    expect(decoded).toContain('<c r="A2"><v>42</v></c>');
    expect(decoded).toContain('<c r="O2"><v>123.45</v></c>');
  });

  it("escapes text values before writing XML cells", () => {
    const decoded = new TextDecoder().decode(buildTradesExcelXlsx([BASE_TRADE]));

    expect(decoded).toContain("Momentum &amp; breakout &lt;confirmed&gt;");
    expect(decoded).not.toContain("Momentum & breakout <confirmed>");
  });
});
