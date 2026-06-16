import { describe, it, expect } from "vitest";
import { formatRangeLabel } from "@/components/dashboard/date-range-picker";

describe("formatRangeLabel", () => {
  it("labels an empty range as full history", () => {
    expect(formatRangeLabel({ from: null, to: null })).toBe("Storico completo");
  });

  it("labels a from-only range with a 'Dal' prefix", () => {
    const label = formatRangeLabel({ from: new Date(2026, 5, 1), to: null });
    expect(label.startsWith("Dal ")).toBe(true);
  });

  it("labels a two-ended range with an en dash separator", () => {
    const label = formatRangeLabel({ from: new Date(2026, 2, 18), to: new Date(2026, 5, 16) });
    expect(label).toContain("–");
  });

  it("collapses a same-day range to a single date", () => {
    const label = formatRangeLabel({ from: new Date(2026, 5, 16), to: new Date(2026, 5, 16) });
    expect(label).not.toContain("–");
    expect(label.length).toBeGreaterThan(0);
  });
});
