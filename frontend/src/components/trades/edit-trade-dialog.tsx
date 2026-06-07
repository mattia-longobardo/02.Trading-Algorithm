"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import { type Trade } from "@/lib/types";

const EDITABLE_FIELDS: Array<{
  key: keyof Trade;
  label: string;
  hint: string;
}> = [
  {
    key: "target_entry_price",
    label: "Target entry",
    hint: "Prezzo desiderato per l'entrata. Per le crypto è il livello GPT; entry_price è invece il limit IOC inviato al broker.",
  },
  {
    key: "quantity",
    label: "Quantity",
    hint: "Numero di azioni o frazioni di crypto. Obbligatorio (>0).",
  },
  {
    key: "take_profit",
    label: "Take profit",
    hint: "Livello di chiusura in profitto. Quando viene raggiunto il bot chiude a mercato.",
  },
  {
    key: "trailing_take_profit_distance",
    label: "Trailing TP distance",
    hint: "Distanza assoluta dal massimo (high-water mark). Trailing TP attivo solo se entrambi i campi trailing TP sono valorizzati.",
  },
  {
    key: "trailing_take_profit_activation_pct",
    label: "Trailing TP activation %",
    hint: "Guadagno % oltre l'entry richiesto per armare il trailing TP. Esempio: 5 = +5% sopra entry.",
  },
  {
    key: "stop_loss",
    label: "Stop loss",
    hint: "Stop hard di chiusura in perdita.",
  },
  {
    key: "trailing_stop_distance",
    label: "Trailing stop distance",
    hint: "Distanza assoluta dal massimo per il trailing stop. Lascia vuoto se non vuoi un trailing stop.",
  },
  {
    key: "high_water_mark",
    label: "High-water mark",
    hint: "Massimo storico osservato dal bot, usato come riferimento per trailing TP/SL. Modificarlo \"resetta\" il trailing senza aspettare il prossimo tick.",
  },
];

interface EditTradeDialogProps {
  trade: Trade;
  onClose: () => void;
  onSaved: () => void;
}

export function EditTradeDialog({ trade, onClose, onSaved }: EditTradeDialogProps) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {};
    for (const f of EDITABLE_FIELDS) {
      const raw = trade[f.key];
      seed[f.key as string] = raw === null || raw === undefined ? "" : String(raw);
    }
    return seed;
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const body: Record<string, number | null> = {};
      for (const f of EDITABLE_FIELDS) {
        const raw = values[f.key as string];
        if (raw === "") {
          if (f.key === "quantity") {
            throw new Error("La quantità è obbligatoria");
          }
          body[f.key as string] = null;
        } else {
          const num = Number(raw);
          if (Number.isNaN(num)) {
            throw new Error(`${f.label} non è un numero valido`);
          }
          body[f.key as string] = num;
        }
      }
      return api.patch(`/api/trades/${trade.id}`, body);
    },
    onSuccess: onSaved,
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    },
  });

  return (
    <div>
      <DialogHeader>
        <DialogTitle>
          Modifica trade #{trade.id} — {trade.symbol}
        </DialogTitle>
        <DialogDescription>
          Solo i parametri editabili sono modificabili. La validazione del backend impedisce
          valori non positivi e applica la regola coppia per il trailing TP (entrambi
          valorizzati o entrambi vuoti).
        </DialogDescription>
      </DialogHeader>
      <form
        className="space-y-3 max-h-[60vh] overflow-y-auto pr-1"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          mutation.mutate();
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
          <Button type="submit" className="w-full sm:w-auto" disabled={mutation.isPending}>
            {mutation.isPending ? "Salvataggio…" : "Salva"}
          </Button>
        </div>
      </form>
    </div>
  );
}
