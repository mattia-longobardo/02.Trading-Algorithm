"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, streamUrl } from "@/lib/api";
import type { ReportRow } from "@/lib/types";

interface ReportJsonViewerProps {
  report: ReportRow;
}

function ReportJsonViewer({ report }: ReportJsonViewerProps) {
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
      <pre className="max-h-[70vh] overflow-auto rounded-lg border border-(--color-line) bg-(--color-panel) p-4 text-xs leading-relaxed">
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

interface ReportPreviewInnerProps {
  report: ReportRow;
}

function ReportPreviewInner({ report }: ReportPreviewInnerProps) {
  if (report.format === "pdf") {
    return (
      <div>
        <DialogHeader>
          <DialogTitle>{report.filename}</DialogTitle>
          <DialogDescription>Anteprima PDF.</DialogDescription>
        </DialogHeader>
        <iframe
          title={`Anteprima PDF — ${report.filename}`}
          src={streamUrl(`/api/reports/${report.id}/file`)}
          className="h-[70vh] w-full rounded-lg border border-(--color-line) bg-(--color-panel)"
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

export interface ReportPreviewProps {
  report: ReportRow | null;
  onClose: () => void;
}

export function ReportPreview({ report, onClose }: ReportPreviewProps) {
  return (
    <Dialog open={Boolean(report)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-4xl">
        {report && <ReportPreviewInner report={report} />}
      </DialogContent>
    </Dialog>
  );
}
