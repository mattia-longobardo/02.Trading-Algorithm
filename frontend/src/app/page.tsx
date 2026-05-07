"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
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
import { Badge } from "@/components/ui/badge";
import { TimeframeSelector, type Timeframe } from "@/components/timeframe-selector";
import { api } from "@/lib/api";
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from "@/lib/format";
import type {
  AllocationCategory,
  AllocationSymbol,
  EquityPoint,
  Metrics,
  PnlBySymbolRow,
  ReturnsBin,
  Trade,
} from "@/lib/types";

const PIE_COLORS = ["#22c55e", "#38bdf8", "#a78bfa", "#f59e0b", "#f43f5e", "#facc15", "#34d399"];

export default function DashboardPage() {
  const [timeframe, setTimeframe] = useState<Timeframe>("3M");

  const metrics = useQuery({
    queryKey: ["metrics", timeframe],
    queryFn: () => api.get<Metrics>(`/api/metrics?window=${timeframe}`),
  });
  const equity = useQuery({
    queryKey: ["equity", timeframe],
    queryFn: () => api.get<{ points: EquityPoint[] }>(`/api/equity-curve?window=${timeframe}`),
  });
  const accountBalance = useQuery({
    queryKey: ["account-balance", timeframe],
    queryFn: () =>
      api.get<{ points: EquityPoint[]; currency: string }>(
        `/api/account-equity-curve?window=${timeframe}&granularity=hourly`
      ),
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
      api.get<{ by_category: AllocationCategory[]; by_symbol: AllocationSymbol[] }>("/api/allocation"),
  });
  const distribution = useQuery({
    queryKey: ["returns-distribution", timeframe],
    queryFn: () =>
      api.get<{ bins: ReturnsBin[] }>(`/api/returns-distribution?window=${timeframe}&bins=12`),
  });
  const trades = useQuery({
    queryKey: ["trades", "dashboard", timeframe],
    queryFn: () =>
      api.get<{ items: Trade[]; total: number; page: number; page_size: number }>(
        `/api/trades?page=1&page_size=25&sort=-created_at`
      ),
  });

  const m = metrics.data;

  const distributionData = useMemo(() => {
    if (!distribution.data) return [];
    return distribution.data.bins.map((b) => ({
      label: `${formatNumber(b.lo, { maximumFractionDigits: 1 })}…${formatNumber(b.hi, {
        maximumFractionDigits: 1,
      })}%`,
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
          </p>
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

      <Card>
        <CardHeader>
          <CardTitle>Andamento del saldo totale</CardTitle>
          <span className="text-xs text-(--color-muted)">
            Snapshot ogni 15&nbsp;min · valuta {accountBalance.data?.currency ?? m?.currency ?? "—"}
          </span>
        </CardHeader>
        <CardContent className="h-72">
          {(accountBalance.data?.points.length ?? 0) === 0 ? (
            <p className="text-sm text-(--color-muted)">
              Nessuno snapshot ancora registrato. Il primo arriverà entro 15 minuti
              dall&apos;avvio del bot.
            </p>
          ) : (
            <ResponsiveContainer>
              <LineChart data={accountBalance.data?.points ?? []}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="t" stroke="#94a3b8" fontSize={12} tickMargin={8} />
                <YAxis
                  stroke="#94a3b8"
                  fontSize={12}
                  tickFormatter={(v) =>
                    formatCurrency(v, accountBalance.data?.currency ?? m?.currency ?? "EUR")
                  }
                  width={90}
                  domain={["auto", "auto"]}
                />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }}
                  formatter={(v: number) =>
                    formatCurrency(v, accountBalance.data?.currency ?? m?.currency ?? "EUR")
                  }
                />
                <Line
                  type="monotone"
                  dataKey="equity"
                  stroke="#38bdf8"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>

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
          <CardContent className="h-72">
            <ResponsiveContainer>
              <PieChart>
                <Pie
                  data={allocation.data?.by_category ?? []}
                  dataKey="value"
                  nameKey="category"
                  innerRadius={50}
                  outerRadius={90}
                  paddingAngle={2}
                  label={(entry: AllocationCategory) => entry.category}
                >
                  {(allocation.data?.by_category ?? []).map((_, idx) => (
                    <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }}
                  formatter={(v: number) => formatCurrency(v)}
                />
              </PieChart>
            </ResponsiveContainer>
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
                  contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }}
                  formatter={(v: number) => formatCurrency(v, m?.currency ?? "EUR")}
                />
                <Bar dataKey="pnl_abs" fill="#22c55e" />
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
              <BarChart data={distributionData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} />
                <YAxis stroke="#94a3b8" fontSize={12} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1f2937" }} />
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

      <Card>
        <CardHeader>
          <CardTitle>Ultimi trade</CardTitle>
          <span className="text-xs text-(--color-muted)">Apri la console per modificare i parametri.</span>
        </CardHeader>
        <CardContent>
          <TradesTable
            items={trades.data?.items ?? []}
            loading={trades.isLoading}
            currency={m?.currency ?? "EUR"}
          />
        </CardContent>
      </Card>
    </section>
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

function TradesTable({
  items,
  loading,
  currency,
}: {
  items: Trade[];
  loading: boolean;
  currency: string;
}) {
  if (loading) {
    return <p className="text-sm text-(--color-muted)">Caricamento…</p>;
  }
  if (items.length === 0) {
    return <p className="text-sm text-(--color-muted)">Nessun trade nel periodo selezionato.</p>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] border-separate border-spacing-y-1 text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-(--color-muted)">
            <th className="px-3 py-2">Simbolo</th>
            <th className="px-3 py-2">Stato</th>
            <th className="px-3 py-2">Cat.</th>
            <th className="px-3 py-2 text-right">Entry</th>
            <th className="px-3 py-2 text-right">Qty</th>
            <th className="px-3 py-2 text-right">TP</th>
            <th className="px-3 py-2 text-right">SL</th>
            <th className="px-3 py-2 text-right">Prezzo</th>
            <th className="px-3 py-2 text-right">PnL</th>
            <th className="px-3 py-2">Aperto</th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => (
            <tr
              key={t.id}
              className="bg-slate-950/40 [&>td]:border-y [&>td]:border-(--color-line)"
            >
              <td className="px-3 py-2 font-medium first:rounded-l-lg">{t.symbol}</td>
              <td className="px-3 py-2">
                <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
              </td>
              <td className="px-3 py-2 text-(--color-muted)">{t.category}</td>
              <td className="px-3 py-2 text-right">{formatNumber(t.entry_price)}</td>
              <td className="px-3 py-2 text-right">{formatNumber(t.quantity)}</td>
              <td className="px-3 py-2 text-right">{formatNumber(t.take_profit)}</td>
              <td className="px-3 py-2 text-right">{formatNumber(t.stop_loss)}</td>
              <td className="px-3 py-2 text-right">{formatNumber(t.current_price)}</td>
              <td
                className={`px-3 py-2 text-right ${pnlClass(t.realized_pnl + t.unrealized_pnl)}`}
              >
                {formatCurrency(t.realized_pnl + t.unrealized_pnl, currency)}
              </td>
              <td className="px-3 py-2 text-(--color-muted) last:rounded-r-lg">
                {formatDateTime(t.open_timestamp ?? t.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function statusVariant(status: string): "open" | "pending" | "closed" | "cancelled" | "default" {
  switch (status) {
    case "OPEN":
      return "open";
    case "PENDING":
      return "pending";
    case "CLOSED":
      return "closed";
    case "CANCELLED":
      return "cancelled";
    default:
      return "default";
  }
}

function pnlClass(value: number): string {
  if (value > 0) return "text-emerald-400";
  if (value < 0) return "text-rose-400";
  return "text-(--color-text)";
}
