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
    <div className="overflow-x-auto">
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
  );
}
