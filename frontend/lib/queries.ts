"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { toast } from "sonner";

import { api, errorMessage, ApiError } from "@/lib/api";
import type {
  AppSettings,
  AccountCredentials,
  AuditResponse,
  BacktestSummary,
  DecisionsResponse,
  EquityCurve,
  ExecutionsResponse,
  FxRates,
  IngestResult,
  KnowledgeStatus,
  MonthlyReturns,
  Portfolio,
  RiskHistory,
  RiskScore,
  RunStartResponse,
  RunsResponse,
  SettingsUpdate,
  Status,
  TradesResponse,
  TradeHistoryItem,
  TradeItem,
  NewsItem,
  ReportItem,
  DateRangeValue,
} from "@/lib/types";

/** Intervallo di polling standard: 15 secondi. */
export const POLL_MS = 15_000;

// ---------------------------------------------------------------- queries

export function useStatus() {
  return useQuery<Status>({
    queryKey: ["status"],
    queryFn: () => api.get<Status>("/status"),
    refetchInterval: POLL_MS,
  });
}

export function useRuns(limit = 50) {
  return useQuery<RunsResponse>({
    queryKey: ["runs", limit],
    queryFn: () => api.get<RunsResponse>(`/runs?limit=${limit}`),
    refetchInterval: POLL_MS,
  });
}

export function useRunDecisions(runId: string) {
  return useQuery<DecisionsResponse>({
    queryKey: ["runs", runId, "decisions"],
    queryFn: () => api.get<DecisionsResponse>(`/runs/${encodeURIComponent(runId)}/decisions`),
    refetchInterval: POLL_MS,
  });
}

export function useExecutions(limit = 50) {
  return useQuery<ExecutionsResponse>({
    queryKey: ["executions", limit],
    queryFn: () => api.get<ExecutionsResponse>(`/executions?limit=${limit}`),
    refetchInterval: POLL_MS,
  });
}

export function usePortfolio() {
  return useQuery<Portfolio>({
    queryKey: ["portfolio"],
    queryFn: () => api.get<Portfolio>("/portfolio"),
    refetchInterval: POLL_MS,
  });
}

function withRange(path: string, range?: DateRangeValue) {
  if (!range) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}date_from=${encodeURIComponent(range.from)}&date_to=${encodeURIComponent(range.to)}`;
}

export function useBacktestSummary(range?: DateRangeValue) {
  return useQuery<BacktestSummary>({
    queryKey: ["backtest", "summary", range?.from, range?.to],
    queryFn: () => api.get<BacktestSummary>(withRange("/backtest/summary", range)),
    refetchInterval: POLL_MS,
  });
}

export function useEquityCurve(benchmark = "spy", range?: DateRangeValue) {
  return useQuery<EquityCurve>({
    queryKey: ["backtest", "equity-curve", benchmark, range?.from, range?.to],
    queryFn: () => api.get<EquityCurve>(withRange(`/backtest/equity-curve?benchmark=${encodeURIComponent(benchmark)}`, range)),
    refetchInterval: POLL_MS,
  });
}

export function useBacktestTrades() {
  return useQuery<TradesResponse>({
    queryKey: ["backtest", "trades"],
    queryFn: () => api.get<TradesResponse>("/backtest/trades"),
    refetchInterval: POLL_MS,
  });
}

export function useMonthlyReturns() {
  return useQuery<MonthlyReturns>({
    queryKey: ["backtest", "monthly-returns"],
    queryFn: () => api.get<MonthlyReturns>("/backtest/monthly-returns"),
    refetchInterval: POLL_MS,
  });
}

export function useRiskScore() {
  return useQuery<RiskScore>({
    queryKey: ["risk", "score"],
    queryFn: () => api.get<RiskScore>("/risk/score"),
    refetchInterval: POLL_MS,
  });
}

export function useRiskHistory() {
  return useQuery<RiskHistory>({
    queryKey: ["risk", "score-history"],
    queryFn: () => api.get<RiskHistory>("/risk/score/history"),
    refetchInterval: POLL_MS,
  });
}

export function useKnowledgeStatus() {
  return useQuery<KnowledgeStatus>({
    queryKey: ["knowledge", "status"],
    queryFn: () => api.get<KnowledgeStatus>("/knowledge/status"),
    refetchInterval: POLL_MS,
  });
}

export function useSettings() {
  return useQuery<AppSettings>({
    queryKey: ["settings"],
    queryFn: () => api.get<AppSettings>("/settings"),
    refetchInterval: POLL_MS,
  });
}

/**
 * Tassi USD→valuta per la conversione di visualizzazione.
 * I cambi BCE si muovono una volta al giorno: inutile il polling a 15s.
 */
export function useFxRates() {
  return useQuery<FxRates>({
    queryKey: ["fx", "rates"],
    queryFn: () => api.get<FxRates>("/fx/rates"),
    staleTime: 30 * 60_000,
    refetchInterval: 60 * 60_000,
  });
}

export function useSettingsAudit() {
  return useQuery<AuditResponse>({
    queryKey: ["settings", "audit"],
    queryFn: () => api.get<AuditResponse>("/settings/audit"),
    refetchInterval: POLL_MS,
  });
}

export function useAccountCredentials() {
  return useQuery<AccountCredentials>({
    queryKey: ["account", "credentials"],
    queryFn: () => api.get<AccountCredentials>("/account/credentials"),
  });
}

export function useTrades(statuses: string[] = [], symbol = "") {
  const params = new URLSearchParams({ statuses: statuses.join(","), symbol });
  return useQuery<{ trades: TradeItem[] }>({
    queryKey: ["trades", statuses.join(","), symbol],
    queryFn: () => api.get(`/trades?${params.toString()}`),
    refetchInterval: POLL_MS,
  });
}

export function useTradeHistory(statuses: string[] = [], range?: DateRangeValue, symbol = "") {
  const params = new URLSearchParams({ statuses: statuses.join(","), symbol });
  if (range) {
    params.set("date_from", range.from);
    params.set("date_to", range.to);
  }
  return useQuery<{ items: TradeHistoryItem[] }>({
    queryKey: ["trade-history", statuses.join(","), range?.from, range?.to, symbol],
    queryFn: () => api.get(`/trade-history?${params.toString()}`),
    refetchInterval: POLL_MS,
  });
}

export function useNews() {
  return useQuery<{ items: NewsItem[]; updated_at: string | null }>({
    queryKey: ["news"],
    queryFn: () => api.get("/news"),
    refetchInterval: 60_000,
  });
}

export function useReports() {
  return useQuery<{ reports: ReportItem[] }>({
    queryKey: ["reports"],
    queryFn: () => api.get("/reports"),
  });
}

// -------------------------------------------------------------- mutations

export function useTriggerRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<RunStartResponse>("/run"),
    onSuccess: (data) => {
      toast.success(
        "Run avviata",
        data?.run_id ? { description: `Run ID: ${data.run_id}` } : undefined,
      );
      void qc.invalidateQueries({ queryKey: ["status"] });
      void qc.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 409) {
        toast.warning("Run già in corso", { description: err.detail });
      } else {
        toast.error("Avvio run fallito", { description: errorMessage(err) });
      }
    },
  });
}

export function useDeleteRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      api.del<{ deleted: boolean; run_id: string }>(`/runs/${encodeURIComponent(runId)}`),
    onSuccess: () => {
      toast.success("Run eliminata", {
        description: "Rimosse anche le decisioni e le esecuzioni collegate",
      });
      void qc.invalidateQueries({ queryKey: ["runs"] });
      void qc.invalidateQueries({ queryKey: ["executions"] });
      void qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (err) => toast.error("Eliminazione run fallita", { description: errorMessage(err) }),
  });
}

export function useKillSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (activate: boolean) =>
      activate ? api.post<unknown>("/kill-switch") : api.del<unknown>("/kill-switch"),
    onSuccess: (_data, activate) => {
      toast.success(
        activate ? "KILL SWITCH ATTIVATO" : "Kill switch disattivato",
      );
      void qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (err) => {
      toast.error("Operazione kill switch fallita", {
        description: errorMessage(err),
      });
    },
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (update: SettingsUpdate) =>
      api.put<AppSettings>("/settings", update),
    onSuccess: () => {
      toast.success("Impostazioni aggiornate");
      void qc.invalidateQueries({ queryKey: ["settings"] });
      void qc.invalidateQueries({ queryKey: ["status"] });
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 422) {
        toast.error("Modifica respinta dal backend", {
          description: err.detail,
        });
      } else {
        toast.error("Aggiornamento impostazioni fallito", {
          description: errorMessage(err),
        });
      }
    },
  });
}

export function useUpdateCredentials() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      etoro_api_key?: string;
      etoro_user_key?: string;
      openai_api_key?: string;
    }) => api.put<AccountCredentials>("/account/credentials", body),
    onSuccess: () => {
      toast.success("Chiavi personali aggiornate");
      void qc.invalidateQueries({ queryKey: ["account", "credentials"] });
      void qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err) => toast.error("Salvataggio chiavi fallito", { description: errorMessage(err) }),
  });
}

export function useCloseTrade() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (positionId: string | number) =>
      api.post(`/trades/${positionId}/close`, { confirmation: "CHIUDI" }),
    onSuccess: () => {
      toast.success("Posizione chiusa");
      void qc.invalidateQueries({ queryKey: ["trades"] });
      void qc.invalidateQueries({ queryKey: ["trade-history"] });
      void qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
    onError: (err) => toast.error("Chiusura fallita", { description: errorMessage(err) }),
  });
}

export function useCancelExecution() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (executionId: string) => api.post(`/executions/${executionId}/cancel`),
    onSuccess: () => {
      toast.success("Ordine annullato");
      void qc.invalidateQueries({ queryKey: ["trades"] });
      void qc.invalidateQueries({ queryKey: ["trade-history"] });
    },
    onError: (err) => toast.error("Annullamento fallito", { description: errorMessage(err) }),
  });
}

export function useUpdateRssFeeds() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (feeds: string[]) => api.put<{ rss_feeds: string[] }>("/knowledge/rss-feeds", { feeds }),
    onSuccess: () => {
      toast.success("Feed RSS aggiornati");
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (err) => toast.error("Aggiornamento feed fallito", { description: errorMessage(err) }),
  });
}

export function useFetchNews() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<unknown>("/knowledge/fetch-news"),
    onSuccess: () => {
      toast.success("Fetch news avviato");
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (err) => {
      toast.error("Fetch news fallito", { description: errorMessage(err) });
    },
  });
}

/** Upload multipart (file + tickers opzionali): non passa da `lib/api.ts`
 * (che serializza sempre JSON) — fetch diretto, niente Content-Type esplicito
 * così il browser imposta il boundary multipart corretto. */
async function uploadDocument(formData: FormData): Promise<IngestResult> {
  const res = await fetch("/api/knowledge/ingest", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    let detail = `Errore HTTP ${res.status}`;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body) {
        const d = (body as { detail: unknown }).detail;
        detail = typeof d === "string" ? d : JSON.stringify(d);
      }
    } catch {
      // body non-JSON: si tiene il messaggio generico
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as IngestResult;
}

export function useIngestDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (formData: FormData) => uploadDocument(formData),
    onSuccess: (data) => {
      const detected = data.tickers?.length
        ? `titoli rilevati: ${data.tickers.join(", ")}`
        : "nessun titolo dell'universo rilevato";
      toast.success("Documento indicizzato nella knowledge base", {
        description: `${data.chunks_indexed} chunk da ${data.filename} — ${detected}`,
      });
      void qc.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (err) => {
      toast.error("Ingestione fallita", { description: errorMessage(err) });
    },
  });
}
