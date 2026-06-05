"use client";

import { useTheme } from "next-themes";

export interface ChartTheme {
  grid: string;
  axis: string;
  text: string;
  up: string;
  down: string;
  info: string;
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
  positive: "#22d37f",
  negative: "#f06868",
  tooltipBg: "#121722",
  tooltipBorder: "#1f2632",
  pie: ["#22d37f", "#58a6ff", "#a78bfa", "#f59e0b", "#f06868", "#2dd4bf", "#eab308"],
};

const LIGHT: ChartTheme = {
  grid: "#e4e7ec",
  axis: "#525c6e",
  text: "#1a1f29",
  up: "#12a150",
  down: "#e5484d",
  info: "#2f6feb",
  positive: "#12a150",
  negative: "#e5484d",
  tooltipBg: "#ffffff",
  tooltipBorder: "#e4e7ec",
  pie: ["#12a150", "#2f6feb", "#7c3aed", "#d98300", "#e5484d", "#0d9488", "#ca8a04"],
};

export function useChartTheme(): ChartTheme {
  const { resolvedTheme } = useTheme();
  return resolvedTheme === "light" ? LIGHT : DARK;
}
