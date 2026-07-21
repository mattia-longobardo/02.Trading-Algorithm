"use client";

import * as React from "react";
import { DownloadIcon, FileTextIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageHeader } from "@/components/page-header";
import { ErrorState, CardSkeleton } from "@/components/query-states";
import { useReports } from "@/lib/queries";
import { useDisplay } from "@/lib/money";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const labels = { weekly: "Settimanali", monthly: "Mensili", quarterly: "Trimestrali", semiannual: "Semestrali", annual: "Annuali" } as const;

export default function ReportsPage() {
  const query = useReports();
  const [selected, setSelected] = React.useState<string | null>(null);
  const [content, setContent] = React.useState("");
  const d = useDisplay();

  async function openReport(id: string) {
    setSelected(id);
    const response = await fetch(`/api/reports/${id}`);
    const data = (await response.json()) as { content: string };
    setContent(data.content);
  }

  const allReports = query.data?.reports ?? [];
  const latestByCadence = Object.keys(labels).map((cadence) =>
    allReports.find((report) => report.cadence === cadence),
  ).filter(Boolean);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow="Archivio server" title="Report" description="Report generati e salvati sul filesystem del server, ordinati per periodicità." />
      {query.isLoading ? <CardSkeleton className="h-80 w-full" /> : query.error ? <ErrorState error={query.error} /> : (
        <><div className="grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
          <Card><CardHeader><CardTitle>Report più recenti</CardTitle><CardDescription>Un report per ogni periodicità</CardDescription></CardHeader><CardContent className="flex flex-col gap-5">
            {Object.entries(labels).map(([cadence, label]) => {
              const report = latestByCadence.find((item) => item?.cadence === cadence);
              return <section key={cadence} className="flex flex-col gap-2"><h2 className="font-mono text-[10px] tracking-[0.16em] text-muted-foreground uppercase">{label}</h2>{report ? <button type="button" onClick={() => void openReport(report.id)} className="hover:bg-accent focus-visible:ring-ring flex w-full items-start gap-3 rounded-md border p-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"><FileTextIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" /><span className="min-w-0"><span className="block truncate text-sm font-medium">{report.name}</span><span className="text-muted-foreground mt-1 block font-mono text-[10px]">{d.dateTime(report.updated_at)}</span></span></button> : <p className="text-muted-foreground text-xs">Nessun report</p>}</section>;
            })}
          </CardContent></Card>
          <Card><CardHeader><CardTitle>{selected ? selected.split("/").at(-1)?.replace(/\.md$/, "") : "Anteprima report"}</CardTitle><CardDescription>{selected ? "File Markdown sul server" : "Seleziona un report dalla cartella"}</CardDescription></CardHeader><CardContent className="flex flex-col gap-4">{selected ? <><Button asChild variant="outline" size="sm" className="self-start"><a href={`/api/reports/${selected}?download=true`}><DownloadIcon data-icon="inline-start" aria-hidden="true" />Scarica file</a></Button><pre className="bg-muted max-h-[620px] overflow-auto rounded-md border p-5 font-mono text-xs leading-6 whitespace-pre-wrap">{content}</pre></> : <p className="text-muted-foreground py-20 text-center text-sm">Nessun report selezionato</p>}</CardContent></Card>
        </div>
        <Card>
          <CardHeader><CardTitle>Storico report</CardTitle><CardDescription>{allReports.length} file conservati sul server</CardDescription></CardHeader>
          <CardContent><Table><TableHeader><TableRow><TableHead>Report</TableHead><TableHead>Periodicità</TableHead><TableHead>Fine periodo</TableHead><TableHead>Aggiornato</TableHead><TableHead className="text-right">Dimensione</TableHead><TableHead className="text-right">Azioni</TableHead></TableRow></TableHeader>
            <TableBody>{allReports.map((report) => <TableRow key={report.id}><TableCell className="font-medium">{report.name}</TableCell><TableCell>{labels[report.cadence]}</TableCell><TableCell className="font-mono text-xs tabular-nums">{report.period_end}</TableCell><TableCell className="font-mono text-xs tabular-nums">{d.dateTime(report.updated_at)}</TableCell><TableCell className="text-right font-mono text-xs tabular-nums">{(report.size_bytes / 1024).toFixed(1)} KB</TableCell><TableCell className="text-right"><div className="inline-flex gap-1"><Button variant="ghost" size="sm" onClick={() => void openReport(report.id)}>Apri</Button><Button asChild variant="ghost" size="sm"><a href={`/api/reports/${report.id}?download=true`} aria-label={`Scarica ${report.name}`}><DownloadIcon aria-hidden="true" /></a></Button></div></TableCell></TableRow>)}</TableBody>
          </Table></CardContent>
        </Card></>
      )}
    </div>
  );
}
