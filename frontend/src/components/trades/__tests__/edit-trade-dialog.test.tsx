import { render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { EditTradeDialog } from "@/components/trades/edit-trade-dialog";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { AppToastProvider } from "@/lib/toast";
import type { Trade } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    patch: vi.fn(),
  },
}));

const TRADE: Trade = {
  id: 42,
  symbol: "AAPL",
  category: "STOCK",
  direction: "LONG",
  status: "OPEN",
  entry_price: 180.5,
  target_entry_price: 179,
  quantity: 10,
  allocated_capital: 1805,
  take_profit: 200,
  trailing_take_profit_distance: null,
  trailing_take_profit_activation_pct: null,
  stop_loss: 165,
  trailing_stop_distance: null,
  high_water_mark: 195,
  trailing_take_profit_price: null,
  trailing_stop_price: null,
  open_timestamp: "2024-01-15T10:30:00Z",
  close_timestamp: null,
  close_price: null,
  current_price: 195,
  pnl: null,
  realized_pnl: 0,
  unrealized_pnl: 145,
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

function renderDialog() {
  function Harness() {
    const [open, setOpen] = useState(true);
    return (
      <AppToastProvider>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent>
            <EditTradeDialog trade={TRADE} onClose={() => setOpen(false)} onSaved={vi.fn()} />
          </DialogContent>
        </Dialog>
      </AppToastProvider>
    );
  }

  render(<Harness />);
}

describe("EditTradeDialog", () => {
  it("only exposes future exit/protection parameters", () => {
    renderDialog();

    expect(screen.getByText("Take profit")).toBeInTheDocument();
    expect(screen.getByText("Stop loss")).toBeInTheDocument();
    expect(screen.getByText("Trailing TP activation %")).toBeInTheDocument();
    expect(screen.getByText("Trailing TP distance")).toBeInTheDocument();
    expect(screen.getByText("Trailing stop distance")).toBeInTheDocument();

    expect(screen.queryByText("Target entry")).not.toBeInTheDocument();
    expect(screen.queryByText("Quantity")).not.toBeInTheDocument();
    expect(screen.queryByText("High-water mark")).not.toBeInTheDocument();
  });
});
