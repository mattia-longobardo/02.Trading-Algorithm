"use client";

import { useEffect, useRef, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api, streamUrl } from "@/lib/api";

interface LogsResponse {
  log_file: string;
  line_count: number;
  logs: string;
  updated_at: string;
}

export function LogStream() {
  const [content, setContent] = useState<string>("Caricamento dei log…");
  const [meta, setMeta] = useState<string>("…");
  const [status, setStatus] = useState<string>("Connessione…");
  const preRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    let eventSource: EventSource | null = null;
    let cancelled = false;

    function appendChunk(chunk: string) {
      if (!chunk) return;
      const el = preRef.current;
      const stickToBottom = el ? el.scrollTop + el.clientHeight >= el.scrollHeight - 20 : true;
      setContent((prev) => (prev === "Caricamento dei log…" ? chunk : prev + chunk));
      requestAnimationFrame(() => {
        if (stickToBottom && preRef.current) {
          preRef.current.scrollTop = preRef.current.scrollHeight;
        }
      });
    }

    async function bootstrap() {
      try {
        const payload = await api.get<LogsResponse>(`/api/logs?lines=10000`);
        if (cancelled) return;
        setContent(
          payload.logs ||
            "Nessuna riga di log al momento. Lo scheduler scriverà qui non appena fa partire il primo job."
        );
        setMeta(`${payload.line_count} righe da ${payload.log_file}`);
        setStatus(`Connesso: ${payload.updated_at}`);
        requestAnimationFrame(() => {
          if (preRef.current) {
            preRef.current.scrollTop = preRef.current.scrollHeight;
          }
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : "errore sconosciuto";
        if (!cancelled) setStatus(`Caricamento fallito: ${message}`);
      }

      if (cancelled) return;
      eventSource = new EventSource(streamUrl(`/api/logs/stream`));
      eventSource.onopen = () => setStatus("Streaming attivo");
      eventSource.addEventListener("append", (event) => {
        appendChunk((event as MessageEvent).data);
      });
      eventSource.addEventListener("heartbeat", (event) => {
        setStatus(`Streaming live: ${(event as MessageEvent).data}`);
      });
      eventSource.onerror = () => setStatus("Riconnessione…");
    }

    bootstrap();

    return () => {
      cancelled = true;
      eventSource?.close();
    };
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-(--color-muted)">Tail live del file di log del bot.</p>
        <div className="text-sm text-(--color-muted)">{status}</div>
      </div>
      <Card className="overflow-hidden p-0">
        <CardHeader className="border-b border-(--color-line) bg-(--color-panel)/80 px-4 py-3">
          <CardTitle className="flex items-center gap-2">
            <span className="inline-block size-2.5 rounded-full bg-(--color-accent) shadow-[0_0_12px_rgba(34,197,94,0.8)]" />
            Streaming live
          </CardTitle>
          <span className="text-xs text-(--color-muted)">{meta}</span>
        </CardHeader>
        <CardContent className="p-0">
          <pre
            ref={preRef}
            className="m-0 max-h-[70vh] min-h-[70vh] overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-[13px] leading-relaxed"
          >
            {content}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
