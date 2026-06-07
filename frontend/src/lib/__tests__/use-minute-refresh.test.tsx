import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMinuteRefresh } from "@/lib/use-minute-refresh";
import type { ReactNode } from "react";

function wrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useMinuteRefresh", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("invalidates the given query keys on the aligned tick", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    renderHook(() => useMinuteRefresh(["risk", "metrics"]), { wrapper: wrapper(qc) });
    vi.advanceTimersByTime(61_000);
    expect(spy).toHaveBeenCalledWith({ queryKey: ["risk"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["metrics"] });
  });
});
