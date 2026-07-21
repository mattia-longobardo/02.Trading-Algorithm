"use client";

import { PolarAngleAxis, RadialBar, RadialBarChart } from "recharts";

import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import type { RiskBand } from "@/lib/types";
import { fmtNum } from "@/lib/format";

/* Toni da stampa, theme-aware via token CSS. */
export const BAND_META: Record<
  RiskBand,
  { label: string; color: string; range: string }
> = {
  low: { label: "Basso", color: "var(--positive)", range: "1–3" },
  medium: { label: "Medio", color: "var(--caution)", range: "4–6" },
  high: { label: "Alto", color: "var(--risk-high)", range: "7–8" },
  extreme: { label: "Estremo", color: "var(--negative)", range: "9–10" },
};

const chartConfig = { score: { label: "Risk score" } } satisfies ChartConfig;

/** Gauge semicircolare 1–10 con fascia colorata (§11.4). */
export function RiskGauge({ score, band }: { score: number; band: RiskBand }) {
  const meta = BAND_META[band];
  const data = [{ name: "score", score, fill: meta.color }];

  return (
    <div className="relative mx-auto w-full max-w-[280px]">
      <ChartContainer config={chartConfig} className="aspect-[2/1.2] w-full">
        <RadialBarChart
          data={data}
          startAngle={210}
          endAngle={-30}
          innerRadius="80%"
          outerRadius="130%"
          cy="65%"
        >
          <PolarAngleAxis
            type="number"
            domain={[0, 10]}
            angleAxisId={0}
            tick={false}
          />
          <RadialBar
            dataKey="score"
            background
            cornerRadius={3}
            angleAxisId={0}
            isAnimationActive={false}
          />
        </RadialBarChart>
      </ChartContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center pt-6">
        <span className="font-mono text-4xl font-semibold tabular-nums">
          {fmtNum(score, 1)}
        </span>
        <span
          className="font-mono text-[11px] font-medium tracking-[0.1em] uppercase"
          style={{ color: meta.color }}
        >
          {meta.label} ({meta.range})
        </span>
        <span className="text-muted-foreground font-mono text-[10px] tracking-[0.08em] uppercase">
          su 10
        </span>
      </div>
    </div>
  );
}
