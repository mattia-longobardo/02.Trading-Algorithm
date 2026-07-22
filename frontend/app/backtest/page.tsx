"use client";

import * as React from "react";
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type SortingState,
} from "@tanstack/react-table";
import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  InfoIcon,
  TriangleAlertIcon,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { EquityChart } from "@/components/charts/equity-chart";
import {
  MobileField,
  MobileFields,
  MobileItem,
  MobileItemHeader,
  MobileList,
} from "@/components/mobile-list";
import { PageHeader } from "@/components/page-header";
import { Select, SelectContent, SelectGroup, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { MonthlyHeatmap } from "@/components/monthly-heatmap";
import { CardSkeleton, ErrorState, TableSkeleton } from "@/components/query-states";
import {
  useBacktestSummary,
  useBacktestTrades,
  useEquityCurve,
  useMonthlyReturns,
} from "@/lib/queries";
import { fmtNum, fmtPct, fmtPctSigned, ND, pnlClass } from "@/lib/format";
import { useDisplay } from "@/lib/money";
import type { Display } from "@/lib/money";
import type { BacktestMetrics, ClosedTrade } from "@/lib/types";

interface MetricDef {
  key: keyof BacktestMetrics;
  label: string;
  definition: string;
  /** `d` serve solo alle metriche in valuta: le altre ignorano il parametro. */
  format: (v: number | null, d: Display) => string;
  signed?: boolean;
}

const METRICS: MetricDef[] = [
  {
    key: "total_return_pct",
    label: "Total return",
    definition: "Rendimento complessivo dell'equity curve del bot (TWR).",
    format: (v) => fmtPctSigned(v),
    signed: true,
  },
  {
    key: "cagr_pct",
    label: "CAGR",
    definition:
      "Tasso di crescita annuo composto: (1 + total return)^(1/anni) − 1.",
    format: (v) => fmtPctSigned(v),
    signed: true,
  },
  {
    key: "volatility_pct",
    label: "Volatilità annualizzata",
    definition:
      "Deviazione standard dei rendimenti giornalieri × √252.",
    format: (v) => fmtPct(v),
  },
  {
    key: "sharpe",
    label: "Sharpe ratio",
    definition:
      "(CAGR − risk-free) / volatilità. Risk-free configurabile (default T-bill 3M).",
    format: (v) => fmtNum(v),
  },
  {
    key: "sortino",
    label: "Sortino ratio",
    definition:
      "Come lo Sharpe, ma usa la downside deviation (solo rendimenti negativi).",
    format: (v) => fmtNum(v),
  },
  {
    key: "max_drawdown_pct",
    label: "Max drawdown",
    definition:
      "Massima perdita peak-to-trough sull'equity curve del bot.",
    format: (v) => fmtPct(v),
  },
  {
    key: "calmar",
    label: "Calmar ratio",
    definition: "CAGR / |max drawdown|.",
    format: (v) => fmtNum(v),
  },
  {
    key: "alpha",
    label: "Alpha vs SPY",
    definition:
      "Intercetta della regressione OLS dei rendimenti giornalieri bot vs SPY.",
    format: (v) => fmtNum(v, 3),
  },
  {
    key: "beta",
    label: "Beta vs SPY",
    definition:
      "Pendenza della regressione OLS: sensibilità del bot ai movimenti dell'S&P 500.",
    format: (v) => fmtNum(v),
  },
  {
    key: "information_ratio",
    label: "Information ratio",
    definition:
      "Media dell'excess return vs SPY / tracking error.",
    format: (v) => fmtNum(v),
  },
  {
    key: "win_rate_pct",
    label: "Win rate",
    definition: "Percentuale di trade chiusi con PnL realizzato > 0.",
    format: (v) => fmtPct(v),
  },
  {
    key: "profit_factor",
    label: "Profit factor",
    definition: "Somma dei profitti / |somma delle perdite|.",
    format: (v) => fmtNum(v),
  },
  {
    key: "recovery_factor",
    label: "Recovery factor",
    definition: "Net profit / |max drawdown|.",
    format: (v) => fmtNum(v),
  },
  {
    key: "expectancy_usd",
    label: "Expectancy",
    definition: "PnL medio per trade chiuso.",
    format: (v, d) => d.moneySigned(v),
    signed: true,
  },
  {
    key: "exposure_pct",
    label: "Exposure",
    definition:
      "Percentuale di giorni con almeno una posizione aperta.",
    format: (v) => fmtPct(v),
  },
];

function MetricsCard() {
  const { data, isLoading, error } = useBacktestSummary();
  const display = useDisplay();

  if (isLoading) return <CardSkeleton className="h-80 w-full" />;
  if (error || !data) return <ErrorState error={error} />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Metriche</CardTitle>
        <CardDescription>
          {data.n_closed_trades} trade chiusi · {data.n_days} giorni di dati
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {data.insufficient_sample || data.n_closed_trades < 30 ? (
          <div className="border-caution/50 bg-caution/10 flex items-start gap-2 rounded-md border p-3 text-sm">
            <TriangleAlertIcon className="text-caution mt-0.5 size-4 shrink-0" />
            <p>
              Campione insufficiente per conclusioni statistiche: con meno di 30
              trade chiusi ({data.n_closed_trades}) le metriche sono rumore.
            </p>
          </div>
        ) : null}
        {!data.annualization_available && (
          <p className="text-muted-foreground text-xs">
            Meno di 60 giorni di dati: le metriche annualizzate sono mostrate
            come &quot;{ND}&quot;.
          </p>
        )}
        <div className="grid gap-x-8 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">
          {METRICS.map((m) => {
            const value = data.metrics[m.key];
            return (
              <div
                key={m.key}
                className="border-border/60 flex items-center justify-between border-b py-2 text-sm last:border-0"
              >
                <span className="text-muted-foreground flex items-center gap-1">
                  {m.label}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <InfoIcon className="size-3.5 cursor-help opacity-60" />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-64">
                      {m.definition}
                    </TooltipContent>
                  </Tooltip>
                </span>
                <span
                  className={`font-mono font-medium tabular-nums ${m.signed ? pnlClass(value) : ""}`}
                >
                  {m.format(value, display)}
                </span>
              </div>
            );
          })}
        </div>
        <p className="text-muted-foreground text-xs">
          Osservazioni: {data.n_closed_trades} trade chiusi, {data.n_days}{" "}
          giorni. &quot;{ND}&quot; = metrica non calcolabile con i dati attuali.
        </p>
      </CardContent>
    </Card>
  );
}

function EquityCurveCard() {
  const [benchmark, setBenchmark] = React.useState("SPY");
  const { data, isLoading, error } = useEquityCurve(benchmark);

  if (isLoading) return <CardSkeleton className="h-96 w-full" />;
  if (error || !data) return <ErrorState error={error} />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Trading Bot vs benchmark</CardTitle>
        <CardDescription>
          Benchmark SPY in due viste: lump-sum (capitale investito il giorno
          della prima run) e cash-flow matched (stessi importi, stesse date del
          bot)
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Select value={benchmark} onValueChange={setBenchmark}>
          <SelectTrigger className="w-full sm:w-64" aria-label="Benchmark"><SelectValue /></SelectTrigger>
          <SelectContent><SelectGroup>
            <SelectItem value="SPY">S&amp;P 500 · SPY</SelectItem>
            <SelectItem value="QQQ">Nasdaq 100 · QQQ</SelectItem>
            <SelectItem value="DIA">Dow Jones · DIA</SelectItem>
            <SelectItem value="IWM">Russell 2000 · IWM</SelectItem>
            <SelectItem value="URTH">MSCI World · URTH</SelectItem>
            <SelectItem value="FEZ">Euro Stoxx 50 · FEZ</SelectItem>
          </SelectGroup></SelectContent>
        </Select>
        {data.points.length < 2 ? (
          <p className="text-muted-foreground py-10 text-center text-sm">
            Serie equity non ancora sufficiente per il grafico
          </p>
        ) : (
          <EquityChart points={data.points} benchmarkLabel={benchmark} />
        )}
        <p className="text-muted-foreground flex items-start gap-1.5 text-xs">
          <InfoIcon className="mt-0.5 size-3.5 shrink-0" />
          {data.note_dividends ||
            "Il prezzo di SPY non include i dividendi (~1,3–1,5%/anno di total return in più per il benchmark)."}
        </p>
      </CardContent>
    </Card>
  );
}

function MonthlyReturnsCard() {
  const { data, isLoading, error } = useMonthlyReturns();

  if (isLoading) return <CardSkeleton className="h-48 w-full" />;
  if (error || !data) return <ErrorState error={error} />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rendimenti mensili</CardTitle>
        <CardDescription>Heatmap mese × anno (%)</CardDescription>
      </CardHeader>
      <CardContent>
        <MonthlyHeatmap rows={data.rows} />
      </CardContent>
    </Card>
  );
}

const tradeCol = createColumnHelper<ClosedTrade>();

/* Le colonne dipendono da valuta e fuso: definite come factory perché l'hook
   può essere chiamato solo dentro il componente. */
const tradeColumns = (d: Display) => [
  tradeCol.accessor("symbol", {
    header: "Simbolo",
    cell: (info) => (
      <span className="font-mono font-medium">{info.getValue()}</span>
    ),
  }),
  tradeCol.accessor("amount_usd", {
    header: "Importo",
    cell: (info) => d.money(info.getValue()),
    meta: { align: "right" },
  }),
  tradeCol.accessor("entry_price", {
    header: "Entry",
    cell: (info) => d.money(info.getValue()),
    meta: { align: "right" },
  }),
  tradeCol.accessor("close_price", {
    header: "Chiusura",
    cell: (info) => d.money(info.getValue()),
    meta: { align: "right" },
  }),
  tradeCol.accessor("realized_pnl_usd", {
    header: "PnL",
    cell: (info) => (
      <span className={pnlClass(info.getValue())}>
        {d.moneySigned(info.getValue())}
      </span>
    ),
    meta: { align: "right" },
  }),
  tradeCol.accessor("opened_at", {
    header: "Aperto",
    cell: (info) => (
      <span className="font-mono text-[13px] whitespace-nowrap tabular-nums">
        {d.date(info.getValue())}
      </span>
    ),
  }),
  tradeCol.accessor("closed_at", {
    header: "Chiuso",
    cell: (info) => (
      <span className="font-mono text-[13px] whitespace-nowrap tabular-nums">
        {d.date(info.getValue())}
      </span>
    ),
  }),
  tradeCol.accessor("close_reason", {
    header: "Motivo",
    enableSorting: false,
    cell: (info) => (
      <span className="text-muted-foreground text-xs">
        {info.getValue() ?? "—"}
      </span>
    ),
  }),
];

function TradesTable({ trades }: { trades: ClosedTrade[] }) {
  const [sorting, setSorting] = React.useState<SortingState>([
    { id: "closed_at", desc: true },
  ]);
  const display = useDisplay();
  const columns = React.useMemo(() => tradeColumns(display), [display]);

  const table = useReactTable({
    data: trades,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <>
    <div className="max-md:hidden">
    <Table>
      <TableHeader>
        {table.getHeaderGroups().map((hg) => (
          <TableRow key={hg.id}>
            {hg.headers.map((header) => {
              const align = (
                header.column.columnDef.meta as { align?: string } | undefined
              )?.align;
              const sorted = header.column.getIsSorted();
              return (
                <TableHead
                  key={header.id}
                  className={align === "right" ? "text-right" : undefined}
                >
                  {header.column.getCanSort() ? (
                    <button
                      type="button"
                      className="hover:text-foreground inline-flex items-center gap-1"
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                      {sorted === "asc" ? (
                        <ArrowUpIcon className="size-3" />
                      ) : sorted === "desc" ? (
                        <ArrowDownIcon className="size-3" />
                      ) : (
                        <ArrowUpDownIcon className="size-3 opacity-40" />
                      )}
                    </button>
                  ) : (
                    flexRender(
                      header.column.columnDef.header,
                      header.getContext(),
                    )
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        ))}
      </TableHeader>
      <TableBody>
        {table.getRowModel().rows.map((row) => (
          <TableRow key={row.id}>
            {row.getVisibleCells().map((cell) => {
              const align = (
                cell.column.columnDef.meta as { align?: string } | undefined
              )?.align;
              return (
                <TableCell
                  key={cell.id}
                  className={
                    align === "right"
                      ? "text-right font-mono tabular-nums"
                      : undefined
                  }
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              );
            })}
          </TableRow>
        ))}
      </TableBody>
    </Table>
    </div>
    <MobileList>
      {table.getRowModel().rows.map((row) => {
        const t = row.original;
        return (
          <MobileItem key={row.id}>
            <MobileItemHeader>
              <span className="font-mono text-sm font-medium">{t.symbol}</span>
              <span className={`font-mono text-sm font-medium tabular-nums ${pnlClass(t.realized_pnl_usd)}`}>
                {display.moneySigned(t.realized_pnl_usd)}
              </span>
            </MobileItemHeader>
            <MobileFields>
              <MobileField label="Importo"><span className="font-mono tabular-nums">{display.money(t.amount_usd)}</span></MobileField>
              <MobileField label="Entry → chiusura">
                <span className="font-mono text-xs tabular-nums">
                  {display.money(t.entry_price)} → {display.money(t.close_price)}
                </span>
              </MobileField>
              <MobileField label="Aperto"><span className="font-mono text-xs tabular-nums">{display.date(t.opened_at)}</span></MobileField>
              <MobileField label="Chiuso"><span className="font-mono text-xs tabular-nums">{display.date(t.closed_at)}</span></MobileField>
              {t.close_reason ? (
                <MobileField label="Motivo" wide>
                  <span className="text-muted-foreground text-xs">{t.close_reason}</span>
                </MobileField>
              ) : null}
            </MobileFields>
          </MobileItem>
        );
      })}
    </MobileList>
    </>
  );
}

function TradesCard() {
  const { data, isLoading, error } = useBacktestTrades();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Trade chiusi</CardTitle>
        <CardDescription>
          Il track record reale del bot: il journal è il dataset. Colonne
          ordinabili.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <TableSkeleton rows={6} />
        ) : error || !data ? (
          <ErrorState error={error} />
        ) : data.trades.length === 0 ? (
          <p className="text-muted-foreground py-10 text-center text-sm">
            Nessun trade chiuso — il track record inizia con la prima chiusura
          </p>
        ) : (
          <TradesTable trades={data.trades} />
        )}
      </CardContent>
    </Card>
  );
}

export default function BacktestPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Track record"
        title="Benchmark"
        description="Andamento del Trading Bot e simulazione dello stesso capitale investito nell’S&P 500."
      />
      <EquityCurveCard />
      <MetricsCard />
      <div className="grid gap-4 xl:grid-cols-2">
        <MonthlyReturnsCard />
        <TradesCard />
      </div>
    </div>
  );
}
