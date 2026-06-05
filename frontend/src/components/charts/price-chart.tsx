"use client";

import { useEffect, useRef } from "react";
import {
  createChart,
  ColorType,
  type UTCTimestamp,
  type IChartApi,
} from "lightweight-charts";
import type { Candle } from "@/lib/types";
import { useChartTheme, type ChartTheme } from "./use-chart-theme";

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

function resolvePriceLineColor(line: PriceLine, theme: ChartTheme): string {
  if (line.color) return line.color;
  const t = (line.title ?? "").toLowerCase();
  if (t.includes("tp") || t.includes("take profit")) return theme.up;
  if (t.includes("sl") || t.includes("stop loss")) return theme.down;
  return theme.info; // entry / unknown
}

export function PriceChart({ candles, priceLines, height = 360 }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const theme = useChartTheme();

  useEffect(() => {
    if (typeof window === "undefined") return;
    const container = containerRef.current;
    if (!container) return;

    const chart: IChartApi = createChart(container, {
      layout: {
        background: { type: ColorType.Solid, color: theme.tooltipBg },
        textColor: theme.text,
      },
      grid: {
        vertLines: { color: theme.grid },
        horzLines: { color: theme.grid },
      },
      width: container.clientWidth,
      height,
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const series = chart.addCandlestickSeries({
      upColor: theme.up,
      downColor: theme.down,
      borderUpColor: theme.up,
      borderDownColor: theme.down,
      wickUpColor: theme.up,
      wickDownColor: theme.down,
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
        color: resolvePriceLineColor(pl, theme),
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
  }, [candles, priceLines, height, theme]);

  return <div ref={containerRef} style={{ height }} className="w-full" />;
}
