"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency } from "@/lib/format";
import { useChartTheme } from "@/components/charts/use-chart-theme";

export interface CumulativeGainPoint {
  t: string;
  portfolio_eur: number | null;
  benchmark_eur: number | null;
}

const SERIES_LABELS: Record<string, string> = {
  portfolio_eur: "Conto (bot)",
  benchmark_eur: "Se investito nell'S&P 500",
};

function formatDayTick(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "2-digit" });
}

export function CumulativeGainChart({
  points,
  currency,
  loading,
  error,
  benchmarkSymbol = "SPX500",
}: {
  points: CumulativeGainPoint[];
  currency: string;
  loading?: boolean;
  error?: boolean;
  benchmarkSymbol?: string;
}) {
  const theme = useChartTheme();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Guadagno cumulato — bot vs S&amp;P 500</CardTitle>
        <span className="text-xs text-(--color-muted)">
          Guadagno/perdita totale del conto contro lo stesso capitale investito
          nell&apos;indice ({benchmarkSymbol}) alla data di partenza · valuta {currency}
        </span>
      </CardHeader>
      <CardContent className="h-80">
        {loading ? (
          <Skeleton className="h-full w-full" />
        ) : error ? (
          <p className="text-sm text-(--color-muted)">Errore nel caricamento</p>
        ) : points.length === 0 ? (
          <p className="text-sm text-(--color-muted)">
            Nessun dato nel periodo selezionato. Allarga l&apos;intervallo o aspetta il primo
            snapshot equity.
          </p>
        ) : (
          <ResponsiveContainer>
            <LineChart data={points} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
              <XAxis
                dataKey="t"
                stroke={theme.grid}
                tick={{ fill: theme.axis, fontSize: 11 }}
                tickMargin={8}
                minTickGap={32}
                tickFormatter={formatDayTick}
              />
              <YAxis
                stroke={theme.grid}
                tick={{ fill: theme.axis, fontSize: 11 }}
                tickFormatter={(v: number) => formatCurrency(v, currency)}
                width={90}
                domain={["auto", "auto"]}
              />
              <ReferenceLine y={0} stroke={theme.axis} strokeDasharray="4 4" />
              <Tooltip
                contentStyle={{
                  background: theme.tooltipBg,
                  border: `1px solid ${theme.tooltipBorder}`,
                  borderRadius: 8,
                  color: theme.text,
                }}
                labelStyle={{ color: theme.axis }}
                itemStyle={{ color: theme.text }}
                labelFormatter={(label: string) => formatDayTick(label)}
                formatter={(v: number, name: string) => [
                  formatCurrency(v, currency),
                  SERIES_LABELS[name] ?? name,
                ]}
              />
              <Legend formatter={(name: string) => SERIES_LABELS[name] ?? name} />
              <Line
                type="monotone"
                dataKey="portfolio_eur"
                stroke={theme.up}
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="benchmark_eur"
                stroke={theme.info}
                strokeWidth={2}
                dot={false}
                connectNulls
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
