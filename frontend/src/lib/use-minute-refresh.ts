"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

// Il cron ``monitor_trades`` del backend gira ogni minuto a ``:XX:00`` UTC.
// Allineiamo il tick client a ``:XX:30`` per leggere i prezzi aggiornati.
const REFRESH_OFFSET_SECONDS = 30;

/** Invalida periodicamente (≈ :XX:30) le query keys passate. Ritorna l'orario
 * dell'ultimo tick (o null). Estratto da useDashboardAutoRefresh. */
export function useMinuteRefresh(queryKeys: readonly string[]): Date | null {
  const qc = useQueryClient();
  const [lastTick, setLastTick] = useState<Date | null>(null);
  const keysSig = queryKeys.join(",");
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    function scheduleNext() {
      const now = new Date();
      const next = new Date(now);
      next.setSeconds(REFRESH_OFFSET_SECONDS, 0);
      if (next <= now) next.setMinutes(next.getMinutes() + 1);
      const delayMs = next.getTime() - now.getTime();
      timer = setTimeout(() => {
        for (const key of keysSig.split(",")) {
          qc.invalidateQueries({ queryKey: [key] });
        }
        setLastTick(new Date());
        scheduleNext();
      }, delayMs);
    }
    scheduleNext();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [qc, keysSig]);
  return lastTick;
}
