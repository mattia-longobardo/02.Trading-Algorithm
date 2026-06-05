"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { TimeframeSelector, type Timeframe } from "@/components/timeframe-selector";
import { EquityBalanceChart } from "@/components/equity-balance-chart";
import { KpiStrip } from "@/components/dashboard/kpi-strip";
import { CategoryAllocationChart } from "@/components/dashboard/category-allocation-chart";
import { PnlBySymbolChart } from "@/components/dashboard/pnl-by-symbol-chart";
import { ReturnsDistributionChart } from "@/components/dashboard/returns-distribution-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LiveBadge } from "@/components/live/live-badge";
import { useLiveStream } from "@/lib/use-live-stream";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import { formatCurrency } from "@/lib/format";
import type {
  AllocationCategory,
  AllocationSymbol,
  EquityPoint,
  Metrics,
  PnlBySymbolRow,
  ReturnsBin,
} from "@/lib/types";
import { useChartTheme } from "@/components/charts/use-chart-theme";

// Query keys the dashboard reads. We refresh them as a group on a single
// wall-clock-aligned tick (see ``useDashboardAutoRefresh`` below).
const DASHBOARD_QUERY_KEYS = [
  "metrics",
  "equity",
  "allocation",
  "pnl-by-symbol",
  "returns-distribution",
  "fx-rate",
  "account-balance",
] as const;

// The backend's ``monitor_trades`` cron job fires every minute at ``:XX:00``
// UTC and refreshes broker prices / PnL in SQLite. We want the dashboard to
// re-fetch *after* that job completes so the new market data is visible —
// so we align the client tick to ``:XX:30``: 30 s past the cron mark gives
// the job enough headroom while keeping the lag small.
const REFRESH_OFFSET_SECONDS = 30;

function useDashboardAutoRefresh(): Date | null {
  const qc = useQueryClient();
  const [lastTick, setLastTick] = useState<Date | null>(null);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    function scheduleNext() {
      const now = new Date();
      const next = new Date(now);
      next.setSeconds(REFRESH_OFFSET_SECONDS, 0);
      if (next <= now) next.setMinutes(next.getMinutes() + 1);
      const delayMs = next.getTime() - now.getTime();
      timer = setTimeout(() => {
        for (const key of DASHBOARD_QUERY_KEYS) {
          qc.invalidateQueries({ queryKey: [key] });
        }
        setLastTick(new Date());
        scheduleNext();
      }, delayMs);
    }
    scheduleNext();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [qc]);
  return lastTick;
}

export default function DashboardPage() {
  const theme = useChartTheme();
  const [timeframe, setTimeframe] = useState<Timeframe>("3M");
  const lastAutoRefresh = useDashboardAutoRefresh();
  const { status: liveStatus } = useLiveStream();

  const metrics = useQuery({
    queryKey: ["metrics", timeframe],
    queryFn: () => api.get<Metrics>(`/api/metrics?window=${timeframe}`),
  });
  const equity = useQuery({
    queryKey: ["equity", timeframe],
    queryFn: () => api.get<{ points: EquityPoint[] }>(`/api/equity-curve?window=${timeframe}`),
  });
  const fxRate = useQuery({
    queryKey: ["fx-rate"],
    queryFn: () =>
      api.get<{
        from: string;
        to: string;
        rate: number | null;
        stale: boolean;
        available: boolean;
      }>(`/api/fx/rate`),
    staleTime: 5 * 60 * 1000,
  });
  const pnlBySymbol = useQuery({
    queryKey: ["pnl-by-symbol", timeframe],
    queryFn: () => api.get<{ items: PnlBySymbolRow[] }>(`/api/pnl-by-symbol?window=${timeframe}`),
  });
  const allocation = useQuery({
    queryKey: ["allocation"],
    queryFn: () =>
      api.get<{
        by_category: AllocationCategory[];
        by_symbol: AllocationSymbol[];
      }>("/api/allocation"),
  });
  const distribution = useQuery({
    queryKey: ["returns-distribution", timeframe],
    queryFn: () =>
      api.get<{ bins: ReturnsBin[] }>(`/api/returns-distribution?window=${timeframe}&bins=12`),
  });

  const m = metrics.data;
  const currency = m?.currency ?? "EUR";

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Dashboard</h1>
          <p className="text-sm text-(--color-muted)">
            Performance del bot — i KPI ricalcolano sull&apos;intervallo selezionato.
            I dati si aggiornano una volta al minuto, ~30 s dopo il tick di
            mercato del backend.
          </p>
          {lastAutoRefresh && (
            <p className="mt-1 text-xs text-(--color-muted)">
              Ultimo aggiornamento:{" "}
              {lastAutoRefresh.toLocaleTimeString(undefined, {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <LiveBadge status={liveStatus} />
          {fxRate.data && fxRate.data.from !== fxRate.data.to && (
            <div
              className={`rounded-lg border px-3 py-1.5 text-xs ${
                fxRate.data.available
                  ? fxRate.data.stale
                    ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                    : "border-(--color-line) bg-(--color-panel)/70 text-(--color-muted)"
                  : "border-rose-500/40 bg-rose-500/10 text-rose-300"
              }`}
              title={
                fxRate.data.available
                  ? fxRate.data.stale
                    ? "Tasso ottenuto in passato; il provider FX al momento non risponde."
                    : `1 ${fxRate.data.from} = ${(fxRate.data.rate ?? 0).toFixed(4)} ${fxRate.data.to}`
                  : "Nessun provider FX raggiungibile: i valori restano in valuta broker."
              }
            >
              {fxRate.data.available && fxRate.data.rate != null ? (
                <>
                  {fxRate.data.stale && "⚠ "}1 {fxRate.data.from} ={" "}
                  <span className="tnum font-medium tabular-nums">
                    {fxRate.data.rate.toFixed(4)}
                  </span>{" "}
                  {fxRate.data.to}
                </>
              ) : (
                <>FX non disponibile</>
              )}
            </div>
          )}
          <TimeframeSelector value={timeframe} onChange={setTimeframe} />
        </div>
      </header>

      {/* KPI grid */}
      <KpiStrip metrics={m} loading={metrics.isLoading} />

      {/* Account equity + equity curve */}
      <EquityBalanceChart fallbackCurrency={currency} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Equity curve (PnL realizzato cumulato)</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer>
              <LineChart data={equity.data?.points ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke={theme.grid} />
                <XAxis dataKey="t" stroke={theme.grid} tick={{ fill: theme.axis, fontSize: 11 }} tickMargin={8} />
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
                  labelStyle={{ color: theme.axis }}
                  itemStyle={{ color: theme.text }}
                  formatter={(v: number) => formatCurrency(v, currency)}
                />
                <Line
                  type="monotone"
                  dataKey="equity"
                  stroke={theme.up}
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Allocation donut */}
        <CategoryAllocationChart
          byCategory={allocation.data?.by_category ?? []}
          currency={currency}
          loading={allocation.isLoading}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* PnL by symbol bar chart */}
        <PnlBySymbolChart
          items={pnlBySymbol.data?.items ?? []}
          currency={currency}
          loading={pnlBySymbol.isLoading}
        />

        {/* Returns histogram */}
        <ReturnsDistributionChart
          bins={distribution.data?.bins ?? []}
          loading={distribution.isLoading}
        />
      </div>
    </section>
  );
}
