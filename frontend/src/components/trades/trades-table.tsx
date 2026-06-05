"use client";

import { Inbox } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { type Trade } from "@/lib/types";
import { TradeRow } from "./trade-row";

interface TradesTableProps {
  items: Trade[];
  loading: boolean;
  onEdit: (t: Trade) => void;
  onClose: (t: Trade) => void;
}

export function TradesTable({ items, loading, onEdit, onClose }: TradesTableProps) {
  if (loading) return <p className="text-sm text-(--color-muted)">Caricamento…</p>;
  if (items.length === 0)
    return (
      <EmptyState
        icon={Inbox}
        title="Nessun trade"
        description="Nessun trade per i filtri selezionati. Allenta i filtri di stato/categoria o cerca un simbolo diverso."
      />
    );

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1200px] border-separate border-spacing-y-1 text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-(--color-muted)">
            {/* Sticky first column header */}
            <th className="sticky left-0 z-10 bg-(--color-panel) px-2 py-2">Simbolo</th>
            <th className="px-2 py-2">ID</th>
            <th className="px-2 py-2">Stato</th>
            <th className="px-2 py-2">Cat.</th>
            <th className="px-2 py-2">Dir.</th>
            <th className="px-2 py-2 text-right">Entry</th>
            <th className="px-2 py-2 text-right">Target</th>
            <th className="px-2 py-2 text-right">Qty</th>
            <th className="px-2 py-2 text-right">Capitale</th>
            <th className="px-2 py-2 text-right">TP</th>
            <th className="px-2 py-2 text-right">TTP dist</th>
            <th className="px-2 py-2 text-right">TTP arm%</th>
            <th className="px-2 py-2 text-right">TTP trigger</th>
            <th className="px-2 py-2 text-right">HWM</th>
            <th className="px-2 py-2 text-right">SL</th>
            <th className="px-2 py-2 text-right">TS dist</th>
            <th className="px-2 py-2 text-right">TS trigger</th>
            <th className="px-2 py-2 text-right">Prezzo</th>
            <th className="px-2 py-2 text-right">PnL</th>
            <th className="px-2 py-2">Motivo</th>
            <th className="px-2 py-2">Aperto</th>
            <th className="px-2 py-2">Chiuso</th>
            <th className="px-2 py-2 text-right"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => (
            <TradeRow key={t.id} trade={t} onEdit={onEdit} onClose={onClose} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
