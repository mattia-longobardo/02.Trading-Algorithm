"use client";

import * as React from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";
import { ErrorState, TableSkeleton } from "@/components/query-states";
import { Stamp } from "@/components/stamp";
import { DateRangeFilter, lastDaysRange } from "@/components/date-range-filter";
import { MultiStatusFilter } from "@/components/multi-status-filter";
import {
  MobileField,
  MobileFields,
  MobileItem,
  MobileItemHeader,
  MobileList,
} from "@/components/mobile-list";
import { useTradeHistory } from "@/lib/queries";
import { pnlClass } from "@/lib/format";
import { useDisplay } from "@/lib/money";

const statusTone = (status: string) =>
  status === "closed" || status === "open"
    ? ("approved" as const)
    : status === "failed" || status === "rejected"
      ? ("rejected" as const)
      : ("neutral" as const);

export default function HistoryPage() {
  const [range, setRange] = React.useState(() => lastDaysRange(90));
  const [statuses, setStatuses] = React.useState<string[]>([]);
  const [search, setSearch] = React.useState("");
  const history = useTradeHistory(statuses, range, search);
  const rows = history.data?.items ?? [];
  const d = useDisplay();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow="Archivio" title="Storico" description="Tutti i trade aperti, chiusi, annullati, falliti e respinti in ordine cronologico." actions={<DateRangeFilter value={range} onChange={setRange} />} />
      <Card>
        <CardHeader><CardTitle>Storico trade</CardTitle><CardDescription>{rows.length} risultati</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
            <Input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Cerca simbolo" aria-label="Cerca nello storico" />
            <MultiStatusFilter value={statuses} onChange={setStatuses} options={[
              { value: "open", label: "Aperti" }, { value: "closed", label: "Chiusi" },
              { value: "cancelled", label: "Annullati" }, { value: "failed", label: "Falliti" },
              { value: "rejected", label: "Respinti" }, { value: "filled", label: "Eseguiti" },
            ]} />
          </div>
          {history.isLoading ? <TableSkeleton rows={10} /> : history.error ? <ErrorState error={history.error} /> : (
            <>
            <div className="max-md:hidden">
            <Table><TableHeader><TableRow><TableHead>Simbolo</TableHead><TableHead>Stato</TableHead><TableHead>Lato</TableHead><TableHead className="text-right">Importo</TableHead><TableHead className="text-right">Prezzo</TableHead><TableHead className="text-right">PnL</TableHead><TableHead>Apertura</TableHead><TableHead>Chiusura</TableHead></TableRow></TableHeader>
              <TableBody>{rows.map((item) => <TableRow key={item.id}><TableCell className="font-mono font-medium">{item.symbol}</TableCell><TableCell><Stamp tone={statusTone(item.status)}>{item.status}</Stamp></TableCell><TableCell className="font-mono text-xs uppercase">{item.side}</TableCell><TableCell className="text-right font-mono tabular-nums">{d.money(item.amount_usd)}</TableCell><TableCell className="text-right font-mono tabular-nums">{d.money(item.price)}</TableCell><TableCell className={`text-right font-mono tabular-nums ${pnlClass(item.pnl_usd)}`}>{d.moneySigned(item.pnl_usd)}</TableCell><TableCell className="font-mono text-xs whitespace-nowrap">{d.dateTime(item.opened_at)}</TableCell><TableCell className="font-mono text-xs whitespace-nowrap">{item.closed_at ? d.dateTime(item.closed_at) : "—"}</TableCell></TableRow>)}</TableBody>
            </Table>
            </div>
            <MobileList>
              {rows.map((item) => (
                <MobileItem key={item.id}>
                  <MobileItemHeader>
                    <span className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium">{item.symbol}</span>
                      <span className="text-muted-foreground font-mono text-xs uppercase">{item.side}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      <span className={`font-mono text-sm font-medium tabular-nums ${pnlClass(item.pnl_usd)}`}>{d.moneySigned(item.pnl_usd)}</span>
                      <Stamp tone={statusTone(item.status)}>{item.status}</Stamp>
                    </span>
                  </MobileItemHeader>
                  <MobileFields>
                    <MobileField label="Importo"><span className="font-mono tabular-nums">{d.money(item.amount_usd)}</span></MobileField>
                    <MobileField label="Prezzo"><span className="font-mono tabular-nums">{d.money(item.price)}</span></MobileField>
                    <MobileField label="Apertura"><span className="font-mono text-xs tabular-nums">{d.dateTime(item.opened_at)}</span></MobileField>
                    <MobileField label="Chiusura"><span className="font-mono text-xs tabular-nums">{item.closed_at ? d.dateTime(item.closed_at) : "—"}</span></MobileField>
                  </MobileFields>
                </MobileItem>
              ))}
            </MobileList>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
