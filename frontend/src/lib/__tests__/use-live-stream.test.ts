import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { LiveSnapshot } from "@/lib/types";

// ---------------------------------------------------------------------------
// Controllable EventSource mock
// jsdom does not ship EventSource, so we define one here.
// ---------------------------------------------------------------------------

type Listener = (event: Event) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];

  url: string;
  onopen: ((e: Event) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readyState = 0; // CONNECTING

  private listeners: Map<string, Listener[]> = new Map();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: Listener) {
    const arr = this.listeners.get(type) ?? [];
    arr.push(listener);
    this.listeners.set(type, arr);
  }

  removeEventListener(type: string, listener: Listener) {
    const arr = this.listeners.get(type) ?? [];
    this.listeners.set(
      type,
      arr.filter((l) => l !== listener),
    );
  }

  close() {
    this.readyState = 2; // CLOSED
  }

  /** Helpers the tests use to drive the mock */
  simulateOpen() {
    this.readyState = 1; // OPEN
    this.onopen?.(new Event("open"));
  }

  simulateMessage(eventType: string, data: string) {
    // MessageEvent(type, init) — the first argument IS the type; no need to
    // reassign it (type is a read-only getter on Event).
    const event = new MessageEvent(eventType, { data });
    const listeners = this.listeners.get(eventType) ?? [];
    listeners.forEach((l) => l(event));
  }

  simulateError() {
    this.onerror?.(new Event("error"));
  }
}

// ---------------------------------------------------------------------------
// Install mock before each test; restore after
// ---------------------------------------------------------------------------

beforeEach(() => {
  MockEventSource.instances = [];
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (globalThis as any).EventSource = MockEventSource;
});

afterEach(() => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  delete (globalThis as any).EventSource;
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useLiveStream", () => {
  it("starts with status=connecting and no snapshot", async () => {
    const { useLiveStream } = await import("@/lib/use-live-stream");
    const { result } = renderHook(() => useLiveStream());
    expect(result.current.status).toBe("connecting");
    expect(result.current.snapshot).toBeNull();
  });

  it("transitions to live after open event", async () => {
    const { useLiveStream } = await import("@/lib/use-live-stream");
    const { result } = renderHook(() => useLiveStream());

    await act(async () => {
      const src = MockEventSource.instances[0];
      src.simulateOpen();
    });

    expect(result.current.status).toBe("live");
  });

  it("parses snapshot payload and stays live", async () => {
    const { useLiveStream } = await import("@/lib/use-live-stream");
    const { result } = renderHook(() => useLiveStream());

    const payload: LiveSnapshot = {
      ts: "2026-06-05T10:00:00Z",
      currency: "USD",
      equity: 10500.5,
      cash: 2000,
      positions: [
        {
          id: 1,
          symbol: "BTC",
          category: "CRYPTO",
          units: 0.1,
          entry_price: 60000,
          current_price: 62000,
          unrealized_pnl: 200,
          unrealized_pnl_pct: 3.33,
          take_profit: 70000,
          stop_loss: 55000,
          position_id: "pos-abc",
          instrument_id: 42,
          is_buy: true,
        },
      ],
    };

    await act(async () => {
      const src = MockEventSource.instances[0];
      src.simulateOpen();
      src.simulateMessage("snapshot", JSON.stringify(payload));
    });

    expect(result.current.status).toBe("live");
    expect(result.current.snapshot).toEqual(payload);
  });

  it("transitions to reconnecting after an error", async () => {
    vi.useFakeTimers();
    const { useLiveStream } = await import("@/lib/use-live-stream");
    const { result } = renderHook(() => useLiveStream());

    await act(async () => {
      const src = MockEventSource.instances[0];
      src.simulateOpen();
      src.simulateError();
    });

    expect(["reconnecting", "stale"]).toContain(result.current.status);
  });

  it("closes the EventSource on unmount", async () => {
    const { useLiveStream } = await import("@/lib/use-live-stream");
    const { unmount } = renderHook(() => useLiveStream());

    const src = MockEventSource.instances[0];
    unmount();

    expect(src.readyState).toBe(2); // CLOSED
  });
});
