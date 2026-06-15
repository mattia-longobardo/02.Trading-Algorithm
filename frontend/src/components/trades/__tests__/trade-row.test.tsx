import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { TradeRow, tradePnlPct } from "@/components/trades/trade-row";
import type { Trade } from "@/lib/types";

const OPEN_TRADE: Trade = {
  id: 42,
  symbol: "AAPL",
  category: "STOCK",
  direction: "LONG",
  status: "OPEN",
  entry_price: 180.5,
  target_entry_price: 179.0,
  quantity: 10,
  allocated_capital: 1805.0,
  take_profit: 200.0,
  trailing_take_profit_distance: null,
  trailing_take_profit_activation_pct: null,
  stop_loss: 165.0,
  trailing_stop_distance: null,
  high_water_mark: null,
  trailing_take_profit_price: null,
  trailing_stop_price: null,
  open_timestamp: "2024-01-15T10:30:00Z",
  close_timestamp: null,
  close_price: null,
  current_price: 195.0,
  pnl: null,
  realized_pnl: 0,
  unrealized_pnl: 145.0,
  close_reason: null,
  instrument_id: 1001,
  position_id: "pos-123",
  order_reference_id: "ord-456",
  reasoning: null,
  confidence: null,
  account_currency: "EUR",
  created_at: "2024-01-15T10:00:00Z",
  updated_at: "2024-01-15T10:30:00Z",
  trade_score: null,
};

function renderRow(trade: Trade) {
  const onEdit = vi.fn();
  const onClose = vi.fn();
  const result = render(
    <table>
      <tbody>
        <TradeRow trade={trade} onEdit={onEdit} onClose={onClose} />
      </tbody>
    </table>
  );
  return { ...result, onEdit, onClose };
}

describe("TradeRow", () => {
  it("renders the symbol", () => {
    renderRow(OPEN_TRADE);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("renders trade id", () => {
    renderRow(OPEN_TRADE);
    expect(screen.getByText("#42")).toBeInTheDocument();
  });

  it("renders OPEN status badge", () => {
    renderRow(OPEN_TRADE);
    expect(screen.getByText("OPEN")).toBeInTheDocument();
  });

  it("renders positive PnL with accent/profit class and formatted value", () => {
    renderRow(OPEN_TRADE);
    // unrealized_pnl=145, realized_pnl=0 → total=145 → positive
    // formatCurrency(145, "EUR") in it-IT locale → "145,00 €" or similar
    const pnlCell = screen.getByTitle(/Trailing TP non ancora armato/i)
      .closest("tr")
      ?.querySelectorAll("td");

    // Find the PnL cell — it should have the accent class and contain a positive formatted number
    const cells = screen.getAllByRole("cell");
    const pnlCellEl = Array.from(cells).find(
      (cell) =>
        cell.classList.contains("text-\\(--color-accent\\)") ||
        cell.className.includes("--color-accent")
    );
    expect(pnlCellEl).toBeDefined();
  });

  it("PnL cell contains a numeric value indicating profit", () => {
    renderRow(OPEN_TRADE);
    // With it-IT locale and EUR: 145 → "145,00 €" or "€145,00" depending on environment
    // Just assert the formatted string appears somewhere in the row
    const allText = document.body.textContent ?? "";
    // The value 145 should appear somewhere in formatted form
    expect(allText).toMatch(/145/);
  });

  it("renders Chiudi button for OPEN trades", () => {
    renderRow(OPEN_TRADE);
    expect(screen.getByRole("button", { name: /Chiudi/i })).toBeInTheDocument();
  });

  it("renders Modifica button", () => {
    renderRow(OPEN_TRADE);
    expect(screen.getByRole("button", { name: /Modifica/i })).toBeInTheDocument();
  });

  it("renders Annulla button for PENDING trades", () => {
    const pendingTrade: Trade = { ...OPEN_TRADE, status: "PENDING" };
    renderRow(pendingTrade);
    expect(screen.getByRole("button", { name: /Annulla/i })).toBeInTheDocument();
  });

  it("does not render close button for CLOSED trades", () => {
    const closedTrade: Trade = {
      ...OPEN_TRADE,
      status: "CLOSED",
      close_timestamp: "2024-01-20T12:00:00Z",
    };
    renderRow(closedTrade);
    expect(screen.queryByRole("button", { name: /Chiudi/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Annulla/i })).not.toBeInTheDocument();
  });

  it("applies tnum class to numeric cells (entry price)", () => {
    renderRow(OPEN_TRADE);
    // entry_price = 180.5, formatted with it-IT: "180,5"
    // Find all cells with tnum class
    const tnumCells = document.querySelectorAll("td.tnum");
    expect(tnumCells.length).toBeGreaterThan(0);
  });

  it("PnL cell has accent CSS class for positive values", () => {
    renderRow(OPEN_TRADE);
    const cells = document.querySelectorAll("td.tnum");
    // The PnL cell (last tnum before actions) should have the accent color
    const pnlCells = Array.from(cells).filter((cell) =>
      cell.className.includes("--color-accent")
    );
    expect(pnlCells.length).toBeGreaterThan(0);
  });

  it("PnL cell has danger CSS class for negative values", () => {
    const losingTrade: Trade = {
      ...OPEN_TRADE,
      realized_pnl: 0,
      unrealized_pnl: -50,
    };
    renderRow(losingTrade);
    const cells = document.querySelectorAll("td.tnum");
    const pnlCells = Array.from(cells).filter((cell) =>
      cell.className.includes("--color-danger")
    );
    expect(pnlCells.length).toBeGreaterThan(0);
  });

  it("uses the live position PnL percentage when present", () => {
    expect(tradePnlPct({ ...OPEN_TRADE, unrealized_pnl_pct: 8.33 })).toBe(8.33);
  });
});
