"use client";

import * as React from "react";
import { SearchIcon, XIcon } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader } from "@/components/page-header";
import { ErrorState, TableSkeleton } from "@/components/query-states";
import { Stamp } from "@/components/stamp";
import { MultiStatusFilter } from "@/components/multi-status-filter";
import { useCancelExecution, useCloseTrade, useTrades } from "@/lib/queries";
import { useDisplay } from "@/lib/money";

const toneForStatus = (status: string) => {
  if (status === "open" || status === "filled") return "approved" as const;
  if (status === "pending") return "caution" as const;
  if (status === "failed" || status === "rejected") return "rejected" as const;
  return "neutral" as const;
};

export default function TradesPage() {
  const [statuses, setStatuses] = React.useState<string[]>([]);
  const [search, setSearch] = React.useState("");
  const trades = useTrades(statuses, search);
  const closeTrade = useCloseTrade();
  const cancelExecution = useCancelExecution();
  const d = useDisplay();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Operatività"
        title="Trade"
        description="Posizioni aperte e ordini da eseguire, con ricerca, filtri e azioni controllate."
      />

      <Card>
        <CardHeader>
          <CardTitle>Registro operativo</CardTitle>
          <CardDescription>{trades.data?.trades.length ?? 0} elementi visibili</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
            <div className="relative">
              <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" aria-hidden="true" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Cerca simbolo"
                aria-label="Cerca trade per simbolo"
                className="pl-9"
              />
            </div>
            <MultiStatusFilter value={statuses} onChange={setStatuses} options={[
              { value: "open", label: "Aperti" }, { value: "pending", label: "Da aprire" },
              { value: "filled", label: "Eseguiti" }, { value: "failed", label: "Falliti" },
              { value: "rejected", label: "Respinti" }, { value: "cancelled", label: "Annullati" },
            ]} />
          </div>

          {trades.isLoading ? <TableSkeleton rows={8} /> : trades.error ? (
            <ErrorState error={trades.error} />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Simbolo</TableHead><TableHead>Stato</TableHead><TableHead>Lato</TableHead>
                  <TableHead className="text-right">Importo</TableHead><TableHead className="text-right">Prezzo</TableHead>
                  <TableHead>Data / ora</TableHead><TableHead>Dettaglio</TableHead><TableHead className="text-right">Azioni</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(trades.data?.trades ?? []).map((trade) => (
                  <TableRow key={trade.id}>
                    <TableCell className="font-mono font-medium">{trade.symbol}</TableCell>
                    <TableCell><Stamp tone={toneForStatus(trade.status)}>{trade.status}</Stamp></TableCell>
                    <TableCell className="font-mono text-xs uppercase">{trade.side}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{d.money(trade.amount_usd)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{d.money(trade.entry_price)}</TableCell>
                    <TableCell className="font-mono text-xs whitespace-nowrap tabular-nums">{d.dateTime(trade.created_at)}</TableCell>
                    <TableCell className="text-muted-foreground max-w-56 truncate text-xs">{trade.detail ?? "n/d"}</TableCell>
                    <TableCell className="text-right">
                      {trade.can_close && trade.position_id ? (
                        <AlertDialog>
                          <AlertDialogTrigger asChild><Button variant="outline" size="sm">Chiudi</Button></AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader><AlertDialogTitle>Chiudere {trade.symbol}?</AlertDialogTitle>
                              <AlertDialogDescription>Verrà inviato a eToro un ordine di chiusura totale a mercato. L’operazione muove denaro nel conto configurato.</AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter><AlertDialogCancel>Annulla</AlertDialogCancel>
                              <AlertDialogAction onClick={() => closeTrade.mutate(trade.position_id!)}>Chiudi posizione</AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      ) : trade.can_cancel && trade.execution_id ? (
                        <Button variant="outline" size="sm" onClick={() => cancelExecution.mutate(trade.execution_id!)}>
                          <XIcon data-icon="inline-start" aria-hidden="true" />Annulla
                        </Button>
                      ) : <span className="text-muted-foreground text-xs">—</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
