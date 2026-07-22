"use client";

import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { EquityPoint } from "@/lib/types";
import { useDisplay } from "@/lib/money";

/* Bot in cobalto pieno; benchmark SPY in grigi tratteggiati (due dash
   diversi per le due viste): identità = colore + tratteggio + legenda. */
export function EquityChart({ points, benchmarkLabel = "SPY", showBenchmarks = true }: { points: EquityPoint[]; benchmarkLabel?: string; showBenchmarks?: boolean }) {
  const d = useDisplay();
  const chartConfig = {
    equity_usd: { label: "Trading Bot", color: "var(--chart-1)" },
    spy_lump_sum_usd: { label: `${benchmarkLabel} lump-sum`, color: "var(--benchmark)" },
    spy_cash_flow_matched_usd: { label: `${benchmarkLabel} cash-flow matched`, color: "var(--benchmark-alt)" },
  } satisfies ChartConfig;
  return (
    <ChartContainer
      config={chartConfig}
      className="aspect-auto h-[240px] w-full sm:h-[320px] [&_.recharts-cartesian-axis-tick_text]:font-mono [&_.recharts-cartesian-axis-tick_text]:text-[11px]"
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
          width={64}
          domain={["auto", "auto"]}
          tickFormatter={(v: number) => d.moneyCompact(v)}
        />
        <ChartTooltip
          content={
            <ChartTooltipContent
              labelFormatter={(_, payload) =>
                d.date(payload?.[0]?.payload?.date as string | undefined)
              }
              formatter={(value, name, item) => (
                <div className="flex w-full items-center gap-2">
                  <span
                    className="size-2 shrink-0 rounded-[2px]"
                    style={{ background: item.color }}
                  />
                  <span className="text-muted-foreground">
                    {chartConfig[name as keyof typeof chartConfig]?.label ?? name}
                  </span>
                  <span className="text-foreground ml-auto font-mono font-medium tabular-nums">
                    {d.money(typeof value === "number" ? value : null)}
                  </span>
                </div>
              )}
            />
          }
        />
        <Line
          dataKey="equity_usd"
          type="monotone"
          stroke="var(--color-equity_usd)"
          strokeWidth={1.5}
          dot={false}
          connectNulls
        />
        {showBenchmarks ? (
          <>
            <Line dataKey="spy_lump_sum_usd" type="monotone" stroke="var(--color-spy_lump_sum_usd)" strokeWidth={1.5} strokeDasharray="6 4" dot={false} connectNulls />
            <Line dataKey="spy_cash_flow_matched_usd" type="monotone" stroke="var(--color-spy_cash_flow_matched_usd)" strokeWidth={1.5} strokeDasharray="2 3" dot={false} connectNulls />
            <ChartLegend content={<ChartLegendContent />} />
          </>
        ) : null}
      </LineChart>
    </ChartContainer>
  );
}
