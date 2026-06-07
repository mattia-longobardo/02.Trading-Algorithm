"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import type { SettingsResponse } from "@/lib/types";

const FIELDS: Array<{ key: string; label: string; hint: string }> = [
  { key: "max_open_trades_stock", label: "Max posizioni stock", hint: "Slot massimi attivi su azioni." },
  { key: "max_open_trades_crypto", label: "Max posizioni crypto", hint: "Slot massimi attivi su crypto." },
  { key: "risk_tolerance", label: "Tolleranza al rischio (1–10)", hint: "1 = conservativo, 10 = aggressivo. Determina il budget di volatilità." },
];

export function RiskLimitsPanel({ isAdmin, budgetVol }: { isAdmin: boolean; budgetVol: number }) {
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
    for (const f of FIELDS) {
      const v = settings.data.values[f.key];
      seed[f.key] = v === null || v === undefined ? "" : String(v);
    }
    setDraft(seed);
  }, [settings.data]);

  const mutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, number> = {};
      for (const f of FIELDS) {
        const raw = draft[f.key];
        if (raw === "" || raw === undefined) continue;
        const num = Number(raw);
        if (Number.isNaN(num)) throw new Error(`${f.label} non valido`);
        payload[f.key] = num;
      }
      return api.patch<SettingsResponse>("/api/settings", payload);
    },
    onSuccess: () => {
      setSuccess("Limiti salvati.");
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["risk"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        {FIELDS.map((f) => (
          <div key={f.key} className="space-y-1">
            <label className="text-xs uppercase text-(--color-muted)">{f.label}</label>
            <Input
              value={draft[f.key] ?? ""}
              onChange={(e) => setDraft((p) => ({ ...p, [f.key]: e.target.value }))}
              disabled={!isAdmin}
              inputMode="decimal"
            />
            <p className="text-xs text-(--color-muted)">{f.hint}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-(--color-muted)">
        Budget di volatilità attuale (da tolleranza):{" "}
        <span className="tnum font-medium text-(--color-text)">{(budgetVol * 100).toFixed(0)}%</span> annualizzato.
      </p>

      {error && <StatusBanner kind="error">{error}</StatusBanner>}
      {success && <StatusBanner kind="success">{success}</StatusBanner>}

      {isAdmin ? (
        <div className="flex justify-end">
          <Button
            onClick={() => {
              setError(null);
              setSuccess(null);
              mutation.mutate();
            }}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Salvataggio…" : "Salva limiti"}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-(--color-muted)">Solo gli amministratori possono modificare i limiti.</p>
      )}
    </div>
  );
}
