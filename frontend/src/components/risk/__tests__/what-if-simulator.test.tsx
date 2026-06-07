import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { WhatIfSimulator } from "@/components/risk/what-if-simulator";
import type { RiskProjection } from "@/lib/types";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: { post: vi.fn() },
}));

const PROJ: RiskProjection = {
  current: { score: 40 } as RiskProjection["current"],
  projected: { score: 52 } as RiskProjection["projected"],
  suggested_size: 480,
  delta: { score: 12, exposure: 0.05, portfolio_vol: 0.01, n_eff: -0.3 },
};

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("WhatIfSimulator", () => {
  beforeEach(() => vi.clearAllMocks());

  it("submits an open scenario and renders the delta", async () => {
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(PROJ);
    wrap(<WhatIfSimulator openSymbols={["AAA"]} />);
    fireEvent.change(screen.getByLabelText(/simbolo/i), { target: { value: "BBB" } });
    fireEvent.change(screen.getByLabelText(/valore/i), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: /simula/i }));
    await waitFor(() => expect(screen.getByText(/\+12\.0/)).toBeInTheDocument());
    expect(api.post).toHaveBeenCalledWith("/api/risk/project", expect.objectContaining({ symbol: "BBB", value: 1000 }));
  });
});
