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

export interface ReturnsDistributionChartProps {
  bins: ReturnsBin[];
  loading?: boolean;
}

export function ReturnsDistributionChart({ bins }: ReturnsDistributionChartProps) {
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
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              dataKey="label"
              stroke="#94a3b8"
              fontSize={11}
              interval={0}
              angle={-35}
              textAnchor="end"
              height={48}
              tickMargin={8}
            />
            <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
            <Tooltip
              cursor={{ fill: "rgba(148, 163, 184, 0.08)" }}
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #1f2937",
                borderRadius: 8,
                color: "#e2e8f0",
              }}
              labelStyle={{ color: "#94a3b8", marginBottom: 4 }}
              itemStyle={{ color: "#e2e8f0" }}
              labelFormatter={(_label, payload) => {
                const p = payload?.[0]?.payload as { rangeLabel?: string } | undefined;
                return p?.rangeLabel ?? "";
              }}
              formatter={(v: number) => [v, "# Trade"]}
            />
            <Bar dataKey="count">
              {distributionData.map((entry, idx) => (
                <Cell key={idx} fill={entry.negative ? "#f43f5e" : "#22c55e"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
