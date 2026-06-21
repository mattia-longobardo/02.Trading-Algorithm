import { describe, expect, it } from "vitest";
import { buildTradesExcelFilename, buildTradesExcelXml } from "@/lib/trade-export";
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
      "trades_2026-06-01_2026-06-21.xls",
    );
  });

  it("serializes trades as SpreadsheetML with numeric cells", () => {
    const xml = buildTradesExcelXml([BASE_TRADE]);

    expect(xml).toContain('<?mso-application progid="Excel.Sheet"?>');
    expect(xml).toContain('<Worksheet ss:Name="Trade">');
    expect(xml).toContain('<Data ss:Type="String">Simbolo</Data>');
    expect(xml).toContain('<Data ss:Type="Number">42</Data>');
    expect(xml).toContain('<Data ss:Type="Number">123.45</Data>');
  });

  it("escapes text values before writing XML cells", () => {
    const xml = buildTradesExcelXml([BASE_TRADE]);

    expect(xml).toContain("Momentum &amp; breakout &lt;confirmed&gt;");
    expect(xml).not.toContain("Momentum & breakout <confirmed>");
  });
});
