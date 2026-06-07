import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { useChartTheme } from "../use-chart-theme";

vi.mock("next-themes", () => ({
  useTheme: vi.fn(),
}));

import { useTheme } from "next-themes";
import type { Mock } from "vitest";

describe("useChartTheme", () => {
  it("returns dark palette when resolvedTheme is 'dark'", () => {
    (useTheme as Mock).mockReturnValue({ resolvedTheme: "dark" });
    const { result } = renderHook(() => useChartTheme());
    const theme = result.current;

    // Has all expected keys
    const keys: Array<keyof typeof theme> = [
      "grid", "axis", "text", "up", "down", "info",
      "positive", "negative", "tooltipBg", "tooltipBorder", "pie",
    ];
    for (const key of keys) {
      expect(theme).toHaveProperty(key);
    }

    // Spot-check dark values
    expect(theme.grid).toBe("#1f2632");
    expect(theme.text).toBe("#dfe6ee");
    expect(theme.up).toBe("#22d37f");
    expect(Array.isArray(theme.pie)).toBe(true);
    expect(theme.pie.length).toBeGreaterThan(0);
  });

  it("returns light palette when resolvedTheme is 'light'", () => {
    (useTheme as Mock).mockReturnValue({ resolvedTheme: "light" });
    const { result } = renderHook(() => useChartTheme());
    const theme = result.current;

    // Spot-check light values
    expect(theme.grid).toBe("#e4e7ec");
    expect(theme.text).toBe("#1a1f29");
    expect(theme.up).toBe("#12a150");
    expect(Array.isArray(theme.pie)).toBe(true);
  });

  it("differs between dark and light themes on key fields", () => {
    (useTheme as Mock).mockReturnValue({ resolvedTheme: "dark" });
    const { result: dark } = renderHook(() => useChartTheme());

    (useTheme as Mock).mockReturnValue({ resolvedTheme: "light" });
    const { result: light } = renderHook(() => useChartTheme());

    expect(dark.current.grid).not.toBe(light.current.grid);
    expect(dark.current.text).not.toBe(light.current.text);
    expect(dark.current.up).not.toBe(light.current.up);
  });

  it("returns dark palette (default) when resolvedTheme is undefined", () => {
    (useTheme as Mock).mockReturnValue({ resolvedTheme: undefined });
    const { result } = renderHook(() => useChartTheme());
    const theme = result.current;

    expect(theme.grid).toBe("#1f2632");
    expect(theme.text).toBe("#dfe6ee");
  });
});
