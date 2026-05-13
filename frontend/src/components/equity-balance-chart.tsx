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
import { Input } from "@/components/ui/input";
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

type Period = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y" | "All" | "Custom";
type Granularity = "15m" | "1h" | "4h" | "1d";

const PERIOD_OPTIONS: { value: Period; label: string }[] = [
  { value: "1D", label: "Ultimo giorno" },
  { value: "1W", label: "Ultima settimana" },
  { value: "1M", label: "Ultimo mese" },
  { value: "3M", label: "Ultimi 3 mesi" },
  { value: "6M", label: "Ultimi 6 mesi" },
  { value: "1Y", label: "Ultimo anno" },
  { value: "All", label: "Storico completo" },
  { value: "Custom", label: "Periodo personalizzato" },
];

const GRANULARITY_OPTIONS: { value: Granularity; label: string }[] = [
  { value: "15m", label: "15 min" },
  { value: "1h", label: "1 ora" },
  { value: "4h", label: "4 ore" },
  { value: "1d", label: "1 giorno" },
];

const MAX_VISIBLE_POINTS = 80;

function toLocalInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(
    date.getHours()
  )}:${pad(date.getMinutes())}`;
}

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

export function EquityBalanceChart({ fallbackCurrency }: { fallbackCurrency: string }) {
  const now = useMemo(() => new Date(), []);
  const [period, setPeriod] = useState<Period>("1W");
  const [granularity, setGranularity] = useState<Granularity>("1h");
  const [customFrom, setCustomFrom] = useState<string>(() =>
    toLocalInputValue(new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000))
  );
  const [customTo, setCustomTo] = useState<string>(() => toLocalInputValue(now));

  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("granularity", granularity);
    if (period === "Custom") {
      const fromDate = new Date(customFrom);
      const toDate = new Date(customTo);
      if (!Number.isNaN(fromDate.getTime())) params.set("from", fromDate.toISOString());
      if (!Number.isNaN(toDate.getTime())) params.set("to", toDate.toISOString());
    } else {
      params.set("window", period);
    }
    return params.toString();
  }, [period, granularity, customFrom, customTo]);

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
            <CardTitle>Andamento del saldo totale</CardTitle>
            <span className="text-xs text-(--color-muted)">
              Snapshot ogni 15&nbsp;min · valuta {currency}
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={period} onValueChange={(v) => setPeriod(v as Period)}>
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PERIOD_OPTIONS.map((opt) => (
                  <SelectItem key={opt.value} value={opt.value}>
                    {opt.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
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
        </div>
        {period === "Custom" && (
          <div className="mt-3 grid w-full grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="flex flex-col gap-1 text-xs text-(--color-muted)">
              Da
              <Input
                type="datetime-local"
                value={customFrom}
                onChange={(e) => setCustomFrom(e.target.value)}
                className="h-8"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-(--color-muted)">
              A
              <Input
                type="datetime-local"
                value={customTo}
                onChange={(e) => setCustomTo(e.target.value)}
                className="h-8"
              />
            </label>
          </div>
        )}
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
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis
                dataKey="t"
                stroke="#94a3b8"
                fontSize={11}
                tickMargin={8}
                minTickGap={32}
                tickFormatter={(v: string) => formatTickForGranularity(v, granularity)}
              />
              <YAxis
                stroke="#94a3b8"
                fontSize={12}
                tickFormatter={(v) => formatCurrency(v, currency)}
                width={90}
                domain={["auto", "auto"]}
              />
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid #1f2937",
                  borderRadius: 8,
                  color: "#e2e8f0",
                }}
                labelStyle={{ color: "#94a3b8" }}
                itemStyle={{ color: "#e2e8f0" }}
                labelFormatter={(label: string) => formatTooltipLabel(label)}
                formatter={(v: number) => [formatCurrency(v, currency), "Saldo"]}
              />
              <Line
                type="monotone"
                dataKey="equity"
                stroke="#38bdf8"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
              {showBrush && (
                <Brush
                  dataKey="t"
                  height={24}
                  stroke="#38bdf8"
                  fill="#0f172a"
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
