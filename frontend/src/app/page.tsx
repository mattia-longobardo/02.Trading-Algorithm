"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { TimeframeSelector, type Timeframe } from "@/components/timeframe-selector";
import { EquityBalanceChart } from "@/components/equity-balance-chart";
import { api } from "@/lib/api";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import type {
  AllocationCategory,
  AllocationSymbol,
  EquityPoint,
  Metrics,
  PnlBySymbolRow,
  ReturnsBin,
} from "@/lib/types";

const PIE_COLORS = ["#22c55e", "#38bdf8", "#a78bfa", "#f59e0b", "#f43f5e", "#facc15", "#34d399"];

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
  const [timeframe, setTimeframe] = useState<Timeframe>("3M");
  const lastAutoRefresh = useDashboardAutoRefresh();

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

  const distributionData = useMemo(() => {
    if (!distribution.data) return [];
    const fmt = (v: number) =>
      formatNumber(v, { maximumFractionDigits: 1, minimumFractionDigits: 1 });
    return distribution.data.bins.map((b) => ({
      // Asse X: usiamo solo l'estremo superiore del bin, così le etichette
      // restano leggibili anche con valori negativi. Il range completo finisce
      // nella label del tooltip ("rangeLabel").
      label: `${fmt(b.hi)}%`,
      rangeLabel: `${fmt(b.lo)}% / ${fmt(b.hi)}%`,
      count: b.count,
      negative: b.hi <= 0,
    }));
  }, [distribution.data]);

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
                  <span className="font-medium">{fxRate.data.rate.toFixed(4)}</span>{" "}
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

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-6">
        <Kpi
          title="PnL totale"
          value={formatCurrency(m?.total_pnl_abs, m?.currency ?? "EUR")}
          accent={(m?.total_pnl_abs ?? 0) >= 0 ? "positive" : "negative"}
          subtitle={formatPercent(m?.total_pnl_pct)}
        />
        <Kpi title="Win rate" value={formatPercent((m?.win_rate ?? 0) * 100)} />
        <Kpi title="Profit factor" value={formatNumber(m?.profit_factor, { maximumFractionDigits: 2 })} />
        <Kpi title="Max drawdown" value={formatCurrency(m?.max_drawdown, m?.currency ?? "EUR")} accent="negative" />
        <Kpi title="Sharpe" value={formatNumber(m?.sharpe, { maximumFractionDigits: 2 })} />
        <Kpi title="Equity account" value={formatCurrency(m?.account_equity, m?.currency ?? "EUR")} />
        <Kpi title="Avg win" value={formatCurrency(m?.avg_win, m?.currency ?? "EUR")} accent="positive" />
        <Kpi title="Avg loss" value={formatCurrency(m?.avg_loss, m?.currency ?? "EUR")} accent="negative" />
        <Kpi title="# Trade" value={m ? formatNumber(m.n_trades, { maximumFractionDigits: 0 }) : "—"} />
        <Kpi title="# Aperti" value={m ? formatNumber(m.n_open, { maximumFractionDigits: 0 }) : "—"} />
        <Kpi title="# Pending" value={m ? formatNumber(m.n_pending, { maximumFractionDigits: 0 }) : "—"} />
      </div>

      <EquityBalanceChart fallbackCurrency={m?.currency ?? "EUR"} />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Equity curve (PnL realizzato cumulato)</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer>
              <LineChart data={equity.data?.points ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="t" stroke="#94a3b8" fontSize={12} tickMargin={8} />
                <YAxis stroke="#94a3b8" fontSize={12} tickFormatter={(v) => formatCurrency(v, m?.currency ?? "EUR")} width={80} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }}
                  formatter={(v: number) => formatCurrency(v, m?.currency ?? "EUR")}
                />
                <Line
                  type="monotone"
                  dataKey="equity"
                  stroke="#22c55e"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Allocazione aperta per categoria</CardTitle>
          </CardHeader>
          <CardContent className="flex h-72 flex-col">
            <div className="flex-1">
              <ResponsiveContainer>
                <PieChart>
                  <Pie
                    data={allocation.data?.by_category ?? []}
                    dataKey="value"
                    nameKey="category"
                    innerRadius={50}
                    outerRadius={90}
                    paddingAngle={2}
                    labelLine={false}
                    label={(props: {
                      cx: number;
                      cy: number;
                      midAngle: number;
                      innerRadius: number;
                      outerRadius: number;
                      percent?: number;
                    }) => {
                      const pct = props.percent ?? 0;
                      if (pct < 0.05) return null;
                      const RADIAN = Math.PI / 180;
                      const r = props.innerRadius + (props.outerRadius - props.innerRadius) / 2;
                      const x = props.cx + r * Math.cos(-props.midAngle * RADIAN);
                      const y = props.cy + r * Math.sin(-props.midAngle * RADIAN);
                      return (
                        <text
                          x={x}
                          y={y}
                          fill="#0f172a"
                          textAnchor="middle"
                          dominantBaseline="central"
                          fontSize={12}
                          fontWeight={600}
                        >
                          {`${(pct * 100).toFixed(1)}%`}
                        </text>
                      );
                    }}
                  >
                    {(allocation.data?.by_category ?? []).map((_, idx) => (
                      <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: "#0f172a",
                      border: "1px solid #1f2937",
                      borderRadius: 8,
                      color: "#e2e8f0",
                    }}
                    labelStyle={{ color: "#94a3b8" }}
                    itemStyle={{ color: "#e2e8f0" }}
                    formatter={(v: number, _name, item) => {
                      const total = (allocation.data?.by_category ?? []).reduce(
                        (sum, c) => sum + c.value,
                        0
                      );
                      const pct = total > 0 ? (v / total) * 100 : 0;
                      return [
                        `${formatCurrency(v, m?.currency ?? "EUR")} (${pct.toFixed(1)}%)`,
                        (item as { name?: string })?.name ?? "",
                      ];
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <AllocationLegend
              items={allocation.data?.by_category ?? []}
              currency={m?.currency ?? "EUR"}
            />
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>PnL per simbolo</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer>
              <BarChart data={pnlBySymbol.data?.items ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="symbol" stroke="#94a3b8" fontSize={12} />
                <YAxis stroke="#94a3b8" fontSize={12} tickFormatter={(v) => formatCurrency(v, m?.currency ?? "EUR")} width={80} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1f2937", borderRadius: 8 }}
                  labelStyle={{ color: "#e2e8f0" }}
                  itemStyle={{ color: "#e2e8f0" }}
                  formatter={(v: number) => {
                    const color = v < 0 ? "#f43f5e" : v > 0 ? "#22c55e" : "#e2e8f0";
                    return [
                      <span key="pnl" style={{ color, fontWeight: 600 }}>
                        {formatCurrency(v, m?.currency ?? "EUR")}
                      </span>,
                      "PnL",
                    ];
                  }}
                />
                <Bar dataKey="pnl_abs" name="PnL">
                  {(pnlBySymbol.data?.items ?? []).map((entry, idx) => (
                    <Cell key={idx} fill={entry.pnl_abs < 0 ? "#f43f5e" : "#22c55e"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Distribuzione dei rendimenti (%)</CardTitle>
          </CardHeader>
          <CardContent className="h-72">
            <ResponsiveContainer>
              <BarChart data={distributionData} margin={{ top: 10, right: 10, left: 0, bottom: 24 }}>
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
      </div>

    </section>
  );
}

function AllocationLegend({
  items,
  currency,
}: {
  items: AllocationCategory[];
  currency: string;
}) {
  if (items.length === 0) return null;
  const total = items.reduce((sum, c) => sum + c.value, 0);
  return (
    <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {items.map((item, idx) => {
        const pct = total > 0 ? (item.value / total) * 100 : 0;
        return (
          <li key={item.category} className="flex items-center gap-2 truncate">
            <span
              className="inline-block size-2.5 shrink-0 rounded-full"
              style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }}
            />
            <span className="truncate text-(--color-text)">{item.category}</span>
            <span className="ml-auto text-(--color-muted)">
              {formatCurrency(item.value, currency)} · {pct.toFixed(1)}%
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function Kpi({
  title,
  value,
  subtitle,
  accent,
}: {
  title: string;
  value: string;
  subtitle?: string;
  accent?: "positive" | "negative";
}) {
  const tone =
    accent === "positive"
      ? "text-emerald-400"
      : accent === "negative"
      ? "text-rose-400"
      : "text-(--color-text)";
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wide text-(--color-muted)">{title}</p>
      <p className={`mt-1 text-xl font-semibold ${tone}`}>{value}</p>
      {subtitle && <p className="mt-1 text-xs text-(--color-muted)">{subtitle}</p>}
    </Card>
  );
}
