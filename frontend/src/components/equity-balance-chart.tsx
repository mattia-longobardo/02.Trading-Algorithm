"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Brush,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import type { EquityPoint } from "@/lib/types";
import { useChartTheme } from "@/components/charts/use-chart-theme";

type Granularity = "15m" | "1h" | "4h" | "1d";

const GRANULARITY_OPTIONS: { value: Granularity; label: string }[] = [
  { value: "15m", label: "15 min" },
  { value: "1h", label: "1 ora" },
  { value: "4h", label: "4 ore" },
  { value: "1d", label: "1 giorno" },
];

const MAX_VISIBLE_POINTS = 80;

function formatTickForGranularity(iso: string, granularity: Granularity): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (granularity === "1d") {
    return d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "2-digit" });
  }
  if (granularity === "4h") {
    return d.toLocaleString("it-IT", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  }
  return d.toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTooltipLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("it-IT", { dateStyle: "medium", timeStyle: "short" });
}

export function EquityBalanceChart({
  fallbackCurrency,
  from,
  to,
}: {
  fallbackCurrency: string;
  from: Date | null;
  to: Date | null;
}) {
  const theme = useChartTheme();
  const [granularity, setGranularity] = useState<Granularity>("1h");

  // Period comes from the dashboard's single date-range picker; this chart only
  // owns the granularity. Empty from/to = whole history.
  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("granularity", granularity);
    if (from) {
      const f = new Date(from);
      f.setHours(0, 0, 0, 0);
      params.set("from", f.toISOString());
    }
    if (to) {
      const t = new Date(to);
      t.setHours(23, 59, 59, 999);
      params.set("to", t.toISOString());
    }
    return params.toString();
  }, [granularity, from, to]);

  const balance = useQuery({
    queryKey: ["account-balance", queryParams],
    queryFn: () =>
      api.get<{ points: EquityPoint[]; currency: string }>(
        `/api/account-equity-curve?${queryParams}`
      ),
  });

  const points = balance.data?.points ?? [];
  const currency = balance.data?.currency ?? fallbackCurrency;
  const showBrush = points.length > MAX_VISIBLE_POINTS;
  const startIndex = showBrush ? points.length - MAX_VISIBLE_POINTS : 0;
  const endIndex = points.length > 0 ? points.length - 1 : 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <CardTitle>Andamento del Saldo Totale</CardTitle>
            <span className="text-xs text-(--color-muted)">
              Snapshot ogni 15&nbsp;min · valuta {currency} · periodo dal selettore in alto
            </span>
          </div>
          <Select value={granularity} onValueChange={(v) => setGranularity(v as Granularity)}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {GRANULARITY_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardHeader>
      <CardContent className="h-80">
        {balance.isLoading ? (
          <p className="text-sm text-(--color-muted)">Caricamento…</p>
        ) : points.length === 0 ? (
          <p className="text-sm text-(--color-muted)">
            Nessuno snapshot nel periodo selezionato. Allarga l&apos;intervallo o
            aspetta lo snapshot equity ogni 15 minuti.
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
                tickFormatter={(v: string) => formatTickForGranularity(v, granularity)}
              />
              <YAxis
                stroke={theme.grid}
                tick={{ fill: theme.axis, fontSize: 11 }}
                tickFormatter={(v) => formatCurrency(v, currency)}
                width={90}
                domain={["auto", "auto"]}
              />
              <Tooltip
                contentStyle={{
                  background: theme.tooltipBg,
                  border: `1px solid ${theme.tooltipBorder}`,
                  borderRadius: 8,
                  color: theme.text,
                }}
                labelStyle={{ color: theme.axis }}
                itemStyle={{ color: theme.text }}
                labelFormatter={(label: string) => formatTooltipLabel(label)}
                formatter={(v: number) => [formatCurrency(v, currency), "Saldo"]}
              />
              <Line
                type="monotone"
                dataKey="equity"
                stroke={theme.info}
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              {showBrush && (
                <Brush
                  dataKey="t"
                  height={24}
                  stroke={theme.info}
                  fill={theme.tooltipBg}
                  travellerWidth={8}
                  startIndex={startIndex}
                  endIndex={endIndex}
                  tickFormatter={(v: string) => formatTickForGranularity(v, granularity)}
                />
              )}
            </LineChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  );
}
