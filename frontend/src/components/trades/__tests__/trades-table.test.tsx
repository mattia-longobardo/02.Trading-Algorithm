import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TradesTable } from "@/components/trades/trades-table";
import type { Trade } from "@/lib/types";

const BASE: Trade = {
  id: 0,
  symbol: "AAA",
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
  pnl: null,
  realized_pnl: 0,
  unrealized_pnl: 0,
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

function makeTrade(over: Partial<Trade>): Trade {
  return { ...BASE, ...over };
}

/** Symbols of the desktop table body rows, in DOM order. */
function tableSymbolOrder(container: HTMLElement): string[] {
  const table = container.querySelector("table");
  const rows = table?.querySelectorAll("tbody tr") ?? [];
  return Array.from(rows).map((r) => r.querySelector("td a")?.textContent ?? "");
}

describe("TradesTable", () => {
  it("puts sticky close, edit and symbol columns first", () => {
    const { container } = render(
      <TradesTable items={[makeTrade({ id: 1 })]} loading={false} onEdit={vi.fn()} onClose={vi.fn()} />
    );
    const headers = Array.from(container.querySelectorAll("thead th")).map((th) =>
      th.textContent?.trim()
    );
    expect(headers.slice(0, 3)).toEqual(["Chiudi", "Mod.", "Simbolo"]);
    const firstRowCells = Array.from(container.querySelectorAll("tbody tr:first-child td"));
    expect(firstRowCells[0]).toHaveClass("sticky");
    expect(firstRowCells[1]).toHaveClass("sticky");
    expect(firstRowCells[2]).toHaveClass("sticky");
  });

  it("renders the PnL % column header", () => {
    render(<TradesTable items={[makeTrade({ id: 1 })]} loading={false} onEdit={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: /PnL %/i })).toBeInTheDocument();
  });

  it("shows gain/loss percentage relative to allocated capital", () => {
    // pnl = 145 on 1805 capital → +8.03%
    render(
      <TradesTable
        items={[makeTrade({ id: 1, allocated_capital: 1805, unrealized_pnl: 145 })]}
        loading={false}
        onEdit={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(screen.getAllByText("+8.03%").length).toBeGreaterThan(0);
  });

  it("sorts rows ascending then descending when a header is clicked", async () => {
    const user = userEvent.setup();
    const items = [makeTrade({ id: 1, symbol: "ZZZ" }), makeTrade({ id: 2, symbol: "AAA" })];
    const { container } = render(
      <TradesTable items={items} loading={false} onEdit={vi.fn()} onClose={vi.fn()} />
    );

    // Initial order is preserved (no sort applied).
    expect(tableSymbolOrder(container)).toEqual(["ZZZ", "AAA"]);

    const symbolHeader = screen.getByRole("button", { name: /Simbolo/i });
    await user.click(symbolHeader); // asc
    expect(tableSymbolOrder(container)).toEqual(["AAA", "ZZZ"]);

    await user.click(symbolHeader); // desc
    expect(tableSymbolOrder(container)).toEqual(["ZZZ", "AAA"]);
  });

  it("sorts numeric columns by value, not lexicographically", async () => {
    const user = userEvent.setup();
    const items = [
      makeTrade({ id: 1, symbol: "BIG", allocated_capital: 9 }),
      makeTrade({ id: 2, symbol: "SMALL", allocated_capital: 1000 }),
    ];
    const { container } = render(
      <TradesTable items={items} loading={false} onEdit={vi.fn()} onClose={vi.fn()} />
    );

    await user.click(screen.getByRole("button", { name: /Capitale/i })); // asc by capital
    expect(tableSymbolOrder(container)).toEqual(["BIG", "SMALL"]);
  });
});
