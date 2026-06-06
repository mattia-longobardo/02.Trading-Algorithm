import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TradeCard } from "@/components/trades/trade-card";
import type { Trade } from "@/lib/types";

const trade: Trade = {
  id: 1,
  symbol: "AAPL",
  category: "STOCK",
  direction: "LONG",
  status: "OPEN",
  entry_price: 100,
  target_entry_price: null,
  quantity: 10,
  allocated_capital: 1000,
  take_profit: null,
  trailing_take_profit_distance: null,
  trailing_take_profit_activation_pct: null,
  stop_loss: null,
  trailing_stop_distance: null,
  high_water_mark: null,
  trailing_take_profit_price: null,
  trailing_stop_price: null,
  open_timestamp: "2024-01-15T10:30:00Z",
  close_timestamp: null,
  close_price: null,
  current_price: 110,
  pnl: 42,
  realized_pnl: 0,
  unrealized_pnl: 42,
  close_reason: null,
  instrument_id: null,
  position_id: null,
  order_reference_id: null,
  reasoning: null,
  confidence: null,
  account_currency: "EUR",
  created_at: "2024-01-15T10:00:00Z",
  updated_at: "2024-01-15T10:30:00Z",
  trade_score: null,
};

describe("TradeCard", () => {
  it("shows symbol, status and PnL collapsed", () => {
    render(<TradeCard trade={trade} onEdit={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText(/OPEN/i)).toBeInTheDocument();
    expect(screen.getByText(/42/)).toBeInTheDocument();
  });

  it("expands to reveal detail fields", async () => {
    const user = userEvent.setup();
    render(<TradeCard trade={trade} onEdit={vi.fn()} onClose={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /dettagli/i }));
    // "Entry" and "Target Entry" both match /Entry/i — use getAllByText
    const entryLabels = screen.getAllByText(/Entry/i);
    expect(entryLabels.length).toBeGreaterThan(0);
  });

  it("invokes onEdit from the actions (for an editable trade)", async () => {
    const onEdit = vi.fn();
    const user = userEvent.setup();
    // OPEN trades always show Modifica button (per trade-row: Modifica is always rendered)
    render(<TradeCard trade={trade} onEdit={onEdit} onClose={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /modifica/i }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });
});
