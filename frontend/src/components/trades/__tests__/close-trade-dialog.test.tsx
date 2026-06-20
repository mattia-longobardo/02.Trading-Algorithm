import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { CloseTradeDialog } from "@/components/trades/close-trade-dialog";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { AppToastProvider } from "@/lib/toast";
import type { Trade } from "@/lib/types";

const apiPost = vi.fn();

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status = 500;
    code = null;
    payload = null;
  },
  api: {
    post: (...args: unknown[]) => apiPost(...args),
  },
}));

const OPEN_TRADE: Trade = {
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
  high_water_mark: null,
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderDialog(promise: Promise<{ trade: Trade }>) {
  const onClose = vi.fn();
  const onDone = vi.fn();
  apiPost.mockReturnValueOnce(promise);

  function Harness() {
    const [open, setOpen] = useState(true);
    return (
      <AppToastProvider>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent>
            <CloseTradeDialog
              trade={OPEN_TRADE}
              onClose={() => {
                onClose();
                setOpen(false);
              }}
              onDone={onDone}
            />
          </DialogContent>
        </Dialog>
      </AppToastProvider>
    );
  }

  render(
    <Harness />,
  );
  return { onClose, onDone };
}

describe("CloseTradeDialog", () => {
  it("closes immediately and promotes the running close to a success toast", async () => {
    const user = userEvent.setup();
    const request = deferred<{ trade: Trade }>();
    const { onClose, onDone } = renderDialog(request.promise);

    await user.click(screen.getByRole("button", { name: /conferma chiusura/i }));

    expect(apiPost).toHaveBeenCalledWith("/api/trades/42/close");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/chiudi trade a mercato/i)).not.toBeInTheDocument();
    expect(screen.getByText("Chiusura trade #42 in corso")).toBeInTheDocument();

    await act(async () => {
      request.resolve({ trade: { ...OPEN_TRADE, status: "CLOSED" } });
      await request.promise;
    });

    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(screen.getByText("Chiusura trade #42 inviata")).toBeInTheDocument();
  });

  it("turns the toast red on failure and lets the operator close it", async () => {
    const user = userEvent.setup();
    const request = deferred<{ trade: Trade }>();
    renderDialog(request.promise);

    await user.click(screen.getByRole("button", { name: /conferma chiusura/i }));

    await act(async () => {
      request.reject(new Error("Broker non raggiungibile"));
      try {
        await request.promise;
      } catch {
        // Expected rejection is handled by the toast tracker.
      }
    });

    expect(screen.getByText("Chiusura trade #42 fallita")).toBeInTheDocument();
    expect(screen.getByText("Broker non raggiungibile")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /chiudi notifica/i }));

    await waitFor(() =>
      expect(screen.queryByText("Chiusura trade #42 fallita")).not.toBeInTheDocument(),
    );
  });
});
