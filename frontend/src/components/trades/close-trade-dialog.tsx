"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import { formatCurrency, formatNumber } from "@/lib/format";
import { type Trade } from "@/lib/types";
import { pnlClass, tradePnl } from "./trade-row";

interface CloseTradeDialogProps {
  trade: Trade;
  onClose: () => void;
  onDone: () => void;
}

export function CloseTradeDialog({ trade, onClose, onDone }: CloseTradeDialogProps) {
  const isPending = trade.status === "PENDING";
  const [error, setError] = useState<string | null>(null);
  const pnl = tradePnl(trade);

  const mutation = useMutation({
    mutationFn: () => api.post<{ trade: Trade }>(`/api/trades/${trade.id}/close`),
    onSuccess: onDone,
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    },
  });

  return (
    <div>
      <DialogHeader>
        <DialogTitle>
          {isPending ? "Annulla ordine pending" : "Chiudi trade a mercato"} — #{trade.id}{" "}
          {trade.symbol}
        </DialogTitle>
        <DialogDescription>
          {isPending
            ? "L'ordine pending verrà annullato presso il broker (se ancora aperto) e il trade marcato come CANCELLED con motivo MANUAL_CANCEL."
            : "Verrà inviato un ordine di chiusura a mercato. Il PnL si consoliderà non appena il broker conferma il fill (riconciliato dal job monitor_trades). Motivo: MANUAL_CLOSE."}
        </DialogDescription>
      </DialogHeader>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-md border border-(--color-line) bg-(--color-panel) p-2">
          <p className="text-(--color-muted)">Entry</p>
          <p className="tnum font-medium">{formatNumber(trade.entry_price)}</p>
        </div>
        <div className="rounded-md border border-(--color-line) bg-(--color-panel) p-2">
          <p className="text-(--color-muted)">Prezzo corrente</p>
          <p className="tnum font-medium">{formatNumber(trade.current_price)}</p>
        </div>
        <div className="rounded-md border border-(--color-line) bg-(--color-panel) p-2">
          <p className="text-(--color-muted)">Quantità</p>
          <p className="tnum font-medium">{formatNumber(trade.quantity)}</p>
        </div>
        <div className="rounded-md border border-(--color-line) bg-(--color-panel) p-2">
          <p className="text-(--color-muted)">PnL stimato</p>
          <p className={`tnum font-medium ${pnlClass(pnl)}`}>
            {formatCurrency(pnl, trade.account_currency || "EUR")}
          </p>
        </div>
      </div>
      {error && (
        <StatusBanner kind="error" className="mt-3">
          {error}
        </StatusBanner>
      )}
      <div className="mt-4 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
        <Button type="button" variant="secondary" className="w-full sm:w-auto" onClick={onClose}>
          Indietro
        </Button>
        <Button
          variant="danger"
          className="w-full sm:w-auto"
          disabled={mutation.isPending}
          onClick={() => {
            setError(null);
            mutation.mutate();
          }}
        >
          {mutation.isPending
            ? "Invio…"
            : isPending
              ? "Conferma annullamento"
              : "Conferma chiusura"}
        </Button>
      </div>
    </div>
  );
}
