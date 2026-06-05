"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber } from "@/lib/format";
import type { ReturnsBin } from "@/lib/types";
import { useChartTheme } from "@/components/charts/use-chart-theme";

export interface ReturnsDistributionChartProps {
  bins: ReturnsBin[];
  loading?: boolean;
}

export function ReturnsDistributionChart({ bins }: ReturnsDistributionChartProps) {
  const theme = useChartTheme();

  const distributionData = useMemo(() => {
    const fmt = (v: number) =>
      formatNumber(v, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
    return bins.map((b) => ({
      // X-axis: use only the upper bound of the bin so labels stay readable
      // even with negative values. The full range goes in the tooltip rangeLabel.
      label: `${fmt(b.hi)}%`,
      rangeLabel: `${fmt(b.lo)}% / ${fmt(b.hi)}%`,
      count: b.count,
      negative: b.hi <= 0,
    }));
  }, [bins]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Distribuzione dei rendimenti (%)</CardTitle>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer>
          <BarChart
            data={distributionData}
            margin={{ top: 10, right: 10, left: 0, bottom: 24 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
            <XAxis
              dataKey="label"
              stroke={theme.grid}
              tick={{ fill: theme.axis, fontSize: 11 }}
              interval={0}
              angle={-35}
              textAnchor="end"
              height={48}
              tickMargin={8}
            />
            <YAxis stroke={theme.grid} tick={{ fill: theme.axis, fontSize: 11 }} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: "rgba(148, 163, 184, 0.08)" }}
              contentStyle={{
                background: theme.tooltipBg,
                border: `1px solid ${theme.tooltipBorder}`,
                borderRadius: 8,
                color: theme.text,
              }}
              labelStyle={{ color: theme.axis, marginBottom: 4 }}
              itemStyle={{ color: theme.text }}
              labelFormatter={(_label, payload) => {
                const p = payload?.[0]?.payload as { rangeLabel?: string } | undefined;
                return p?.rangeLabel ?? "";
              }}
              formatter={(v: number) => [v, "# Trade"]}
            />
            <Bar dataKey="count">
              {distributionData.map((entry, idx) => (
                <Cell key={idx} fill={entry.negative ? theme.negative : theme.positive} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
