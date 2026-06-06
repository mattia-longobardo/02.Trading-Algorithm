"use client";

import { Inbox } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { type Trade } from "@/lib/types";
import { TradeCard } from "./trade-card";
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
    <>
      <div className="space-y-2 lg:hidden">
        {items.map((t) => (
          <TradeCard key={t.id} trade={t} onEdit={onEdit} onClose={onClose} />
        ))}
      </div>
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full min-w-[1200px] border-separate border-spacing-y-1 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-(--color-muted)">
              {/* Sticky first column header */}
              <th scope="col" className="sticky left-0 z-10 bg-(--color-panel) px-2 py-2">Simbolo</th>
              <th scope="col" className="px-2 py-2">ID</th>
              <th scope="col" className="px-2 py-2">Stato</th>
              <th scope="col" className="px-2 py-2">Cat.</th>
              <th scope="col" className="px-2 py-2">Dir.</th>
              <th scope="col" className="px-2 py-2 text-right">Entry</th>
              <th scope="col" className="px-2 py-2 text-right">Target</th>
              <th scope="col" className="px-2 py-2 text-right">Qty</th>
              <th scope="col" className="px-2 py-2 text-right">Capitale</th>
              <th scope="col" className="px-2 py-2 text-right">TP</th>
              <th scope="col" className="px-2 py-2 text-right">TTP dist</th>
              <th scope="col" className="px-2 py-2 text-right">TTP arm%</th>
              <th scope="col" className="px-2 py-2 text-right">TTP trigger</th>
              <th scope="col" className="px-2 py-2 text-right">HWM</th>
              <th scope="col" className="px-2 py-2 text-right">SL</th>
              <th scope="col" className="px-2 py-2 text-right">TS dist</th>
              <th scope="col" className="px-2 py-2 text-right">TS trigger</th>
              <th scope="col" className="px-2 py-2 text-right">Prezzo</th>
              <th scope="col" className="px-2 py-2 text-right">PnL</th>
              <th scope="col" className="px-2 py-2">Motivo</th>
              <th scope="col" className="px-2 py-2">Aperto</th>
              <th scope="col" className="px-2 py-2">Chiuso</th>
              <th scope="col" className="px-2 py-2 text-right"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <TradeRow key={t.id} trade={t} onEdit={onEdit} onClose={onClose} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
