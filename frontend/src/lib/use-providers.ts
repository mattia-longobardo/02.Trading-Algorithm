"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Provider, ProvidersResponse } from "@/lib/types";

/**
 * Single source of truth for "which broker modules are active right now?".
 *
 * The backend auto-detects active providers from configured API keys at
 * startup. The frontend treats inactive providers as if they didn't exist:
 * we never render their dashboard contributions, universe tabs, prompt
 * tabs, or settings cards.
 *
 * Cached for 5 minutes — providers only change on a backend restart, and
 * stale=false here would re-fetch on every mount.
 */
export function useProviders() {
  const query = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.get<ProvidersResponse>("/api/providers"),
    staleTime: 5 * 60 * 1000,
  });

  const active = query.data?.active ?? [];
  const isActive = (provider: Provider) => active.includes(provider);

  return {
    ...query,
    active,
    descriptors: query.data?.providers ?? [],
    isActive,
    alpaca: isActive("alpaca"),
    none: query.data ? active.length === 0 : false,
  };
}
