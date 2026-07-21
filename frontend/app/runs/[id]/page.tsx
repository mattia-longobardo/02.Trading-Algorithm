"use client";

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowLeftIcon,
  BrainCircuitIcon,
  LayoutDashboardIcon,
  MessagesSquareIcon,
  ScaleIcon,
  ShieldCheckIcon,
  Trash2Icon,
  TriangleAlertIcon,
  ZapIcon,
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
import { PageHeader } from "@/components/page-header";
import { Stamp } from "@/components/stamp";
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
import { JsonView } from "@/components/json-view";
import { ExecutionStatusBadge, SideBadge } from "@/components/status-badges";
import { ErrorState, TableSkeleton } from "@/components/query-states";
import { useDeleteRun, useExecutions, useRunDecisions } from "@/lib/queries";
import { useDisplay } from "@/lib/money";
import type { Decision, DecisionStage } from "@/lib/types";

const STAGE_META: {
  stage: DecisionStage;
  title: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
}[] = [
  {
    stage: "analyst",
    title: "Report analisti",
    description:
      "Fondamentale, tecnico, sentiment e macro — eseguiti in parallelo",
    icon: BrainCircuitIcon,
  },
  {
    stage: "debate",
    title: "Debate",
    description: "Bull vs bear per candidato, poi il verdetto del giudice",
    icon: MessagesSquareIcon,
  },
  {
    stage: "portfolio",
    title: "Portfolio manager",
    description: "Ordini proposti con size proporzionale alla conviction",
    icon: ScaleIcon,
  },
  {
    stage: "risk",
    title: "Risk gate",
    description:
      "Verdetti deterministici: approvati e respinti con motivazione",
    icon: ShieldCheckIcon,
  },
  {
    stage: "reconcile_anomaly",
    title: "Anomalie di riconciliazione",
    description: "Posizioni del registry non più presenti sul conto",
    icon: TriangleAlertIcon,
  },
];

function DecisionCard({ decision }: { decision: Decision }) {
  const d = useDisplay();
  return (
    <div className="rounded-md border p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Stamp tone="accent">{decision.symbol}</Stamp>
        <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
          {d.dateTime(decision.created_at)}
        </span>
      </div>
      <JsonView value={decision.payload} />
    </div>
  );
}

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = React.use(params);
  const router = useRouter();
  const { data, isLoading, error } = useRunDecisions(id);
  const { data: execData } = useExecutions(200);
  const deleteRun = useDeleteRun();
  const d = useDisplay();

  const executions = (execData?.executions ?? []).filter(
    (ex) => ex.run_id === id,
  );

  const byStage = new Map<DecisionStage, Decision[]>();
  for (const d of data?.decisions ?? []) {
    const list = byStage.get(d.stage) ?? [];
    list.push(d);
    byStage.set(d.stage, list);
  }

  // Dopo la cancellazione la run non esiste più: si torna all'elenco.
  const confirmDelete = () => {
    deleteRun.mutate(id, { onSuccess: () => router.push("/runs") });
  };

  return (
    <div className="space-y-4">
      {/* La sidebar non ha una voce "Run": il percorso di uscita — elenco e
          dashboard — va esplicitato qui sopra all'intestazione. */}
      <nav aria-label="Percorso" className="flex items-center gap-1">
        <Button variant="ghost" size="sm" asChild className="-ml-2.5">
          <Link href="/runs">
            <ArrowLeftIcon data-icon="inline-start" aria-hidden="true" />
            Elenco run
          </Link>
        </Button>
        <span aria-hidden="true" className="text-muted-foreground/60 text-xs">
          /
        </span>
        <Button variant="ghost" size="sm" asChild>
          <Link href="/">
            <LayoutDashboardIcon data-icon="inline-start" aria-hidden="true" />
            Dashboard
          </Link>
        </Button>
      </nav>

      <PageHeader
        eyebrow="Journal"
        title="Dettaglio run"
        description={<span className="font-mono text-xs">{id}</span>}
        actions={
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" disabled={deleteRun.isPending}>
                <Trash2Icon data-icon="inline-start" aria-hidden="true" />
                Elimina run
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Eliminare questa run?</AlertDialogTitle>
                <AlertDialogDescription>
                  L&apos;operazione è irreversibile e cancella anche le
                  decisioni e le esecuzioni collegate. Le posizioni già aperte
                  su eToro non vengono toccate.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Annulla</AlertDialogCancel>
                <AlertDialogAction
                  variant="destructive"
                  disabled={deleteRun.isPending}
                  onClick={confirmDelete}
                >
                  <Trash2Icon data-icon="inline-start" aria-hidden="true" />
                  Elimina run
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        }
      />

      {isLoading ? (
        <TableSkeleton rows={8} />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <div className="space-y-4">
          {STAGE_META.map(({ stage, title, description, icon: Icon }) => {
            const decisions = byStage.get(stage) ?? [];
            if (stage === "reconcile_anomaly" && decisions.length === 0) {
              return null; // sezione visibile solo se ci sono anomalie
            }
            return (
              <Card key={stage}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Icon className="text-muted-foreground size-4" />
                    {title}
                    <Stamp tone="neutral" className="ml-1 tabular-nums">
                      {decisions.length}
                    </Stamp>
                  </CardTitle>
                  <CardDescription>{description}</CardDescription>
                </CardHeader>
                <CardContent>
                  {decisions.length === 0 ? (
                    <p className="text-muted-foreground text-sm">
                      Nessun elemento per questa fase
                    </p>
                  ) : (
                    <div className="grid gap-3 lg:grid-cols-2">
                      {decisions.map((d) => (
                        <DecisionCard key={d.id} decision={d} />
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ZapIcon className="text-muted-foreground size-4" />
                Esecuzioni
                <Stamp tone="neutral" className="ml-1 tabular-nums">
                  {executions.length}
                </Stamp>
              </CardTitle>
              <CardDescription>
                L&apos;unico punto della pipeline che tocca denaro
              </CardDescription>
            </CardHeader>
            <CardContent>
              {executions.length === 0 ? (
                <p className="text-muted-foreground text-sm">
                  Nessuna esecuzione per questa run
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Data</TableHead>
                      <TableHead>Simbolo</TableHead>
                      <TableHead>Lato</TableHead>
                      <TableHead className="text-right">Importo</TableHead>
                      <TableHead className="text-right">Prezzo</TableHead>
                      <TableHead>Esito</TableHead>
                      <TableHead>Dettaglio</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {executions.map((ex) => (
                      <TableRow key={ex.id}>
                        <TableCell className="font-mono text-[13px] whitespace-nowrap tabular-nums">
                          {d.dateTime(ex.created_at)}
                        </TableCell>
                        <TableCell className="font-mono font-medium">
                          {ex.symbol}
                        </TableCell>
                        <TableCell>
                          <SideBadge side={ex.side} />
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {d.money(ex.amount_usd)}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {d.money(ex.execution_price)}
                        </TableCell>
                        <TableCell>
                          <ExecutionStatusBadge status={ex.status} />
                        </TableCell>
                        <TableCell className="text-muted-foreground max-w-64 truncate text-xs">
                          {ex.detail ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
