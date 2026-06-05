"use client";

import { useEffect, useRef, useState } from "react";
import { streamUrl } from "@/lib/api";
import type { LiveSnapshot, LiveStatus } from "@/lib/types";

// Backoff schedule (ms): 1s, 2s, 5s, then cap at 10s.
const BACKOFF = [1_000, 2_000, 5_000, 10_000];

function getBackoff(attempt: number): number {
  return BACKOFF[Math.min(attempt, BACKOFF.length - 1)];
}

export function useLiveStream(): { snapshot: LiveSnapshot | null; status: LiveStatus } {
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const [status, setStatus] = useState<LiveStatus>("connecting");

  const sourceRef = useRef<EventSource | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;

    function clearTimer() {
      if (timerRef.current !== null) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    }

    function closeSource() {
      if (sourceRef.current) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
    }

    function connect() {
      if (!mountedRef.current) return;
      // Guard: only run in browser environments
      if (typeof EventSource === "undefined") return;
      // Don't reconnect if the tab is hidden
      if (typeof document !== "undefined" && document.hidden) return;

      closeSource();
      setStatus("connecting");

      const es = new EventSource(streamUrl("/api/live/stream"));
      sourceRef.current = es;

      es.onopen = () => {
        if (!mountedRef.current) return;
        attemptRef.current = 0;
        setStatus("live");
      };

      es.addEventListener("snapshot", (e) => {
        if (!mountedRef.current) return;
        try {
          const parsed: LiveSnapshot = JSON.parse((e as MessageEvent).data);
          setSnapshot(parsed);
          setStatus("live");
        } catch {
          // malformed payload — ignore
        }
      });

      es.addEventListener("heartbeat", (_e) => {
        // keep-alive: no state change needed; onopen already set us to "live"
      });

      es.onerror = () => {
        if (!mountedRef.current) return;
        closeSource();
        setStatus("reconnecting");
        const delay = getBackoff(attemptRef.current);
        attemptRef.current += 1;
        clearTimer();
        timerRef.current = setTimeout(() => {
          if (mountedRef.current) connect();
        }, delay);
      };
    }

    function handleVisibilityChange() {
      if (!mountedRef.current) return;
      if (typeof document === "undefined") return;
      if (document.hidden) {
        // Tab went background — close; we'll reopen when visible again.
        clearTimer();
        closeSource();
        setStatus("stale");
      } else {
        // Tab became visible — reconnect immediately.
        attemptRef.current = 0;
        connect();
      }
    }

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", handleVisibilityChange);
    }

    connect();

    return () => {
      mountedRef.current = false;
      clearTimer();
      closeSource();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibilityChange);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { snapshot, status };
}
