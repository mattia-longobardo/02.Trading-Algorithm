"use client";

import Link from "next/link";
import { ArrowRightIcon, Trash2Icon } from "lucide-react";

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
import { Card, CardContent } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EnvBadge } from "@/components/site-header";
import { PageHeader } from "@/components/page-header";
import { ErrorState, TableSkeleton } from "@/components/query-states";
import { useDeleteRun, useRuns } from "@/lib/queries";
import { useDisplay } from "@/lib/money";

export default function RunsPage() {
  const { data, isLoading, error } = useRuns(50);
  const deleteRun = useDeleteRun();
  const d = useDisplay();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Journal"
        title="Run"
        description="Esito sintetico della pipeline: candidati, ordini proposti, approvati, respinti ed eseguiti."
      />
      <Card>
        <CardContent>
          {isLoading ? (
            <TableSkeleton rows={10} />
          ) : error ? (
            <ErrorState error={error} />
          ) : (data?.runs.length ?? 0) === 0 ? (
            <p className="text-muted-foreground py-10 text-center text-sm">
              Nessuna run ancora — avvia la prima dalla Dashboard
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Avvio</TableHead>
                  <TableHead>Ambiente</TableHead>
                  <TableHead className="text-right">Candidati</TableHead>
                  <TableHead className="text-right">Proposti</TableHead>
                  <TableHead className="text-right">Approvati</TableHead>
                  <TableHead className="text-right">Respinti</TableHead>
                  <TableHead className="text-right">Eseguiti</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data!.runs.map((run) => (
                  <TableRow key={run.run_id}>
                    <TableCell className="font-mono text-[13px] whitespace-nowrap tabular-nums">
                      {d.dateTime(run.started_at)}
                    </TableCell>
                    <TableCell>
                      <EnvBadge environment={run.environment} />
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {run.summary?.candidates ?? "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {run.summary?.proposed ?? "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {run.summary?.approved ?? "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono tabular-nums">
                      {run.summary?.rejected ?? "—"}
                    </TableCell>
                    <TableCell className="text-right font-mono font-medium tabular-nums">
                      {run.summary?.executed ?? "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="sm" asChild>
                          <Link href={`/runs/${run.run_id}`}>
                            Dettaglio <ArrowRightIcon className="size-3.5" />
                          </Link>
                        </Button>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon-sm"
                              aria-label="Elimina run"
                              // Solo la riga in cancellazione si disabilita: le altre restano usabili.
                              disabled={
                                deleteRun.isPending &&
                                deleteRun.variables === run.run_id
                              }
                            >
                              <Trash2Icon aria-hidden="true" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>
                                Eliminare la run?
                              </AlertDialogTitle>
                              <AlertDialogDescription>
                                L&apos;operazione è irreversibile e cancella
                                anche le decisioni e le esecuzioni collegate.
                                Le posizioni già aperte su eToro non vengono
                                toccate.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Annulla</AlertDialogCancel>
                              <AlertDialogAction
                                variant="destructive"
                                disabled={deleteRun.isPending}
                                onClick={() => deleteRun.mutate(run.run_id)}
                              >
                                <Trash2Icon
                                  data-icon="inline-start"
                                  aria-hidden="true"
                                />
                                Elimina run
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
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
