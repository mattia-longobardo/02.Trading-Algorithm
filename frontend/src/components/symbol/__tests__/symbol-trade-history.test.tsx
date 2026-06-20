import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { SymbolTradeHistory } from "@/components/symbol/symbol-trade-history";
import type { Trade } from "@/lib/types";

const BASE_TRADE: Trade = {
  id: 1,
  symbol: "BTC",
  category: "CRYPTO",
  direction: "LONG",
  status: "CLOSED",
  entry_price: 60_000,
  target_entry_price: null,
  quantity: 0.5,
  allocated_capital: 30_000,
  take_profit: 70_000,
  trailing_take_profit_distance: null,
  trailing_take_profit_activation_pct: null,
  stop_loss: 55_000,
  trailing_stop_distance: null,
  high_water_mark: null,
  trailing_take_profit_price: null,
  trailing_stop_price: null,
  open_timestamp: "2024-01-01T10:00:00Z",
  close_timestamp: "2024-01-10T14:00:00Z",
  close_price: 70_000,
  current_price: 70_000,
  pnl: 5_000,
  realized_pnl: 5_000,
  unrealized_pnl: 0,
  close_reason: "TP",
  instrument_id: 100,
  position_id: "pos-001",
  order_reference_id: "ord-001",
  reasoning: null,
  confidence: null,
  account_currency: "EUR",
  created_at: "2024-01-01T09:00:00Z",
  updated_at: "2024-01-10T14:00:00Z",
  trade_score: null,
};

const WIN_TRADE: Trade = {
  ...BASE_TRADE,
  id: 1,
  realized_pnl: 5_000,
  unrealized_pnl: 0,
};

const LOSS_TRADE: Trade = {
  ...BASE_TRADE,
  id: 2,
  realized_pnl: -1_500,
  unrealized_pnl: 0,
  close_price: 55_000,
  current_price: 55_000,
  close_reason: "SL",
};

describe("SymbolTradeHistory", () => {
  describe("with trades", () => {
    it("renders a row for each trade", () => {
      render(<SymbolTradeHistory trades={[WIN_TRADE, LOSS_TRADE]} />);
      // Two tbody rows — query by role
      const rows = document.querySelectorAll("tbody tr");
      expect(rows).toHaveLength(2);
    });

    it("renders status badges", () => {
      render(<SymbolTradeHistory trades={[WIN_TRADE, LOSS_TRADE]} />);
      // Both trades are CLOSED
      const badges = screen.getAllByText("CLOSED");
      expect(badges.length).toBeGreaterThanOrEqual(2);
    });

    it("profit-colored cell is present for the winning trade", () => {
      render(<SymbolTradeHistory trades={[WIN_TRADE, LOSS_TRADE]} />);
      const cells = document.querySelectorAll("td.tnum");
      const profitCells = Array.from(cells).filter((cell) =>
        cell.className.includes("--color-accent"),
      );
      expect(profitCells.length).toBeGreaterThan(0);
    });

    it("loss-colored cell is present for the losing trade", () => {
      render(<SymbolTradeHistory trades={[WIN_TRADE, LOSS_TRADE]} />);
      const cells = document.querySelectorAll("td.tnum");
      const dangerCells = Array.from(cells).filter((cell) =>
        cell.className.includes("--color-danger"),
      );
      expect(dangerCells.length).toBeGreaterThan(0);
    });

    it("renders column headers", () => {
      render(<SymbolTradeHistory trades={[WIN_TRADE]} />);
      const headers = Array.from(document.querySelectorAll("th")).map(
        (header) => header.textContent,
      );
      expect(headers).toContain("Stato");
      expect(headers).toContain("Entry");
      expect(headers).toContain("PnL");
    });

    it("uses tnum class on numeric cells", () => {
      render(<SymbolTradeHistory trades={[WIN_TRADE]} />);
      const tnumCells = document.querySelectorAll("td.tnum");
      expect(tnumCells.length).toBeGreaterThan(0);
    });
  });

  describe("with empty trades", () => {
    it("renders the empty state message", () => {
      render(<SymbolTradeHistory trades={[]} />);
      expect(
        screen.getByText("Nessun trade per questo simbolo"),
      ).toBeInTheDocument();
    });

    it("does not render a table", () => {
      render(<SymbolTradeHistory trades={[]} />);
      expect(document.querySelector("table")).not.toBeInTheDocument();
    });
  });
});
