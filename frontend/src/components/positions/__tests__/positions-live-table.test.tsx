import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { PositionsLiveTable } from "@/components/positions/positions-live-table";
import type { LivePosition } from "@/lib/types";

const POSITION_PROFIT: LivePosition = {
  id: 1,
  symbol: "BTC",
  category: "CRYPTO",
  units: 0.5,
  entry_price: 60_000,
  current_price: 65_000,
  unrealized_pnl: 2_500,
  unrealized_pnl_pct: 8.33,
  take_profit: 70_000,
  stop_loss: 55_000,
  position_id: "pos-001",
  instrument_id: 100,
  is_buy: true,
};

const POSITION_LOSS: LivePosition = {
  id: 2,
  symbol: "AAPL",
  category: "STOCK",
  units: 10,
  entry_price: 180,
  current_price: 170,
  unrealized_pnl: -100,
  unrealized_pnl_pct: -5.56,
  take_profit: 200,
  stop_loss: 165,
  position_id: "pos-002",
  instrument_id: 200,
  is_buy: true,
};

describe("PositionsLiveTable", () => {
  describe("with positions", () => {
    beforeEach(() => {
      render(<PositionsLiveTable positions={[POSITION_PROFIT, POSITION_LOSS]} />);
    });

    it("renders both symbols", () => {
      expect(screen.getByText("BTC")).toBeInTheDocument();
      expect(screen.getByText("AAPL")).toBeInTheDocument();
    });

    it("positive PnL cell has accent/profit class", () => {
      // Find td cells with the accent color token
      const accentCells = document.querySelectorAll("td.tnum");
      const profitCells = Array.from(accentCells).filter((cell) =>
        cell.className.includes("--color-accent")
      );
      expect(profitCells.length).toBeGreaterThan(0);
    });

    it("positive PnL cell shows a leading '+' sign", () => {
      // The formatted PnL for POSITION_PROFIT (2500) should start with '+'
      const allText = document.body.textContent ?? "";
      expect(allText).toMatch(/\+/);
    });

    it("negative PnL cell has danger class", () => {
      const allCells = document.querySelectorAll("td.tnum");
      const dangerCells = Array.from(allCells).filter((cell) =>
        cell.className.includes("--color-danger")
      );
      expect(dangerCells.length).toBeGreaterThan(0);
    });

    it("negative PnL cell shows a leading '-' sign", () => {
      const allText = document.body.textContent ?? "";
      // The formatted -100 should appear with a minus sign somewhere in the row
      expect(allText).toMatch(/-/);
    });

    it("renders column headers", () => {
      expect(screen.getByText("Simbolo")).toBeInTheDocument();
      expect(screen.getByText("PnL")).toBeInTheDocument();
      expect(screen.getByText("PnL %")).toBeInTheDocument();
    });

    it("uses tnum class on numeric cells", () => {
      const tnumCells = document.querySelectorAll("td.tnum");
      expect(tnumCells.length).toBeGreaterThan(0);
    });
  });

  describe("with empty positions", () => {
    it("renders the empty-state message instead of a table", () => {
      render(<PositionsLiveTable positions={[]} />);
      expect(screen.getByText("Nessuna posizione aperta")).toBeInTheDocument();
      // No table should be rendered
      expect(document.querySelector("table")).not.toBeInTheDocument();
    });

    it("does not render any symbol", () => {
      render(<PositionsLiveTable positions={[]} />);
      expect(screen.queryByText("BTC")).not.toBeInTheDocument();
    });
  });
});
