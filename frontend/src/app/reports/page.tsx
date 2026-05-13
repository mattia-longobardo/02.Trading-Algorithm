"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSearch, Folder, FolderPlus, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api, streamUrl } from "@/lib/api";
import { formatDateTime, formatNumber } from "@/lib/format";
import type { ReportFolder, ReportRow } from "@/lib/types";

type FolderFilter = number | null | "ALL";

export default function ReportsPage() {
  const qc = useQueryClient();
  const [folderFilter, setFolderFilter] = useState<FolderFilter>("ALL");
  const [typeFilter, setTypeFilter] = useState<string>("ALL");
  const [q, setQ] = useState("");
  const [fullText, setFullText] = useState(false);
  const [previewing, setPreviewing] = useState<ReportRow | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);

  const params = new URLSearchParams();
  if (folderFilter !== "ALL") {
    params.set("folder_id", folderFilter === null ? "0" : String(folderFilter));
  }
  if (typeFilter !== "ALL") params.set("type", typeFilter);
  if (q.trim()) params.set("q", q.trim());
  if (fullText && q.trim()) params.set("full_text", "true");

  const reports = useQuery({
    queryKey: ["reports", folderFilter, typeFilter, q, fullText],
    queryFn: () => api.get<{ items: ReportRow[] }>(`/api/reports?${params.toString()}`),
  });

  const folders = useQuery({
    queryKey: ["report-folders"],
    queryFn: () => api.get<{ folders: ReportFolder[] }>(`/api/report-folders`),
  });

  const moveMutation = useMutation({
    mutationFn: ({ id, folder_id }: { id: number; folder_id: number | null }) =>
      api.patch(`/api/reports/${id}`, { folder_id, clear_folder: folder_id === null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["reports"] }),
  });

  const deleteFolderMutation = useMutation({
    mutationFn: (id: number) => api.delete(`/api/report-folders/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["report-folders"] });
      qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });

  const folderById = useMemo(() => {
    const map = new Map<number, ReportFolder>();
    for (const f of folders.data?.folders ?? []) {
      map.set(f.id, f);
    }
    return map;
  }, [folders.data]);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Report</h1>
          <p className="text-sm text-(--color-muted)">
            Sfoglia i report JSON e PDF generati dal bot. I file restano sul disco; le cartelle
            sono virtuali.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setCreatingFolder(true)}>
          <FolderPlus className="size-4" /> Nuova cartella
        </Button>
      </header>

      <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Cartelle</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            <FolderRow
              label="Tutte"
              active={folderFilter === "ALL"}
              onClick={() => setFolderFilter("ALL")}
            />
            <FolderRow
              label="Senza cartella"
              active={folderFilter === null}
              onClick={() => setFolderFilter(null)}
            />
            <FolderTree
              folders={folders.data?.folders ?? []}
              activeId={folderFilter}
              onSelect={(id) => setFolderFilter(id)}
              onDelete={(f) => {
                if (
                  confirm(
                    `Eliminare la cartella "${f.name}"? I report tornano "senza cartella".`
                  )
                ) {
                  deleteFolderMutation.mutate(f.id);
                }
              }}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Filtri</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-3">
            <div className="md:col-span-2 space-y-1">
              <label className="text-xs uppercase text-(--color-muted)">Cerca</label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-(--color-muted)" />
                  <Input
                    className="pl-9"
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                    placeholder="filename, tag o contenuto JSON…"
                  />
                </div>
                <label className="flex items-center gap-2 text-xs text-(--color-muted)">
                  <input
                    type="checkbox"
                    checked={fullText}
                    onChange={(e) => setFullText(e.target.checked)}
                  />
                  Full-text JSON
                </label>
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs uppercase text-(--color-muted)">Tipo</label>
              <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">Tutti</SelectItem>
                  <SelectItem value="weekly">Settimanale</SelectItem>
                  <SelectItem value="quarterly">Trimestrale</SelectItem>
                  <SelectItem value="biannual">Semestrale</SelectItem>
                  <SelectItem value="annual">Annuale</SelectItem>
                  <SelectItem value="other">Altro</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Risultati</CardTitle>
          <span className="text-xs text-(--color-muted)">{reports.data?.items.length ?? 0} report</span>
        </CardHeader>
        <CardContent>
          {reports.isLoading && <p className="text-sm text-(--color-muted)">Caricamento…</p>}
          {!reports.isLoading && (reports.data?.items.length ?? 0) === 0 && (
            <EmptyState
              icon={FileSearch}
              title="Nessun report trovato"
              description={
                <>
                  I report settimanali sono generati ogni domenica alle 23:00 UTC.
                  Puoi lanciarne uno manualmente dalla Console oppure cambiare i
                  filtri qui sopra.
                </>
              }
            />
          )}
          {(reports.data?.items.length ?? 0) > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[840px] border-separate border-spacing-y-1 text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase text-(--color-muted)">
                    <th className="px-2 py-2">Nome</th>
                    <th className="px-2 py-2">Tipo</th>
                    <th className="px-2 py-2">Formato</th>
                    <th className="px-2 py-2 text-right">Dim.</th>
                    <th className="px-2 py-2">Generato</th>
                    <th className="px-2 py-2">Cartella</th>
                    <th className="px-2 py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {reports.data!.items.map((r) => (
                    <tr
                      key={r.id}
                      className="bg-slate-950/40 transition-colors hover:bg-slate-900/60 [&>td]:border-y [&>td]:border-(--color-line)"
                    >
                      <td className="px-2 py-2 font-medium first:rounded-l-lg">{r.filename}</td>
                      <td className="px-2 py-2">
                        <Badge variant="muted">{r.type}</Badge>
                      </td>
                      <td className="px-2 py-2">
                        <Badge variant={r.format === "pdf" ? "open" : "muted"}>{r.format}</Badge>
                      </td>
                      <td className="px-2 py-2 text-right">
                        {formatNumber(r.size_bytes / 1024, { maximumFractionDigits: 1 })} KB
                      </td>
                      <td className="px-2 py-2 text-(--color-muted)">{formatDateTime(r.generated_at)}</td>
                      <td className="px-2 py-2">
                        <Select
                          value={r.folder_id ? String(r.folder_id) : "NONE"}
                          onValueChange={(v) =>
                            moveMutation.mutate({
                              id: r.id,
                              folder_id: v === "NONE" ? null : Number(v),
                            })
                          }
                        >
                          <SelectTrigger className="h-8 text-xs">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="NONE">— senza cartella —</SelectItem>
                            {folders.data?.folders.map((f) => (
                              <SelectItem key={f.id} value={String(f.id)}>
                                {f.name}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </td>
                      <td className="px-2 py-2 last:rounded-r-lg">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="secondary" onClick={() => setPreviewing(r)}>
                            Apri
                          </Button>
                          <a
                            href={streamUrl(`/api/reports/${r.id}/file?download=true`)}
                            download={r.filename}
                          >
                            <Button size="icon" variant="ghost" className="size-8">
                              <Download className="size-4" />
                            </Button>
                          </a>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={Boolean(previewing)} onOpenChange={(o) => !o && setPreviewing(null)}>
        <DialogContent className="max-w-4xl">
          {previewing && <ReportPreview report={previewing} />}
        </DialogContent>
      </Dialog>

      <CreateFolderDialog open={creatingFolder} onClose={() => setCreatingFolder(false)} />
    </section>
  );
}

function FolderTree({
  folders,
  activeId,
  onSelect,
  onDelete,
}: {
  folders: ReportFolder[];
  activeId: FolderFilter;
  onSelect: (id: number) => void;
  onDelete: (f: ReportFolder) => void;
}) {
  // Group folders by parent id (null = root) and sort children by name.
  const byParent = new Map<number | null, ReportFolder[]>();
  for (const f of folders) {
    const key = f.parent_id ?? null;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(f);
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name));
  }

  function render(parentId: number | null, depth: number): React.ReactNode {
    const children = byParent.get(parentId) ?? [];
    return children.map((f) => (
      <div key={f.id}>
        <div className="flex items-center gap-1" style={{ paddingLeft: depth * 12 }}>
          <FolderRow
            className="flex-1"
            label={f.name}
            active={activeId === f.id}
            onClick={() => onSelect(f.id)}
          />
          <Button
            variant="ghost"
            size="icon"
            className="text-(--color-muted) hover:text-rose-400"
            onClick={() => onDelete(f)}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
        {render(f.id, depth + 1)}
      </div>
    ));
  }

  return <>{render(null, 0)}</>;
}

function FolderRow({
  label,
  active,
  onClick,
  className,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm transition-colors ${
        active ? "bg-slate-800 text-(--color-text)" : "text-(--color-muted) hover:bg-slate-800/60"
      } ${className ?? ""}`}
    >
      <Folder className="size-4" />
      <span className="truncate">{label}</span>
    </button>
  );
}

function ReportPreview({ report }: { report: ReportRow }) {
  if (report.format === "pdf") {
    return (
      <div>
        <DialogHeader>
          <DialogTitle>{report.filename}</DialogTitle>
          <DialogDescription>Anteprima PDF.</DialogDescription>
        </DialogHeader>
        <iframe
          src={streamUrl(`/api/reports/${report.id}/file`)}
          className="h-[70vh] w-full rounded-lg border border-(--color-line) bg-slate-950"
        />
        <div className="mt-3 flex justify-end">
          <a
            href={streamUrl(`/api/reports/${report.id}/file?download=true`)}
            download={report.filename}
          >
            <Button size="sm" variant="secondary">
              <Download className="size-4" /> Scarica
            </Button>
          </a>
        </div>
      </div>
    );
  }
  return <ReportJsonViewer report={report} />;
}

function ReportJsonViewer({ report }: { report: ReportRow }) {
  const json = useQuery({
    queryKey: ["report-json", report.id],
    queryFn: () =>
      api.get<{ report: ReportRow; content: unknown }>(`/api/reports/${report.id}/json`),
  });
  return (
    <div>
      <DialogHeader>
        <DialogTitle>{report.filename}</DialogTitle>
        <DialogDescription>Contenuto JSON.</DialogDescription>
      </DialogHeader>
      <pre className="max-h-[70vh] overflow-auto rounded-lg border border-(--color-line) bg-slate-950 p-4 text-xs leading-relaxed">
        {json.isLoading
          ? "Caricamento…"
          : json.data
          ? JSON.stringify(json.data.content, null, 2)
          : "—"}
      </pre>
      <div className="mt-3 flex justify-end">
        <a
          href={streamUrl(`/api/reports/${report.id}/file?download=true`)}
          download={report.filename}
        >
          <Button size="sm" variant="secondary">
            <Download className="size-4" /> Scarica
          </Button>
        </a>
      </div>
    </div>
  );
}

function CreateFolderDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: () => api.post(`/api/report-folders`, { name }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["report-folders"] });
      setName("");
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuova cartella</DialogTitle>
          <DialogDescription>
            Le cartelle sono solo metadati; non rinominano né spostano i file su disco.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Nome cartella"
            autoFocus
          />
          {error && <StatusBanner kind="error">{error}</StatusBanner>}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Annulla
            </Button>
            <Button onClick={() => mutation.mutate()} disabled={!name.trim() || mutation.isPending}>
              Crea
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
