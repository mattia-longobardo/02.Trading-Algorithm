"use client";

import * as React from "react";
import { DatabaseIcon, DownloadIcon, FileIcon, PlusIcon, RssIcon, SaveIcon, Trash2Icon, UploadCloudIcon } from "lucide-react";
import { toast } from "sonner";

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
import { Input } from "@/components/ui/input";
import { CardSkeleton, ErrorState } from "@/components/query-states";
import {
  useFetchNews,
  useIngestDocument,
  useKnowledgeStatus,
  useUpdateRssFeeds,
} from "@/lib/queries";
import { fmtNum } from "@/lib/format";
import { useDisplay } from "@/lib/money";
import type { IngestResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt"];
const ACCEPTED_LABELS = ["PDF", "DOCX", "PPTX", "XLSX", "MD", "TXT"];

function isAcceptedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

function StatusCards() {
  const { data, isLoading, error } = useKnowledgeStatus();
  const display = useDisplay();
  const fetchNews = useFetchNews();
  const updateFeeds = useUpdateRssFeeds();
  const [feedOverride, setFeedOverride] = React.useState<string[] | null>(null);
  const feeds = feedOverride ?? data?.rss_feeds ?? [];
  const setFeeds = (update: (current: string[]) => string[]) =>
    setFeedOverride((current) => update(current ?? data?.rss_feeds ?? []));

  if (isLoading) {
    return (
      <div className="grid gap-4 lg:grid-cols-2">
        <CardSkeleton className="h-52 w-full" />
        <CardSkeleton className="h-52 w-full" />
      </div>
    );
  }
  if (error || !data) return <ErrorState error={error} />;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <DatabaseIcon className="text-muted-foreground size-4" />
            Stato Qdrant
          </CardTitle>
          <CardDescription>
            Vector DB per RAG — se giù, il bot gira senza knowledge base
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Qdrant</span>
            {data.qdrant_up ? (
              <Stamp tone="approved">Attivo</Stamp>
            ) : (
              <Stamp tone="rejected">Non raggiungibile</Stamp>
            )}
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">news_kb</span>
            <span className="font-mono tabular-nums">
              {fmtNum(data.collections.news_kb, 0)} documenti
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">trade_memory</span>
            <span className="font-mono tabular-nums">
              {fmtNum(data.collections.trade_memory, 0)} documenti
            </span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RssIcon className="text-muted-foreground size-4" />
            Fonti RSS
          </CardTitle>
          <CardDescription>
            Ultimo fetch: {display.dateTime(data.last_fetch)}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex max-h-52 flex-col gap-2 overflow-y-auto">
            {feeds.map((feed, index) => (
              <div key={`${index}-${feed}`} className="flex items-center gap-2">
                <Input value={feed} onChange={(event) => setFeeds((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} aria-label={`Feed RSS ${index + 1}`} />
                <Button variant="ghost" size="icon" aria-label="Rimuovi feed" onClick={() => setFeeds((current) => current.filter((_, itemIndex) => itemIndex !== index))}><Trash2Icon aria-hidden="true" /></Button>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setFeeds((current) => [...current, ""])}><PlusIcon data-icon="inline-start" aria-hidden="true" />Aggiungi feed</Button>
            <Button variant="outline" size="sm" disabled={updateFeeds.isPending} onClick={() => updateFeeds.mutate(feeds, { onSuccess: () => setFeedOverride(null) })}><SaveIcon data-icon="inline-start" aria-hidden="true" />Salva feed</Button>
            <Button size="sm" disabled={fetchNews.isPending} onClick={() => fetchNews.mutate()}><DownloadIcon data-icon="inline-start" aria-hidden="true" />{fetchNews.isPending ? "Fetch in corso…" : "Fetch ora"}</Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function IngestCard() {
  const ingest = useIngestDocument();
  const [file, setFile] = React.useState<File | null>(null);
  const [dragActive, setDragActive] = React.useState(false);
  const [lastResult, setLastResult] = React.useState<IngestResult | null>(null);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const pickFile = (candidate: File | undefined | null) => {
    if (!candidate) return;
    if (!isAcceptedFile(candidate)) {
      toast.error("Formato non supportato", {
        description: `Estensioni ammesse: ${ACCEPTED_LABELS.join(", ")}`,
      });
      return;
    }
    setLastResult(null);
    setFile(candidate);
  };

  const submit = () => {
    if (!file) return;
    // Nessun ticker da allegare: i titoli impattati li deduce l'ingestione
    // dal contenuto, chunk per chunk.
    const formData = new FormData();
    formData.append("file", file);
    ingest.mutate(formData, {
      onSuccess: (data) => {
        setLastResult(data);
        setFile(null);
        if (inputRef.current) inputRef.current.value = "";
      },
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <UploadCloudIcon className="text-muted-foreground size-4" />
          Ingestione documento
        </CardTitle>
        <CardDescription>
          Carica un documento (news, analisi, note) da indicizzare nella
          knowledge base: i titoli impattati vengono rilevati dal contenuto
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") inputRef.current?.click();
          }}
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            pickFile(e.dataTransfer.files?.[0]);
          }}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed px-4 py-8 text-center transition-colors",
            dragActive ? "border-primary bg-primary/5" : "border-border",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,.docx,.pptx,.xlsx,.md,.txt"
            className="hidden"
            onChange={(e) => pickFile(e.target.files?.[0])}
          />
          <UploadCloudIcon className="text-muted-foreground size-6" strokeWidth={1.5} />
          <p className="text-sm">
            Trascina un file qui o clicca per selezionarlo
          </p>
          <p className="text-muted-foreground font-mono text-[10px] tracking-[0.18em] uppercase">
            {ACCEPTED_LABELS.join(" · ")}
          </p>
        </div>

        {file ? (
          <div className="text-muted-foreground flex items-center gap-2 font-mono text-xs">
            <FileIcon className="size-3.5" />
            {file.name}
          </div>
        ) : null}

        <Button disabled={ingest.isPending || !file} onClick={submit}>
          {ingest.isPending ? "Caricamento…" : "Carica e indicizza"}
        </Button>

        {lastResult ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Stamp tone="approved">Indicizzato</Stamp>
              <span className="text-muted-foreground text-xs">
                {lastResult.chunks_indexed} chunk indicizzati da {lastResult.filename}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-muted-foreground font-mono text-[10px] tracking-[0.14em] uppercase">
                Titoli rilevati
              </span>
              {lastResult.tickers?.length ? (
                lastResult.tickers.map((ticker) => (
                  <Stamp key={ticker} tone="accent">
                    {ticker}
                  </Stamp>
                ))
              ) : (
                <span className="text-muted-foreground text-xs">
                  nessuno dell&apos;universo investibile
                </span>
              )}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

export default function KnowledgePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="RAG"
        title="Knowledge base"
        description="RAG su Qdrant (news_kb, trade_memory) + fonti RSS. La KB è un'aggiunta, mai un requisito."
      />
      <StatusCards />
      <IngestCard />
    </div>
  );
}
