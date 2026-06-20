import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  DEFAULT_TRADE_CATEGORY_FILTER,
  DEFAULT_TRADE_STATUS_FILTER,
  TradesFilters,
} from "@/components/trades/trades-filters";

describe("TradesFilters", () => {
  it("starts from active statuses and lets CANCELLED be added from the dropdown", async () => {
    const user = userEvent.setup();
    const onStatusChange = vi.fn();

    render(
      <TradesFilters
        statusFilter={DEFAULT_TRADE_STATUS_FILTER}
        categoryFilter={DEFAULT_TRADE_CATEGORY_FILTER}
        symbolFilter=""
        onStatusChange={onStatusChange}
        onCategoryChange={vi.fn()}
        onSymbolChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Stato: Attivi" }));
    expect(screen.getByRole("button", { name: "CANCELLED" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await user.click(screen.getByRole("button", { name: "CANCELLED" }));

    expect(onStatusChange).toHaveBeenCalledWith(["PENDING", "OPEN", "CLOSED", "CANCELLED"]);
  });

  it("lets categories be selected independently while staying in dropdown form", async () => {
    const user = userEvent.setup();
    const onCategoryChange = vi.fn();

    render(
      <TradesFilters
        statusFilter={DEFAULT_TRADE_STATUS_FILTER}
        categoryFilter={DEFAULT_TRADE_CATEGORY_FILTER}
        symbolFilter=""
        onStatusChange={vi.fn()}
        onCategoryChange={onCategoryChange}
        onSymbolChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Categoria: Tutte" }));
    await user.click(screen.getByRole("button", { name: "CRYPTO" }));

    expect(onCategoryChange).toHaveBeenCalledWith(["STOCK"]);
  });
});
