"use client";

import { Download, FileSearch, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { streamUrl } from "@/lib/api";
import { formatDateTime, formatNumber } from "@/lib/format";
import type { ReportFolder, ReportRow } from "@/lib/types";

export interface ReportsListProps {
  items: ReportRow[];
  loading: boolean;
  folders: ReportFolder[];
  onPreview: (r: ReportRow) => void;
  onMove: (id: number, folder_id: number | null) => void;
  isAdmin: boolean;
  deletingId?: number | null;
  onDelete: (r: ReportRow) => void;
}

function ReportCard({
  report,
  folders,
  onPreview,
  onMove,
  isAdmin,
  deleting,
  onDelete,
}: {
  report: ReportRow;
  folders: ReportFolder[];
  onPreview: (r: ReportRow) => void;
  onMove: (id: number, folder_id: number | null) => void;
  isAdmin: boolean;
  deleting: boolean;
  onDelete: (r: ReportRow) => void;
}) {
  return (
    <div className="rounded-lg border border-(--color-line) bg-(--color-panel)/40 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-words font-medium">{report.filename}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            <Badge variant="muted">{report.type}</Badge>
            <Badge variant={report.format === "pdf" ? "open" : "muted"}>{report.format}</Badge>
          </div>
        </div>
        <span className="tnum shrink-0 text-xs text-(--color-muted)">
          {formatNumber(report.size_bytes / 1024, { maximumFractionDigits: 1 })} KB
        </span>
      </div>

      <div className="mt-3 space-y-2 text-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="text-(--color-muted)">Generato</span>
          <span className="text-right text-(--color-text)">{formatDateTime(report.generated_at)}</span>
        </div>
        <Select
          value={report.folder_id ? String(report.folder_id) : "NONE"}
          onValueChange={(v) => onMove(report.id, v === "NONE" ? null : Number(v))}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="NONE">— senza cartella —</SelectItem>
            {folders.map((f) => (
              <SelectItem key={f.id} value={String(f.id)}>
                {f.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="mt-3 grid grid-cols-[1fr_auto_auto] gap-2">
        <Button size="sm" variant="secondary" onClick={() => onPreview(report)}>
          Apri
        </Button>
        <a href={streamUrl(`/api/reports/${report.id}/file?download=true`)} download={report.filename}>
          <Button
            size="icon"
            variant="ghost"
            aria-label={`Scarica ${report.filename}`}
          >
            <Download className="size-4" />
          </Button>
        </a>
        {isAdmin && (
          <Button
            size="icon"
            variant="ghost"
            className="text-(--color-danger) hover:text-(--color-danger)"
            aria-label={`Elimina ${report.filename}`}
            disabled={deleting}
            onClick={() => onDelete(report)}
          >
            <Trash2 className="size-4" />
          </Button>
        )}
      </div>
    </div>
  );
}

export function ReportsList({
  items,
  loading,
  folders,
  onPreview,
  onMove,
  isAdmin,
  deletingId = null,
  onDelete,
}: ReportsListProps) {
  if (loading) {
    return <p className="text-sm text-(--color-muted)">Caricamento…</p>;
  }

  if (items.length === 0) {
    return (
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
    );
  }

  return (
    <>
    <div className="space-y-2 md:hidden">
      {items.map((r) => (
        <ReportCard
          key={r.id}
          report={r}
          folders={folders}
          onPreview={onPreview}
          onMove={onMove}
          isAdmin={isAdmin}
          deleting={deletingId === r.id}
          onDelete={onDelete}
        />
      ))}
    </div>
    <div className="hidden overflow-x-auto md:block">
      <table className="w-full min-w-[840px] border-separate border-spacing-y-1 text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-(--color-muted)">
            <th scope="col" className="px-2 py-2">Nome</th>
            <th scope="col" className="px-2 py-2">Tipo</th>
            <th scope="col" className="px-2 py-2">Formato</th>
            <th scope="col" className="px-2 py-2 text-right tabular-nums">Dim.</th>
            <th scope="col" className="px-2 py-2">Generato</th>
            <th scope="col" className="px-2 py-2">Cartella</th>
            <th scope="col" className="px-2 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr
              key={r.id}
              className="bg-(--color-panel)/40 transition-colors hover:bg-(--color-hover)/60 [&>td]:border-y [&>td]:border-(--color-line)"
            >
              <td className="px-2 py-2 font-medium first:rounded-l-lg">{r.filename}</td>
              <td className="px-2 py-2">
                <Badge variant="muted">{r.type}</Badge>
              </td>
              <td className="px-2 py-2">
                <Badge variant={r.format === "pdf" ? "open" : "muted"}>{r.format}</Badge>
              </td>
              <td className="px-2 py-2 text-right tabular-nums">
                {formatNumber(r.size_bytes / 1024, { maximumFractionDigits: 1 })} KB
              </td>
              <td className="px-2 py-2 text-(--color-muted)">{formatDateTime(r.generated_at)}</td>
              <td className="px-2 py-2">
                <Select
                  value={r.folder_id ? String(r.folder_id) : "NONE"}
                  onValueChange={(v) =>
                    onMove(r.id, v === "NONE" ? null : Number(v))
                  }
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="NONE">— senza cartella —</SelectItem>
                    {folders.map((f) => (
                      <SelectItem key={f.id} value={String(f.id)}>
                        {f.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </td>
              <td className="px-2 py-2 last:rounded-r-lg">
                <div className="flex justify-end gap-1">
                  <Button size="sm" variant="secondary" onClick={() => onPreview(r)}>
                    Apri
                  </Button>
                  <a
                    href={streamUrl(`/api/reports/${r.id}/file?download=true`)}
                    download={r.filename}
                  >
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8"
                      aria-label={`Scarica ${r.filename}`}
                    >
                      <Download className="size-4" />
                    </Button>
                  </a>
                  {isAdmin && (
                    <Button
                      size="icon"
                      variant="ghost"
                      className="size-8 text-(--color-danger) hover:text-(--color-danger)"
                      aria-label={`Elimina ${r.filename}`}
                      disabled={deletingId === r.id}
                      onClick={() => onDelete(r)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
