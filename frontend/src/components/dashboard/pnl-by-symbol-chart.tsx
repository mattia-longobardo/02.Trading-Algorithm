"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency } from "@/lib/format";
import type { PnlBySymbolRow } from "@/lib/types";
import { useChartTheme } from "@/components/charts/use-chart-theme";

export interface PnlBySymbolChartProps {
  items: PnlBySymbolRow[];
  currency: string;
  loading?: boolean;
  error?: boolean;
}

export function PnlBySymbolChart({ items, currency, loading, error }: PnlBySymbolChartProps) {
  const theme = useChartTheme();

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>PnL per simbolo</CardTitle>
        </CardHeader>
        <CardContent className="flex h-56 sm:h-72 items-center justify-center">
          <p className="text-sm text-(--color-muted)">Errore nel caricamento</p>
        </CardContent>
      </Card>
    );
  }

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>PnL per simbolo</CardTitle>
        </CardHeader>
        <CardContent className="h-56 sm:h-72">
          <Skeleton className="h-full w-full rounded-lg" />
        </CardContent>
      </Card>
    );
  }

  if (items.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>PnL per simbolo</CardTitle>
        </CardHeader>
        <CardContent className="flex h-56 sm:h-72 items-center justify-center">
          <p className="text-sm text-(--color-muted)">Nessun dato</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>PnL per simbolo</CardTitle>
      </CardHeader>
      <CardContent className="h-56 sm:h-72">
        <ResponsiveContainer>
          <BarChart data={items}>
            <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
            <XAxis dataKey="symbol" stroke={theme.grid} tick={{ fill: theme.axis, fontSize: 11 }} />
            <YAxis
              stroke={theme.grid}
              tick={{ fill: theme.axis, fontSize: 11 }}
              tickFormatter={(v) => formatCurrency(v, currency)}
              width={80}
            />
            <Tooltip
              contentStyle={{
                background: theme.tooltipBg,
                border: `1px solid ${theme.tooltipBorder}`,
                borderRadius: 8,
                color: theme.text,
              }}
              labelStyle={{ color: theme.text }}
              itemStyle={{ color: theme.text }}
              formatter={(v: number) => {
                const color = v < 0 ? theme.negative : v > 0 ? theme.positive : theme.text;
                return [
                  <span key="pnl" style={{ color, fontWeight: 600 }}>
                    {formatCurrency(v, currency)}
                  </span>,
                  "PnL",
                ];
              }}
            />
            <Bar dataKey="pnl_abs" name="PnL">
              {items.map((entry, idx) => (
                <Cell key={idx} fill={entry.pnl_abs < 0 ? theme.negative : theme.positive} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
