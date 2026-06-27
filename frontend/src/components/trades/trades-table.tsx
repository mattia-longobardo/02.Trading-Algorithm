"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronsUpDown, ChevronUp, Inbox } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { type Trade } from "@/lib/types";
import { TradeCard } from "./trade-card";
import { TradeRow, tradePnl, tradePnlPct } from "./trade-row";

interface TradesTableProps {
  items: Trade[];
  loading: boolean;
  onEdit: (t: Trade) => void;
  onClose: (t: Trade) => void;
}

type SortValue = string | number | null | undefined;
type SortDir = "asc" | "desc";

interface ColumnDef {
  key: string;
  label: string;
  align?: "left" | "center" | "right";
  stickyClass?: string;
  /** Returns a comparable value for sorting; omit to make the column non-sortable. */
  accessor?: (t: Trade) => SortValue;
}

function ts(value: string | null | undefined): number | null {
  if (!value) return null;
  const n = new Date(value).getTime();
  return Number.isNaN(n) ? null : n;
}

// Column order MUST stay in sync with the cells rendered by <TradeRow>.
const COLUMNS: ColumnDef[] = [
  {
    key: "close_action",
    label: "Chiudi",
    align: "center",
    stickyClass: "sticky left-0 top-0 z-40 w-14 min-w-14 bg-(--color-panel)",
  },
  {
    key: "edit_action",
    label: "Mod.",
    align: "center",
    stickyClass: "sticky left-14 top-0 z-40 w-14 min-w-14 bg-(--color-panel)",
  },
  {
    key: "symbol",
    label: "Simbolo",
    stickyClass: "sticky left-28 top-0 z-40 w-40 min-w-40 bg-(--color-panel)",
    accessor: (t) => t.symbol,
  },
  { key: "status", label: "Stato", accessor: (t) => t.status },
  { key: "pnl", label: "PnL", align: "right", accessor: (t) => tradePnl(t) },
  { key: "pnl_pct", label: "PnL %", align: "right", accessor: (t) => tradePnlPct(t) },
  { key: "price", label: "Prezzo att.", align: "right", accessor: (t) => t.current_price },
  { key: "opened", label: "Aperto", accessor: (t) => ts(t.open_timestamp ?? t.created_at) },
  { key: "entry", label: "Entry", align: "right", accessor: (t) => t.entry_price },
  { key: "exit", label: "Uscita", align: "right", accessor: (t) => t.close_price },
  { key: "closed", label: "Chiuso", accessor: (t) => ts(t.close_timestamp) },
  { key: "qty", label: "Qty", align: "right", accessor: (t) => t.quantity },
  { key: "capital", label: "Capitale", align: "right", accessor: (t) => t.allocated_capital },
  { key: "category", label: "Cat.", accessor: (t) => t.category },
  { key: "direction", label: "Dir.", accessor: (t) => t.direction },
  { key: "target", label: "Target", align: "right", accessor: (t) => t.target_entry_price },
  { key: "tp", label: "TP", align: "right", accessor: (t) => t.take_profit },
  { key: "sl", label: "SL", align: "right", accessor: (t) => t.stop_loss },
  { key: "ttp_dist", label: "TTP dist", align: "right", accessor: (t) => t.trailing_take_profit_distance },
  { key: "ttp_arm", label: "TTP arm%", align: "right", accessor: (t) => t.trailing_take_profit_activation_pct },
  { key: "ttp_trigger", label: "TTP trigger", align: "right", accessor: (t) => t.trailing_take_profit_price },
  { key: "hwm", label: "HWM", align: "right", accessor: (t) => t.high_water_mark },
  { key: "ts_dist", label: "TS dist", align: "right", accessor: (t) => t.trailing_stop_distance },
  { key: "ts_trigger", label: "TS trigger", align: "right", accessor: (t) => t.trailing_stop_price },
  { key: "reason", label: "Motivo", accessor: (t) => t.close_reason },
  { key: "id", label: "ID", accessor: (t) => t.id },
  { key: "planned_reward_risk", label: "Plan RR", align: "right", accessor: (t) => t.planned_reward_risk },
  { key: "realized_r", label: "Real R", align: "right", accessor: (t) => t.realized_r },
  { key: "mfe", label: "MFE (R)", align: "right", accessor: (t) => t.mfe },
  { key: "mae", label: "MAE (R)", align: "right", accessor: (t) => t.mae },
];

function compareValues(a: SortValue, b: SortValue): number {
  const an = a == null;
  const bn = b == null;
  if (an && bn) return 0;
  if (an) return 1; // nulls always sort last
  if (bn) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "it");
}

export function TradesTable({ items, loading, onEdit, onClose }: TradesTableProps) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");

  const sorted = useMemo(() => {
    if (!sortKey) return items;
    const col = COLUMNS.find((c) => c.key === sortKey);
    if (!col?.accessor) return items;
    const dir = sortDir === "asc" ? 1 : -1;
    const accessor = col.accessor;
    return [...items].sort((a, b) => compareValues(accessor(a), accessor(b)) * dir);
  }, [items, sortKey, sortDir]);

  function toggleSort(key: string) {
    if (sortKey !== key) {
      setSortKey(key);
      setSortDir("asc");
    } else if (sortDir === "asc") {
      setSortDir("desc");
    } else {
      setSortKey(null); // third click clears the sort
      setSortDir("asc");
    }
  }

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
        {sorted.map((t) => (
          <TradeCard key={t.id} trade={t} onEdit={onEdit} onClose={onClose} />
        ))}
      </div>
      <div className="hidden max-h-[calc(100vh-12rem)] overflow-auto lg:block">
        <table className="w-full min-w-[1840px] border-separate border-spacing-y-1 text-sm">
          <thead>
            <tr className="text-left text-xs uppercase text-(--color-muted)">
              {COLUMNS.map((col) => {
                const active = sortKey === col.key;
                const thClass = [
                  "whitespace-nowrap px-3 py-2",
                  col.stickyClass ?? "sticky top-0 z-30 bg-(--color-panel)",
                  col.align === "center" ? "text-center" : "",
                  col.align === "right" ? "text-right" : "",
                ]
                  .filter(Boolean)
                  .join(" ");

                if (!col.accessor) {
                  return (
                    <th key={col.key} scope="col" className={thClass}>
                      {col.label}
                    </th>
                  );
                }

                const Icon = active
                  ? sortDir === "asc"
                    ? ChevronUp
                    : ChevronDown
                  : ChevronsUpDown;

                return (
                  <th key={col.key} scope="col" className={thClass} aria-sort={active ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
                    <button
                      type="button"
                      onClick={() => toggleSort(col.key)}
                      className={`inline-flex items-center gap-1 uppercase transition-colors hover:text-(--color-text) ${
                        col.align === "right" ? "flex-row-reverse" : ""
                      } ${active ? "text-(--color-text)" : ""}`}
                      title="Ordina"
                    >
                      <span>{col.label}</span>
                      <Icon className={`h-3 w-3 shrink-0 ${active ? "" : "opacity-40"}`} aria-hidden="true" />
                    </button>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => (
              <TradeRow key={t.id} trade={t} onEdit={onEdit} onClose={onClose} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
