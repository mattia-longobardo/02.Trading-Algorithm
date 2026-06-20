"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { StatusBanner } from "@/components/ui/status-banner";
import { api } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { type Trade } from "@/lib/types";

const EDITABLE_FIELDS: Array<{
  key: keyof Trade;
  label: string;
  hint: string;
}> = [
  {
    key: "take_profit",
    label: "Take profit",
    hint: "Livello futuro di chiusura in profitto. Quando viene raggiunto il bot chiude a mercato.",
  },
  {
    key: "stop_loss",
    label: "Stop loss",
    hint: "Stop futuro di chiusura in perdita.",
  },
  {
    key: "trailing_take_profit_activation_pct",
    label: "Trailing TP activation %",
    hint: "Guadagno % oltre l'entry richiesto per armare il trailing TP. Esempio: 5 = +5% sopra entry.",
  },
  {
    key: "trailing_take_profit_distance",
    label: "Trailing TP distance",
    hint: "Distanza assoluta dal massimo futuro per il trailing TP. Trailing TP attivo solo se entrambi i campi trailing TP sono valorizzati.",
  },
  {
    key: "trailing_stop_distance",
    label: "Trailing stop distance",
    hint: "Distanza assoluta dal massimo futuro per il trailing stop. Lascia vuoto se non vuoi un trailing stop.",
  },
];

interface EditTradeDialogProps {
  trade: Trade;
  onClose: () => void;
  onSaved: () => void;
}

export function EditTradeDialog({ trade, onClose, onSaved }: EditTradeDialogProps) {
  const toast = useToast();
  const [values, setValues] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {};
    for (const f of EDITABLE_FIELDS) {
      const raw = trade[f.key];
      seed[f.key as string] = raw === null || raw === undefined ? "" : String(raw);
    }
    return seed;
  });
  const [error, setError] = useState<string | null>(null);

  function submit() {
    try {
      const body: Record<string, number | null> = {};
      for (const f of EDITABLE_FIELDS) {
        const raw = values[f.key as string];
        if (raw === "") {
          body[f.key as string] = null;
        } else {
          const num = Number(raw);
          if (Number.isNaN(num)) {
            throw new Error(`${f.label} non è un numero valido`);
          }
          body[f.key as string] = num;
        }
      }
      const promise = api.patch(`/api/trades/${trade.id}`, body);
      onClose();
      void toast
        .track(promise, {
          loading: `Salvataggio trade #${trade.id} in corso`,
          success: `Trade #${trade.id} aggiornato`,
          error: `Salvataggio trade #${trade.id} fallito`,
          description: trade.symbol,
        })
        .then(onSaved)
        .catch(() => {});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Valori non validi");
    }
  }

  return (
    <div>
      <DialogHeader>
        <DialogTitle>
          Modifica trade #{trade.id} — {trade.symbol}
        </DialogTitle>
        <DialogDescription>
          Puoi modificare solo decisioni future di uscita e protezione. Prezzo di entrata,
          quantità, capitale, massimo osservato e dati broker restano bloccati.
        </DialogDescription>
      </DialogHeader>
      <form
        className="space-y-3 max-h-[60vh] overflow-y-auto pr-1"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          submit();
        }}
      >
        {EDITABLE_FIELDS.map((f) => (
          <div key={f.key as string} className="space-y-1">
            <label className="flex items-center justify-between text-xs uppercase text-(--color-muted)">
              <span>{f.label}</span>
              <span className="lowercase normal-case">{f.key}</span>
            </label>
            <Input
              inputMode="decimal"
              className="text-base"
              value={values[f.key as string] ?? ""}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [f.key as string]: e.target.value }))
              }
              placeholder="—"
            />
            <p className="text-xs text-(--color-muted)">{f.hint}</p>
          </div>
        ))}
        {error && <StatusBanner kind="error">{error}</StatusBanner>}
        <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" className="w-full sm:w-auto" onClick={onClose}>
            Annulla
          </Button>
          <Button type="submit" className="w-full sm:w-auto">
            Salva
          </Button>
        </div>
      </form>
    </div>
  );
}
