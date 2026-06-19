"use client";

import { useTheme } from "next-themes";

export interface ChartTheme {
  grid: string;
  axis: string;
  text: string;
  up: string;
  down: string;
  info: string;
  warning: string;
  positive: string;
  negative: string;
  tooltipBg: string;
  tooltipBorder: string;
  pie: string[];
}

const DARK: ChartTheme = {
  grid: "#1f2632",
  axis: "#6b7484",
  text: "#dfe6ee",
  up: "#22d37f",
  down: "#f06868",
  info: "#58a6ff",
  warning: "#f59e0b",
  positive: "#22d37f",
  negative: "#f06868",
  tooltipBg: "#121722",
  tooltipBorder: "#1f2632",
  pie: ["#22d37f", "#58a6ff", "#a78bfa", "#f59e0b", "#f06868", "#2dd4bf", "#eab308"],
};

const LIGHT: ChartTheme = {
  grid: "#cbd5e1",
  axis: "#475569",
  text: "#0f172a",
  up: "#047857",
  down: "#b42318",
  info: "#1d4ed8",
  warning: "#8a4b00",
  positive: "#047857",
  negative: "#b42318",
  tooltipBg: "#ffffff",
  tooltipBorder: "#cbd5e1",
  pie: ["#047857", "#1d4ed8", "#6d28d9", "#8a4b00", "#b42318", "#0f766e", "#854d0e"],
};

export function useChartTheme(): ChartTheme {
  const { resolvedTheme } = useTheme();
  return resolvedTheme === "light" ? LIGHT : DARK;
}
