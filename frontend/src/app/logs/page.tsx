"use client";

import { useEffect, useRef, useState } from "react";
import { fetchLogs, logsStreamUrl } from "@/lib/api";

export default function LogsPage() {
  const [content, setContent] = useState<string>("Loading logs...");
  const [meta, setMeta] = useState<string>("Loading...");
  const [status, setStatus] = useState<string>("Connecting...");
  const preRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    let eventSource: EventSource | null = null;
    let cancelled = false;

    function appendChunk(chunk: string) {
      if (!chunk) return;
      const el = preRef.current;
      const stickToBottom = el
        ? el.scrollTop + el.clientHeight >= el.scrollHeight - 20
        : true;
      setContent((prev) => (prev === "Loading logs..." ? chunk : prev + chunk));
      requestAnimationFrame(() => {
        if (stickToBottom && preRef.current) {
          preRef.current.scrollTop = preRef.current.scrollHeight;
        }
      });
    }

    async function bootstrap() {
      try {
        const payload = await fetchLogs(10000);
        if (cancelled) return;
        setContent(payload.logs || "No logs available.");
        setMeta(`${payload.line_count} lines from ${payload.log_file}`);
        setStatus(`Connected: ${payload.updated_at}`);
        requestAnimationFrame(() => {
          if (preRef.current) {
            preRef.current.scrollTop = preRef.current.scrollHeight;
          }
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : "unknown error";
        if (!cancelled) setStatus(`Initial load failed: ${message}`);
      }

      if (cancelled) return;
      eventSource = new EventSource(logsStreamUrl());
      eventSource.onopen = () => setStatus("Streaming connected");
      eventSource.addEventListener("append", (event) => {
        appendChunk((event as MessageEvent).data);
      });
      eventSource.addEventListener("heartbeat", (event) => {
        setStatus(`Streaming live: ${(event as MessageEvent).data}`);
      });
      eventSource.onerror = () => setStatus("Streaming reconnecting...");
    }

    bootstrap();

    return () => {
      cancelled = true;
      eventSource?.close();
    };
  }, []);

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Trading Bot Logs</h1>
          <p className="text-sm text-(--color-muted)">Live tail del file di log del bot</p>
        </div>
        <div className="text-sm text-(--color-muted)">{status}</div>
      </div>
      <div className="overflow-hidden rounded-2xl border border-(--color-line) bg-(--color-panel)/90 shadow-2xl">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-(--color-line) bg-slate-950/80 px-4 py-3 text-sm text-(--color-muted)">
          <span className="inline-flex items-center gap-2">
            <span className="inline-block size-2.5 rounded-full bg-(--color-accent) shadow-[0_0_12px_rgba(34,197,94,0.8)]" />
            Streaming live delle nuove righe
          </span>
          <span>{meta}</span>
        </div>
        <pre
          ref={preRef}
          className="m-0 max-h-[70vh] min-h-[70vh] overflow-auto whitespace-pre-wrap break-words p-4 text-[13px] leading-relaxed"
        >
          {content}
        </pre>
      </div>
    </section>
  );
}
