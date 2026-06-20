import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { JobsPanel } from "@/components/ops/jobs-panel";
import { AppToastProvider } from "@/lib/toast";

const apiGet = vi.fn();

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
    code = null;
    payload = null;
  },
  api: {
    get: (...args: unknown[]) => apiGet(...args),
  },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { id: 1, username: "admin", display_name: "Admin", role: "admin" },
    loading: false,
    refresh: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  }),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AppToastProvider>{node}</AppToastProvider>
    </QueryClientProvider>,
  );
}

describe("JobsPanel", () => {
  it("closes the confirmation dialog and tracks a manual job in a toast", async () => {
    const user = userEvent.setup();
    const request = deferred<{ status: string; message: string }>();
    apiGet.mockReturnValueOnce(request.promise);
    wrap(<JobsPanel />);

    await user.click(screen.getAllByRole("button", { name: "Esegui" })[0]);
    expect(screen.getByText(/confermi l'esecuzione manuale/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Conferma" }));

    expect(apiGet).toHaveBeenCalledWith("/api/universe/generate");
    expect(screen.queryByText(/confermi l'esecuzione manuale/i)).not.toBeInTheDocument();
    expect(screen.getByText("Rigenera universo in corso")).toBeInTheDocument();

    await act(async () => {
      request.resolve({ status: "ok", message: "universe job avviato in background" });
      await request.promise;
    });

    await waitFor(() =>
      expect(screen.getByText("universe job avviato in background")).toBeInTheDocument(),
    );
  });
});
