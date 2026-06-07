import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { RiskLimitsPanel } from "@/components/risk/risk-limits-panel";

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn().mockResolvedValue({
      values: { max_open_trades_stock: 3, max_open_trades_crypto: 3, risk_tolerance: 5 },
      restart_required: false,
    }),
    patch: vi.fn().mockResolvedValue({ values: {}, restart_required: false }),
  },
}));

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("RiskLimitsPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the loaded limit values", async () => {
    wrap(<RiskLimitsPanel isAdmin budgetVol={0.3} />);
    await waitFor(() => expect(screen.getByDisplayValue("5")).toBeInTheDocument());
  });

  it("hides the save button for non-admins", async () => {
    wrap(<RiskLimitsPanel isAdmin={false} budgetVol={0.3} />);
    await waitFor(() => expect(screen.getByText(/solo gli amministratori/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /salva/i })).not.toBeInTheDocument();
  });
});
