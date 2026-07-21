"use client";

import { Line, LineChart, YAxis } from "recharts";

import { ChartContainer, type ChartConfig } from "@/components/ui/chart";
import type { EquityPoint } from "@/lib/types";

const chartConfig = {
  equity_usd: { label: "Equity", color: "var(--chart-1)" },
} satisfies ChartConfig;

/** Mini equity-curve per la dashboard: nessun asse, solo l'andamento. */
export function EquitySparkline({ points }: { points: EquityPoint[] }) {
  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-14 w-full">
      <LineChart data={points} margin={{ top: 4, bottom: 4, left: 0, right: 0 }}>
        <YAxis hide domain={["auto", "auto"]} />
        <Line
          dataKey="equity_usd"
          type="monotone"
          stroke="var(--color-equity_usd)"
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
      </LineChart>
    </ChartContainer>
  );
}
