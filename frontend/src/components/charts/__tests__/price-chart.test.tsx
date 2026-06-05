import { render } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Mock } from "vitest";
import { PriceChart } from "../price-chart";
import type { Candle } from "@/lib/types";

// ---------------------------------------------------------------------------
// Stub lightweight-charts so the tests never touch a real canvas.
// ---------------------------------------------------------------------------
const mockSetData = vi.fn();
const mockCreatePriceLine = vi.fn();
const mockFitContent = vi.fn();
const mockApplyOptions = vi.fn();
const mockResize = vi.fn();
const mockRemove = vi.fn();

const mockSeries = {
  setData: mockSetData,
  createPriceLine: mockCreatePriceLine,
};

const mockTimeScale = {
  fitContent: mockFitContent,
};

const mockChart = {
  addCandlestickSeries: vi.fn(() => mockSeries),
  timeScale: vi.fn(() => mockTimeScale),
  applyOptions: mockApplyOptions,
  resize: mockResize,
  remove: mockRemove,
};

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => mockChart),
  ColorType: { Solid: "solid" },
}));

// jsdom lacks ResizeObserver; provide a stub.
const observeSpy = vi.fn();
const disconnectSpy = vi.fn();
class FakeResizeObserver {
  constructor(private cb: ResizeObserverCallback) {}
  observe(el: Element) {
    observeSpy(el);
  }
  disconnect() {
    disconnectSpy();
  }
}
vi.stubGlobal("ResizeObserver", FakeResizeObserver);

// ---------------------------------------------------------------------------

import { createChart } from "lightweight-charts";

const TWO_CANDLES: Candle[] = [
  { t: "2024-01-02T00:00:00Z", o: 100, h: 110, l: 90, c: 105, v: 1000 },
  { t: "2024-01-01T00:00:00Z", o: 95, h: 105, l: 88, c: 100, v: 800 },
];

describe("PriceChart", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Re-attach the mock return value after clearAllMocks resets it.
    (mockChart.addCandlestickSeries as Mock).mockReturnValue(mockSeries);
    (mockChart.timeScale as Mock).mockReturnValue(mockTimeScale);
    (createChart as Mock).mockReturnValue(mockChart);
  });

  it("calls createChart when rendered", () => {
    render(<PriceChart candles={TWO_CANDLES} />);
    expect(createChart).toHaveBeenCalledTimes(1);
  });

  it("maps candles to {time,open,high,low,close} in ascending order", () => {
    render(<PriceChart candles={TWO_CANDLES} />);

    expect(mockSetData).toHaveBeenCalledTimes(1);
    const points = mockSetData.mock.calls[0][0] as Array<{
      time: number;
      open: number;
      high: number;
      low: number;
      close: number;
    }>;

    expect(points).toHaveLength(2);

    // Must be ascending by time.
    expect(points[0].time).toBeLessThan(points[1].time);

    // Verify correct field mapping (not just order).
    const jan1 = points.find((p) => p.time === Math.floor(Date.parse("2024-01-01T00:00:00Z") / 1000));
    const jan2 = points.find((p) => p.time === Math.floor(Date.parse("2024-01-02T00:00:00Z") / 1000));

    expect(jan1).toBeDefined();
    expect(jan1).toMatchObject({ open: 95, high: 105, low: 88, close: 100 });

    expect(jan2).toBeDefined();
    expect(jan2).toMatchObject({ open: 100, high: 110, low: 90, close: 105 });

    // No extra keys like `v`.
    expect(Object.keys(jan1!)).toEqual(["time", "open", "high", "low", "close"]);
  });

  it("de-duplicates candles with equal timestamps keeping the last one", () => {
    const dupes: Candle[] = [
      { t: "2024-01-01T00:00:00Z", o: 1, h: 2, l: 0.5, c: 1.5, v: null },
      { t: "2024-01-01T00:00:00Z", o: 9, h: 10, l: 8, c: 9.5, v: null }, // same ts — kept
    ];
    render(<PriceChart candles={dupes} />);
    const points = mockSetData.mock.calls[0][0] as Array<unknown>;
    expect(points).toHaveLength(1);
    expect((points[0] as { close: number }).close).toBe(9.5);
  });

  it("calls createPriceLine once for a single priceLines entry", () => {
    render(
      <PriceChart
        candles={TWO_CANDLES}
        priceLines={[{ price: 100, title: "Entry" }]}
      />
    );
    expect(mockCreatePriceLine).toHaveBeenCalledTimes(1);
    expect(mockCreatePriceLine).toHaveBeenCalledWith(
      expect.objectContaining({ price: 100, title: "Entry" })
    );
  });

  it("cleans up chart and observer on unmount", () => {
    const { unmount } = render(<PriceChart candles={TWO_CANDLES} />);
    unmount();
    expect(mockRemove).toHaveBeenCalledTimes(1);
    expect(disconnectSpy).toHaveBeenCalledTimes(1);
  });
});
