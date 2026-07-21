"use client";

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { RiskHistoryPoint } from "@/lib/types";
import { useDisplay } from "@/lib/money";

const chartConfig = {
  score: { label: "Risk score", color: "var(--chart-1)" },
} satisfies ChartConfig;

export function RiskHistoryChart({ points }: { points: RiskHistoryPoint[] }) {
  const d = useDisplay();
  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[220px] w-full [&_.recharts-cartesian-axis-tick_text]:font-mono [&_.recharts-cartesian-axis-tick_text]:text-[11px]"
    >
      <LineChart data={points} margin={{ left: 4, right: 12, top: 8 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" strokeWidth={1} />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          minTickGap={48}
          tickFormatter={(v: string) => d.dateShort(v)}
        />
        <YAxis
          tickLine={false}
          axisLine={false}
          width={28}
          domain={[0, 10]}
          ticks={[0, 2, 4, 6, 8, 10]}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(_, payload) =>
                d.date(payload?.[0]?.payload?.date as string | undefined)
              }
            />
          }
        />
        <Line
          dataKey="score"
          type="monotone"
          stroke="var(--color-score)"
          strokeWidth={1.5}
          dot={false}
        />
      </LineChart>
    </ChartContainer>
  );
}
