"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  type UTCTimestamp,
  type IChartApi,
} from "lightweight-charts";
import type { Candle } from "@/lib/types";

interface PriceLine {
  price: number;
  color?: string;
  title?: string;
}

interface PriceChartProps {
  candles: Candle[];
  priceLines?: PriceLine[];
  height?: number;
}

function resolvePriceLineColor(line: PriceLine): string {
  if (line.color) return line.color;
  const t = (line.title ?? "").toLowerCase();
  if (t.includes("tp") || t.includes("take profit")) return "#22d37f";
  if (t.includes("sl") || t.includes("stop loss")) return "#f06868";
  return "#7b8ea0"; // neutral for entry / unknown
}

export function PriceChart({ candles, priceLines, height = 360 }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const container = containerRef.current;
    if (!container) return;

    // Read CSS tokens if available, fall back to dark hex defaults.
    const cs = getComputedStyle(document.documentElement);
    const token = (name: string, fallback: string) => {
      const v = cs.getPropertyValue(name).trim();
      return v || fallback;
    };

    const bg = token("--color-background", "#121722");
    const textColor = token("--color-foreground", "#dfe6ee");
    const gridColor = token("--color-border", "#1f2632");

    const chart: IChartApi = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: bg },
        textColor,
      },
      grid: {
        vertLines: { color: gridColor },
        horzLines: { color: gridColor },
      },
      width: container.clientWidth,
      height,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const series = chart.addCandlestickSeries({
      upColor: "#22d37f",
      downColor: "#f06868",
      borderUpColor: "#22d37f",
      borderDownColor: "#f06868",
      wickUpColor: "#22d37f",
      wickDownColor: "#f06868",
    });

    // Convert ISO timestamps to UNIX seconds, de-dupe (keep last), sort asc.
    const seen = new Map<number, { time: UTCTimestamp; open: number; high: number; low: number; close: number }>();
    for (const c of candles) {
      const time = Math.floor(Date.parse(c.t) / 1000) as UTCTimestamp;
      seen.set(time, { time, open: c.o, high: c.h, low: c.l, close: c.c });
    }
    const data = Array.from(seen.values()).sort((a, b) => (a.time as number) - (b.time as number));
    series.setData(data);

    // Price-line overlays (entry / TP / SL).
    for (const pl of priceLines ?? []) {
      series.createPriceLine({
        price: pl.price,
        color: resolvePriceLineColor(pl),
        title: pl.title ?? "",
        lineWidth: 1,
        lineStyle: 2, // dashed
        axisLabelVisible: true,
      });
    }

    chart.timeScale().fitContent();

    // Resize observer keeps the chart in sync with the container width.
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const w = entry.contentRect.width;
        chart.applyOptions({ width: w });
        chart.resize(w, height);
      }
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
      chart.remove();
    };
  }, [candles, priceLines, height]);

  return <div ref={containerRef} style={{ height }} className="w-full" />;
}
