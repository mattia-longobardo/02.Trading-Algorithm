"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import type { SettingsResponse } from "@/lib/types";

export const SETTING_FIELDS: Array<{
  key: string;
  label: string;
  hint: string;
  kind: "number" | "string" | "select";
  options?: string[];
  restartRequired?: boolean;
}> = [
  { key: "max_open_trades_stock", label: "Max open trade stock", hint: "Slot massimi attivi su azioni.", kind: "number" },
  { key: "max_open_trades_crypto", label: "Max open trade crypto", hint: "Slot massimi attivi su crypto.", kind: "number" },
  { key: "weekly_universe_stocks", label: "Universe stock", hint: "Numero di simboli stock nell'universe settimanale.", kind: "number" },
  { key: "weekly_universe_crypto", label: "Universe crypto", hint: "Numero di simboli crypto nell'universe settimanale.", kind: "number" },
  { key: "currency", label: "Display currency", hint: "Valuta di display nella UI.", kind: "string" },
  { key: "risk_tolerance", label: "Risk tolerance", hint: "1 = conservativo, 10 = aggressivo.", kind: "number" },
  { key: "strategy_horizon_days_min", label: "Horizon min (giorni)", hint: "Minimo orizzonte di holding suggerito al modello.", kind: "number" },
  { key: "strategy_horizon_days_max", label: "Horizon max (giorni)", hint: "Massimo orizzonte di holding suggerito al modello.", kind: "number" },
  { key: "crypto_entry_limit_collar_bps", label: "Crypto collar (bps)", hint: "Tolleranza limit IOC marketable per le crypto eToro.", kind: "number" },
  { key: "crypto_entry_max_chase_bps", label: "Crypto max chase (bps)", hint: "Quanto inseguire la best ask sulle crypto eToro.", kind: "number" },
  { key: "crypto_pending_reprice_minutes", label: "Crypto reprice (min)", hint: "Minuti prima di rinviare il limit pending.", kind: "number" },
  { key: "crypto_pending_cancel_minutes", label: "Crypto cancel (min)", hint: "Minuti prima di cancellare il pending lontano dal target.", kind: "number" },
  { key: "etoro_min_trade_amount", label: "eToro min trade amount", hint: "Importo minimo per ordine eToro.", kind: "number" },
  { key: "etoro_default_leverage", label: "eToro default leverage", hint: "Leva di default per i trade eToro.", kind: "number" },
  { key: "log_level", label: "Log level", hint: "Livello log applicativo.", kind: "select", options: ["DEBUG", "INFO", "WARNING", "ERROR"], restartRequired: true },
  { key: "log_profile", label: "Log profile", hint: "Verbosity preset.", kind: "select", options: ["DEBUG", "PRODUCTION"], restartRequired: true },
];

interface EnvFormProps {
  isAdmin: boolean;
}

export function EnvForm({ isAdmin }: EnvFormProps) {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsResponse>("/api/settings"),
  });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!settings.data) return;
    const seed: Record<string, string> = {};
    for (const f of SETTING_FIELDS) {
      const v = settings.data.values[f.key];
      seed[f.key] = v === null || v === undefined ? "" : String(v);
    }
    setDraft(seed);
  }, [settings.data]);

  const mutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {};
      for (const f of SETTING_FIELDS) {
        const raw = draft[f.key];
        if (f.kind === "number") {
          if (raw === "" || raw === undefined) continue;
          const num = Number(raw);
          if (Number.isNaN(num)) throw new Error(`${f.label} non valido`);
          payload[f.key] = num;
        } else {
          payload[f.key] = raw;
        }
      }
      return api.patch<SettingsResponse>("/api/settings", payload);
    },
    onSuccess: (res) => {
      setSuccess(
        res.restart_required
          ? "Impostazioni salvate. Alcuni valori richiedono un riavvio del backend."
          : "Impostazioni salvate."
      );
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Parametri trading</CardTitle>
          {settings.data?.restart_required && (
            <Badge variant="pending">Riavvio richiesto</Badge>
          )}
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {SETTING_FIELDS.map((f) => (
            <div key={f.key} className="space-y-1">
              <label className="flex items-center justify-between text-xs uppercase text-(--color-muted)">
                <span>{f.label}</span>
                {f.restartRequired && <Badge variant="muted">restart</Badge>}
              </label>
              {f.kind === "select" ? (
                <select
                  className="h-9 w-full rounded-lg border border-(--color-line) bg-(--color-panel)/50 px-3 text-sm text-(--color-text) focus:outline-none focus:ring-2 focus:ring-(--color-accent)"
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft((p) => ({ ...p, [f.key]: e.target.value }))}
                  disabled={!isAdmin}
                >
                  {(f.options ?? []).map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : (
                <Input
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft((p) => ({ ...p, [f.key]: e.target.value }))}
                  disabled={!isAdmin}
                  inputMode={f.kind === "number" ? "decimal" : "text"}
                />
              )}
              <p className="text-xs text-(--color-muted)">{f.hint}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      {error && <StatusBanner kind="error">{error}</StatusBanner>}
      {success && <StatusBanner kind="success">{success}</StatusBanner>}

      {isAdmin && (
        <div className="flex justify-end">
          <Button
            onClick={() => {
              setError(null);
              setSuccess(null);
              mutation.mutate();
            }}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Salvataggio…" : "Salva"}
          </Button>
        </div>
      )}
      {!isAdmin && (
        <p className="text-xs text-(--color-muted)">
          Solo gli amministratori possono modificare queste impostazioni.
        </p>
      )}
    </div>
  );
}
