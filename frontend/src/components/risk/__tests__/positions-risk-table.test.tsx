import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PositionsRiskTable } from "@/components/risk/positions-risk-table";
import { buildRiskRows } from "@/lib/risk";
import type { LivePosition, Trade } from "@/lib/types";

function trade(p: Partial<Trade>): Trade {
  return { id: 1, symbol: "AAA", category: "STOCK", direction: "BUY", status: "OPEN",
    entry_price: 90, target_entry_price: null, quantity: 10, allocated_capital: 900,
    take_profit: null, trailing_take_profit_distance: null, trailing_take_profit_activation_pct: null,
    stop_loss: null, trailing_stop_distance: null, high_water_mark: null,
    trailing_take_profit_price: null, trailing_stop_price: null, open_timestamp: null,
    close_timestamp: null, close_price: null, current_price: 100, pnl: null, realized_pnl: 0,
    unrealized_pnl: 100, close_reason: null, instrument_id: null, position_id: "p1",
    order_reference_id: null, reasoning: null, confidence: null, account_currency: "USD",
    created_at: "", updated_at: "", trade_score: null, ...p };
}
function live(p: Partial<LivePosition>): LivePosition {
  return { id: 1, symbol: "AAA", category: "STOCK", units: 10, entry_price: 90,
    current_price: 100, unrealized_pnl: 100, unrealized_pnl_pct: 11, take_profit: null,
    stop_loss: null, position_id: "p1", instrument_id: null, is_buy: true, ...p };
}

describe("PositionsRiskTable", () => {
  it("flags an unprotected position", () => {
    const rows = buildRiskRows([live({ id: 1 })], [trade({ id: 1 })]); // no SL/TP
    render(<PositionsRiskTable rows={rows} onEdit={() => {}} />);
    expect(screen.getAllByText(/scoperta/i).length).toBeGreaterThan(0);
  });

  it("shows protection badges and stop distance when protected", () => {
    const rows = buildRiskRows(
      [live({ id: 1, stop_loss: 90 })],
      [trade({ id: 1, stop_loss: 90, take_profit: 120, trailing_stop_distance: 5, trailing_stop_price: 95 })],
    );
    render(<PositionsRiskTable rows={rows} onEdit={() => {}} />);
    expect(screen.getAllByText("SL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TP").length).toBeGreaterThan(0);
    // distanza dal prezzo (100) allo stop effettivo (95) = 5.0%
    expect(screen.getAllByText(/5\.0%/).length).toBeGreaterThan(0);
  });

  it("calls onEdit with the trade", async () => {
    const onEdit = vi.fn();
    const rows = buildRiskRows([live({ id: 1 })], [trade({ id: 1 })]);
    render(<PositionsRiskTable rows={rows} onEdit={onEdit} />);
    await userEvent.click(screen.getAllByRole("button", { name: /modifica/i })[0]);
    expect(onEdit).toHaveBeenCalledWith(rows[0].trade);
  });
});
