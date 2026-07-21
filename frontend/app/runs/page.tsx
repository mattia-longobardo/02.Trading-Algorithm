"use client";

import Link from "next/link";
import {
  ArrowRightIcon,
  LayoutDashboardIcon,
  Trash2Icon,
  TriangleAlertIcon,
} from "lucide-react";

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
import { Stamp } from "@/components/stamp";
import { ErrorState, TableSkeleton } from "@/components/query-states";
import { useDeleteRun, useRuns } from "@/lib/queries";
import { useDisplay } from "@/lib/money";
import { describeRun } from "@/lib/run-outcome";
import type { RunSummary } from "@/lib/types";

/** Catena compatta candidati → proposti → approvati → eseguiti. */
function Chain({ summary }: { summary: RunSummary | null }) {
  if (!summary) return <span className="text-muted-foreground">—</span>;
  const steps = [
    { label: "candidati", value: summary.candidates },
    { label: "proposti", value: summary.proposed },
    { label: "approvati", value: summary.approved },
    { label: "eseguiti", value: summary.executed },
  ];
  return (
    <span className="inline-flex items-center gap-1 font-mono text-[12px] tabular-nums">
      {steps.map((step, i) => (
        <span key={step.label} className="inline-flex items-center gap-1">
          <span
            title={step.label}
            className={step.value === 0 ? "text-muted-foreground/50" : ""}
          >
            {step.value}
          </span>
          {i < steps.length - 1 ? (
            <span aria-hidden className="text-muted-foreground/40">
              ›
            </span>
          ) : null}
        </span>
      ))}
    </span>
  );
}

export default function RunsPage() {
  const { data, isLoading, error } = useRuns(50);
  const deleteRun = useDeleteRun();
  const d = useDisplay();

  return (
    <div className="space-y-6">
      {/* La sidebar non ha una voce "Run": il ritorno alla dashboard va
          esplicitato, altrimenti da questa pagina non si esce. */}
      <nav aria-label="Percorso">
        <Button variant="ghost" size="sm" asChild className="-ml-2.5">
          <Link href="/">
            <LayoutDashboardIcon data-icon="inline-start" aria-hidden="true" />
            Torna alla dashboard
          </Link>
        </Button>
      </nav>

      <PageHeader
        eyebrow="Journal"
        title="Run"
        description="Ogni riga è un giro completo della pipeline: dai candidati dello screener agli ordini realmente eseguiti. La colonna Esito dice dove si è fermata."
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
                  <TableHead>Esito</TableHead>
                  <TableHead>
                    <span title="candidati › proposti › approvati › eseguiti">
                      Percorso
                    </span>
                  </TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data!.runs.map((run) => {
                  const outcome = describeRun(run.summary);
                  const errors = run.summary?.errors?.length ?? 0;
                  return (
                    <TableRow key={run.run_id}>
                      <TableCell className="font-mono text-[13px] whitespace-nowrap tabular-nums">
                        {d.dateTime(run.started_at)}
                      </TableCell>
                      <TableCell>
                        <EnvBadge environment={run.environment} />
                      </TableCell>
                      <TableCell>
                        <span className="flex items-center gap-1.5">
                          <Stamp tone={outcome.tone}>{outcome.label}</Stamp>
                          {errors > 0 ? (
                            <span
                              title={`${errors} errori non bloccanti`}
                              className="text-caution inline-flex items-center gap-1 font-mono text-[10px] tabular-nums"
                            >
                              <TriangleAlertIcon
                                aria-hidden="true"
                                className="size-3"
                              />
                              {errors}
                            </span>
                          ) : null}
                        </span>
                      </TableCell>
                      <TableCell>
                        <Chain summary={run.summary} />
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
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
