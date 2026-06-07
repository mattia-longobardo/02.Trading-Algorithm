"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderPlus } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CreateFolderDialog } from "@/components/reports/create-folder-dialog";
import { ReportFolderTree } from "@/components/reports/report-folder-tree";
import { ReportPreview } from "@/components/reports/report-preview";
import { ReportSearch } from "@/components/reports/report-search";
import { ReportsList } from "@/components/reports/reports-list";
import { api } from "@/lib/api";
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

  const folderList = useMemo(
    () => folders.data?.folders ?? [],
    [folders.data],
  );

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
          <CardContent>
            <ReportFolderTree
              folders={folderList}
              selected={folderFilter}
              onSelect={setFolderFilter}
              onDeleteFolder={(f) => {
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
          <CardContent>
            <ReportSearch
              q={q}
              onQChange={setQ}
              fullText={fullText}
              onFullTextChange={setFullText}
              typeFilter={typeFilter}
              onTypeFilterChange={setTypeFilter}
            />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Risultati</CardTitle>
          <span className="text-xs text-(--color-muted)">
            {reports.data?.items.length ?? 0} report
          </span>
        </CardHeader>
        <CardContent>
          <ReportsList
            items={reports.data?.items ?? []}
            loading={reports.isLoading}
            folders={folderList}
            onPreview={setPreviewing}
            onMove={(id, folder_id) => moveMutation.mutate({ id, folder_id })}
          />
        </CardContent>
      </Card>

      <ReportPreview report={previewing} onClose={() => setPreviewing(null)} />

      <CreateFolderDialog open={creatingFolder} onClose={() => setCreatingFolder(false)} />
    </section>
  );
}
