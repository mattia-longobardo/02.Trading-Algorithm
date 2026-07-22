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
import { EnvBadge } from "@/components/site-header";
import {
  MobileField,
  MobileFields,
  MobileItem,
  MobileItemHeader,
  MobileList,
} from "@/components/mobile-list";
import { RunFunnel, type FunnelStep } from "@/components/runs/run-funnel";
import {
  AnalystSection,
  AnomalySection,
  DebateSection,
  OrdersSection,
  RiskSection,
} from "@/components/runs/stage-views";
import { ExecutionStatusBadge, SideBadge } from "@/components/status-badges";
import { ErrorState, TableSkeleton } from "@/components/query-states";
import { useDeleteRun, useExecutions, useRunDecisions } from "@/lib/queries";
import { useDisplay } from "@/lib/money";
import { countVerdicts, describeRun } from "@/lib/run-outcome";
import type { Decision, DecisionStage } from "@/lib/types";

/**
 * Le cinque fasi in ordine di pipeline. `emptyHint` spiega in italiano perché
 * una fase può essere vuota: una sezione senza elementi non è un bug, è il
 * racconto di dove la catena si è interrotta.
 */
const STAGE_META: {
  stage: DecisionStage;
  title: string;
  description: string;
  emptyHint: string;
  icon: React.ComponentType<{ className?: string }>;
  render: (decisions: Decision[]) => React.ReactNode;
}[] = [
  {
    stage: "analyst",
    title: "Cosa dicono gli analisti",
    description:
      "Quattro punti di vista indipendenti su ogni candidato — fondamentale, tecnico, sentiment e macro — con punteggio da −1 (negativo) a +1 (positivo).",
    emptyHint:
      "Nessun report: senza candidati dallo screener gli analisti non vengono nemmeno interpellati.",
    icon: BrainCircuitIcon,
    render: (decisions) => <AnalystSection decisions={decisions} />,
  },
  {
    stage: "debate",
    title: "Il dibattito e il verdetto",
    description:
      "Per ogni candidato un rialzista e un ribassista si confrontano; poi un giudice decide. Apre solo quando il caso rialzista è nettamente più forte.",
    emptyHint: "Nessun verdetto emesso in questa run.",
    icon: MessagesSquareIcon,
    render: (decisions) => <DebateSection decisions={decisions} />,
  },
  {
    stage: "portfolio",
    title: "Ordini proposti",
    description:
      "Il portfolio manager traduce in ordini solo i verdetti «apri long» e «chiudi». L'importo lo calcola il codice, in proporzione alla convinzione.",
    emptyHint:
      "Nessun ordine proposto: al portfolio manager arrivano solo i verdetti «apri long» o «chiudi»: se il debate ha risposto «evita» a tutti, qui non c'è nulla da valutare.",
    icon: ScaleIcon,
    render: (decisions) => <OrdersSection decisions={decisions} />,
  },
  {
    stage: "risk",
    title: "Risk gate",
    description:
      "Controlli deterministici, senza LLM: ogni ordine è approvato o respinto con la motivazione esatta del limite violato.",
    emptyHint: "Nessun ordine da controllare: il risk gate non è stato attivato.",
    icon: ShieldCheckIcon,
    render: (decisions) => <RiskSection decisions={decisions} />,
  },
  {
    stage: "reconcile_anomaly",
    title: "Anomalie di riconciliazione",
    description:
      "Posizioni presenti nel registro del bot ma sparite dal conto eToro: sono state chiuse fuori dal bot.",
    emptyHint: "",
    icon: TriangleAlertIcon,
    render: (decisions) => <AnomalySection decisions={decisions} />,
  },
];

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
  const display = useDisplay();

  const executions = (execData?.executions ?? []).filter(
    (execution) => execution.run_id === id,
  );

  const decisions = React.useMemo(() => data?.decisions ?? [], [data]);

  const byStage = React.useMemo(() => {
    const map = new Map<DecisionStage, Decision[]>();
    for (const decision of decisions) {
      const list = map.get(decision.stage) ?? [];
      list.push(decision);
      map.set(decision.stage, list);
    }
    return map;
  }, [decisions]);

  const run = data?.run;
  const summary = run?.summary ?? null;
  const verdicts = React.useMemo(() => countVerdicts(decisions), [decisions]);
  const outcome = describeRun(summary, verdicts);

  const candidateCount =
    summary?.candidates ??
    new Set(
      decisions.filter((x) => x.stage === "analyst").map((x) => x.symbol),
    ).size;

  const steps: FunnelStep[] = [
    {
      label: "Candidati",
      value: candidateCount,
      hint: "Simboli della watchlist selezionati dallo screener",
    },
    {
      label: "Verdetti",
      value: verdicts.total,
      hint: "Candidati arrivati fino al giudice del dibattito",
    },
    {
      label: "Operativi",
      value: verdicts.openLong + verdicts.close,
      hint: "Verdetti «apri long» o «chiudi»: gli unici che il portfolio manager può usare",
    },
    {
      label: "Proposti",
      value: summary?.proposed ?? (byStage.get("portfolio")?.length ?? 0),
      hint: "Ordini scritti dal portfolio manager",
    },
    {
      label: "Approvati",
      value: summary?.approved ?? 0,
      hint: "Ordini che hanno superato il risk gate",
    },
    {
      label: "Eseguiti",
      value: summary?.executed ?? 0,
      hint: "Ordini realmente inviati a eToro e riempiti",
    },
  ];

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
        title={
          run ? `Run del ${display.dateTime(run.started_at)}` : "Dettaglio run"
        }
        description={
          <span className="flex flex-wrap items-center gap-2">
            {run ? <EnvBadge environment={run.environment} /> : null}
            <span className="text-muted-foreground/70 font-mono text-[11px]">
              {id}
            </span>
          </span>
        }
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
          {/* Com'è andata: la risposta prima del dettaglio. */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Com&apos;è andata
                <Stamp tone={outcome.tone}>{outcome.label}</Stamp>
              </CardTitle>
              <CardDescription>{outcome.headline}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="overflow-x-auto pb-1">
                <RunFunnel steps={steps} />
              </div>
              {summary?.errors?.length ? (
                <div className="border-caution/40 bg-caution/5 space-y-1 rounded-md border p-3">
                  <p className="text-caution font-mono text-[10px] tracking-[0.08em] uppercase">
                    Errori non bloccanti — {summary.errors.length}
                  </p>
                  <ul className="space-y-1">
                    {summary.errors.map((message, i) => (
                      <li key={i} className="text-[13px] leading-relaxed">
                        {message}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </CardContent>
          </Card>

          {STAGE_META.map(
            ({ stage, title, description, emptyHint, icon: Icon, render }) => {
              const stageDecisions = byStage.get(stage) ?? [];
              if (stage === "reconcile_anomaly" && stageDecisions.length === 0) {
                return null; // sezione visibile solo se ci sono anomalie
              }
              return (
                <Card key={stage}>
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Icon className="text-muted-foreground size-4" />
                      {title}
                      <Stamp tone="neutral" className="ml-1 tabular-nums">
                        {stageDecisions.length}
                      </Stamp>
                    </CardTitle>
                    <CardDescription>{description}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    {stageDecisions.length === 0 ? (
                      <p className="text-muted-foreground text-sm">
                        {emptyHint}
                      </p>
                    ) : (
                      render(stageDecisions)
                    )}
                  </CardContent>
                </Card>
              );
            },
          )}

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
                  Nessun ordine è arrivato all&apos;executor: in questa run non è
                  stato mosso denaro.
                </p>
              ) : (
                <>
                <div className="max-md:hidden">
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
                    {executions.map((execution) => (
                      <TableRow key={execution.id}>
                        <TableCell className="font-mono text-[13px] whitespace-nowrap tabular-nums">
                          {display.dateTime(execution.created_at)}
                        </TableCell>
                        <TableCell className="font-mono font-medium">
                          {execution.symbol}
                        </TableCell>
                        <TableCell>
                          <SideBadge side={execution.side} />
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {display.money(execution.amount_usd)}
                        </TableCell>
                        <TableCell className="text-right font-mono tabular-nums">
                          {display.money(execution.execution_price)}
                        </TableCell>
                        <TableCell>
                          <ExecutionStatusBadge status={execution.status} />
                        </TableCell>
                        <TableCell className="text-muted-foreground max-w-64 truncate text-xs">
                          {execution.detail ?? "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                </div>
                <MobileList>
                  {executions.map((execution) => (
                    <MobileItem key={execution.id}>
                      <MobileItemHeader>
                        <span className="font-mono text-sm font-medium">
                          {execution.symbol}
                        </span>
                        <span className="flex items-center gap-1.5">
                          <SideBadge side={execution.side} />
                          <ExecutionStatusBadge status={execution.status} />
                        </span>
                      </MobileItemHeader>
                      <MobileFields>
                        <MobileField label="Importo">
                          <span className="font-mono tabular-nums">
                            {display.money(execution.amount_usd)}
                          </span>
                        </MobileField>
                        <MobileField label="Prezzo">
                          <span className="font-mono tabular-nums">
                            {display.money(execution.execution_price)}
                          </span>
                        </MobileField>
                        <MobileField label="Data" wide>
                          <span className="font-mono text-xs tabular-nums">
                            {display.dateTime(execution.created_at)}
                          </span>
                        </MobileField>
                        {execution.detail ? (
                          <MobileField label="Dettaglio" wide>
                            <span className="text-muted-foreground text-xs">
                              {execution.detail}
                            </span>
                          </MobileField>
                        ) : null}
                      </MobileFields>
                    </MobileItem>
                  ))}
                </MobileList>
                </>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
