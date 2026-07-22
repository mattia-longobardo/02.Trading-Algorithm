"use client";

import { TriangleAlertIcon } from "lucide-react";

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
import { SectorDonut } from "@/components/charts/sector-donut";
import {
  MobileField,
  MobileFields,
  MobileItem,
  MobileItemHeader,
  MobileList,
} from "@/components/mobile-list";
import { PageHeader } from "@/components/page-header";
import { CardSkeleton, ErrorState, TableSkeleton } from "@/components/query-states";
import { usePortfolio } from "@/lib/queries";
import { fmtPctSigned, pnlClass } from "@/lib/format";
import { useDisplay } from "@/lib/money";

function SummaryTiles({
  cash,
  equity,
  exposure,
}: {
  cash: number;
  equity: number;
  exposure: number;
}) {
  const d = useDisplay();
  const tiles = [
    { label: "Equity bot", value: d.money(equity) },
    { label: "Liquidità", value: d.money(cash) },
    { label: "Esposizione", value: d.money(exposure) },
    {
      label: "Esposizione / equity",
      value: equity > 0 ? `${((exposure / equity) * 100).toFixed(1)}%` : "n/d",
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
      {tiles.map((t) => (
        <Card key={t.label} size="sm">
          <CardContent className="space-y-1">
            <p className="text-muted-foreground font-mono text-[10px] tracking-[0.14em] uppercase">
              {t.label}
            </p>
            <p className="font-mono text-xl font-semibold tracking-tight tabular-nums sm:text-2xl">
              {t.value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default function PortfolioPage() {
  const { data, isLoading, error } = usePortfolio();
  const d = useDisplay();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Registry bot"
        title="Portafoglio bot"
        description="Solo le posizioni aperte dal bot: i trade manuali sul conto eToro sono esclusi da tutte le metriche."
      />

      {isLoading ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <CardSkeleton key={i} className="h-24 w-full" />
            ))}
          </div>
          <TableSkeleton rows={6} />
        </>
      ) : error || !data ? (
        <ErrorState error={error} />
      ) : (
        <>
          <SummaryTiles
            cash={data.cash_usd}
            equity={data.equity_usd}
            exposure={data.exposure_usd}
          />

          {data.anomalies.length > 0 && (
            <Card className="border-caution/50">
              <CardHeader>
                <CardTitle className="text-caution flex items-center gap-2">
                  <TriangleAlertIcon className="size-4" />
                  Anomalie di riconciliazione
                </CardTitle>
                <CardDescription>
                  Posizioni del registry bot non più coerenti con il conto eToro
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2 text-sm">
                  {data.anomalies.map((a, i) => (
                    <li key={i} className="flex flex-wrap items-baseline gap-2">
                      <span className="font-mono font-medium">{a.symbol}</span>
                      <span className="text-muted-foreground">{a.detail}</span>
                      <span className="text-muted-foreground ml-auto font-mono text-xs tabular-nums">
                        {d.dateTime(a.detected_at)}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader>
                <CardTitle>Posizioni aperte</CardTitle>
                <CardDescription>
                  {data.positions.length} posizioni nel registry bot
                </CardDescription>
              </CardHeader>
              <CardContent>
                {data.positions.length === 0 ? (
                  <p className="text-muted-foreground py-10 text-center text-sm">
                    Nessuna posizione aperta dal bot — le aperture arrivano con
                    le run live
                  </p>
                ) : (
                  <>
                  <div className="max-md:hidden">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Simbolo</TableHead>
                        <TableHead>Settore</TableHead>
                        <TableHead className="text-right">Importo</TableHead>
                        <TableHead className="text-right">Entry</TableHead>
                        <TableHead className="text-right">Attuale</TableHead>
                        <TableHead className="text-right">PnL</TableHead>
                        <TableHead className="text-right">PnL %</TableHead>
                        <TableHead>Apertura</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {data.positions.map((p) => (
                        <TableRow key={String(p.etoro_position_id)}>
                          <TableCell className="font-mono font-medium">
                            {p.symbol}
                          </TableCell>
                          <TableCell className="text-muted-foreground">
                            {p.sector ?? "n/d"}
                          </TableCell>
                          <TableCell className="text-right font-mono tabular-nums">
                            {d.money(p.amount_usd)}
                          </TableCell>
                          <TableCell className="text-right font-mono tabular-nums">
                            {d.money(p.entry_price)}
                          </TableCell>
                          <TableCell className="text-right font-mono tabular-nums">
                            {d.money(p.current_price)}
                          </TableCell>
                          <TableCell
                            className={`text-right font-mono tabular-nums ${pnlClass(p.unrealized_pnl_usd)}`}
                          >
                            {d.moneySigned(p.unrealized_pnl_usd)}
                          </TableCell>
                          <TableCell
                            className={`text-right font-mono tabular-nums ${pnlClass(p.unrealized_pnl_pct)}`}
                          >
                            {fmtPctSigned(p.unrealized_pnl_pct)}
                          </TableCell>
                          <TableCell className="font-mono text-[13px] whitespace-nowrap tabular-nums">
                            {d.date(p.opened_at)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                  </div>
                  <MobileList>
                    {data.positions.map((p) => (
                      <MobileItem key={String(p.etoro_position_id)}>
                        <MobileItemHeader>
                          <span className="flex min-w-0 items-baseline gap-2">
                            <span className="font-mono text-sm font-medium">{p.symbol}</span>
                            <span className="text-muted-foreground truncate text-xs">{p.sector ?? "n/d"}</span>
                          </span>
                          <span className={`font-mono text-sm font-medium tabular-nums ${pnlClass(p.unrealized_pnl_usd)}`}>
                            {d.moneySigned(p.unrealized_pnl_usd)}
                            <span className="ml-1.5 text-xs">{fmtPctSigned(p.unrealized_pnl_pct)}</span>
                          </span>
                        </MobileItemHeader>
                        <MobileFields>
                          <MobileField label="Importo"><span className="font-mono tabular-nums">{d.money(p.amount_usd)}</span></MobileField>
                          <MobileField label="Apertura"><span className="font-mono text-xs tabular-nums">{d.date(p.opened_at)}</span></MobileField>
                          <MobileField label="Entry"><span className="font-mono tabular-nums">{d.money(p.entry_price)}</span></MobileField>
                          <MobileField label="Attuale"><span className="font-mono tabular-nums">{d.money(p.current_price)}</span></MobileField>
                        </MobileFields>
                      </MobileItem>
                    ))}
                  </MobileList>
                  </>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Allocazione per settore</CardTitle>
                <CardDescription>
                  Valore corrente delle posizioni bot
                </CardDescription>
              </CardHeader>
              <CardContent>
                <SectorDonut positions={data.positions} />
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
