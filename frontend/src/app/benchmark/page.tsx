"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useMinuteRefresh } from "@/lib/use-minute-refresh";
import { DateRangePicker, type DateRange } from "@/components/dashboard/date-range-picker";
import { BenchmarkComparisonChart } from "@/components/benchmark/benchmark-comparison-chart";
import {
  CumulativeGainChart,
  type CumulativeGainPoint,
} from "@/components/benchmark/cumulative-gain-chart";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBanner } from "@/components/ui/status-banner";
import { api } from "@/lib/api";
import { formatCurrency, formatSignedPercent } from "@/lib/format";
import type { BenchmarkResponse } from "@/lib/types";

const BENCHMARK_QUERY_KEYS = ["benchmark"] as const;

function rangeToParams(range: DateRange): string {
  const params = new URLSearchParams();
  if (range.from) {
    const f = new Date(range.from);
    f.setHours(0, 0, 0, 0);
    params.set("from", f.toISOString());
  }
  if (range.to) {
    const t = new Date(range.to);
    t.setHours(23, 59, 59, 999);
    params.set("to", t.toISOString());
  }
  return params.toString();
}

function defaultRange(): DateRange {
  // Storico completo: il confronto parte da quando è partito il bot
  // (primo snapshot equity registrato).
  return { from: null, to: null };
}

function SummaryTile({
  title,
  pct,
  subtitle,
  loading,
}: {
  title: string;
  pct: number | null | undefined;
  subtitle?: string;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <Card className="p-3 sm:p-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-2 h-6 w-20" />
      </Card>
    );
  }
  const tone =
    pct == null
      ? "text-(--color-text)"
      : pct >= 0
      ? "text-(--color-accent)"
      : "text-(--color-danger)";
  return (
    <Card className="p-3 sm:p-4">
      <p className="text-xs uppercase text-(--color-muted)">{title}</p>
      <p className={`tnum mt-1 break-words text-xl font-semibold leading-tight tabular-nums ${tone}`}>
        {formatSignedPercent(pct)}
      </p>
      {subtitle && (
        <p className="tnum mt-1 break-words text-xs leading-tight tabular-nums text-(--color-muted)">
          {subtitle}
        </p>
      )}
    </Card>
  );
}

export default function BenchmarkPage() {
  const [range, setRange] = useState<DateRange>(() => defaultRange());
  const rangeQuery = rangeToParams(range);
  useMinuteRefresh(BENCHMARK_QUERY_KEYS);

  const benchmark = useQuery({
    queryKey: ["benchmark", rangeQuery],
    queryFn: () =>
      api.get<BenchmarkResponse>(`/api/benchmark${rangeQuery ? `?${rangeQuery}` : ""}`),
  });

  const data = benchmark.data;
  const summary = data?.summary ?? null;
  const currency = summary?.currency ?? "EUR";

  // Serie in valuta: guadagno/perdita cumulato del conto contro il guadagno
  // ipotetico dello stesso capitale iniziale investito nell'indice. Derivata
  // esattamente dalle serie % (pct/100 × capitale di partenza).
  const gainPoints = useMemo<CumulativeGainPoint[]>(() => {
    const base = summary?.portfolio_base;
    if (!data || base == null) return [];
    return data.points.map((p) => ({
      t: p.t,
      portfolio_eur:
        p.portfolio_pct != null ? Math.round(base * p.portfolio_pct) / 100 : null,
      benchmark_eur:
        p.benchmark_pct != null ? Math.round(base * p.benchmark_pct) / 100 : null,
    }));
  }, [data, summary]);

  const alphaEur =
    summary && summary.alpha_pct != null
      ? (summary.portfolio_base * summary.alpha_pct) / 100
      : null;

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="text-2xl font-semibold sm:text-3xl">Benchmark</h1>
          <p className="text-sm text-(--color-muted)">
            Quanto avresti guadagnato mettendo gli stessi soldi sull&apos;S&amp;P 500 invece
            che nel bot? Entrambe le serie partono da 0 alla prima data comune del
            periodo selezionato (default: da quando è partito il bot).
          </p>
        </div>
        <DateRangePicker
          value={range}
          onChange={setRange}
          className="w-full justify-center sm:w-auto"
        />
      </header>

      {benchmark.isError && (
        <StatusBanner kind="error">
          Impossibile caricare il confronto con il benchmark. Riprova o controlla la
          connessione al backend.
        </StatusBanner>
      )}

      {data?.benchmark.error && (
        <StatusBanner kind="warning">
          Serie S&amp;P 500 non disponibile ({data.benchmark.symbol}): il grafico mostra solo
          l&apos;andamento del conto. Dettaglio: {data.benchmark.error}
        </StatusBanner>
      )}

      <div className="grid grid-cols-1 gap-3 min-[430px]:grid-cols-3 md:gap-4">
        <SummaryTile
          title="Rendimento conto"
          pct={summary?.portfolio_pct}
          subtitle={
            summary
              ? `${formatCurrency(summary.portfolio_base, currency)} → ${formatCurrency(
                  summary.portfolio_latest,
                  currency
                )}`
              : undefined
          }
          loading={benchmark.isLoading}
        />
        <SummaryTile
          title="Rendimento S&P 500"
          pct={summary?.benchmark_pct}
          subtitle={data ? `Simbolo ${data.benchmark.symbol}` : undefined}
          loading={benchmark.isLoading}
        />
        <SummaryTile
          title="Alpha (conto − indice)"
          pct={summary?.alpha_pct}
          subtitle={
            alphaEur != null
              ? `${alphaEur >= 0 ? "+" : ""}${formatCurrency(alphaEur, currency)} rispetto all'indice`
              : "Extra-rendimento rispetto al benchmark"
          }
          loading={benchmark.isLoading}
        />
      </div>

      <CumulativeGainChart
        points={gainPoints}
        currency={currency}
        loading={benchmark.isLoading}
        error={benchmark.isError}
        benchmarkSymbol={data?.benchmark.symbol ?? "SPX500"}
      />

      <BenchmarkComparisonChart
        points={data?.points ?? []}
        loading={benchmark.isLoading}
        error={benchmark.isError}
        benchmarkSymbol={data?.benchmark.symbol ?? "SPX500"}
      />
    </section>
  );
}
