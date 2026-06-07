"use client";

import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/format";
import type { RiskPositionRow } from "@/lib/risk";
import type { Trade } from "@/lib/types";

function CoverageBadge({ active, label, title }: { active: boolean; label: string; title: string }) {
  return (
    <span
      title={title}
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
        active
          ? "bg-(--color-accent)/15 text-(--color-accent)"
          : "bg-(--color-line) text-(--color-muted) line-through"
      }`}
    >
      {label}
    </span>
  );
}

function Coverage({ row }: { row: RiskPositionRow }) {
  const t = row.trade;
  return (
    <div className="flex flex-wrap gap-1">
      <CoverageBadge active={row.stop.hasHardStop} label="SL" title="Stop loss hard" />
      <CoverageBadge active={row.stop.hasTrailingStop} label="SL trail" title="Trailing stop" />
      <CoverageBadge active={t.take_profit != null} label="TP" title="Take profit" />
      <CoverageBadge active={t.trailing_take_profit_distance != null} label="TP trail" title="Trailing take profit" />
    </div>
  );
}

function StopCell({ row }: { row: RiskPositionRow }) {
  if (row.stop.unprotected) {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-(--color-danger)/15 px-1.5 py-0.5 text-xs font-medium text-(--color-danger)">
        <ShieldAlert className="size-3" /> Scoperta
      </span>
    );
  }
  const d = row.stop.distancePct;
  const near = d != null && d <= 3;
  return (
    <span className="tnum text-xs">
      {row.stop.effectiveStop != null ? formatNumber(row.stop.effectiveStop) : "—"}
      {d != null && (
        <span className={`ml-1 ${near ? "text-(--color-danger)" : "text-(--color-muted)"}`}>
          ({d.toFixed(1)}%)
        </span>
      )}
    </span>
  );
}

const HEADERS = ["Simbolo", "Valore", "Quota", "Protezioni", "Stop / dist.", ""] as const;

export function PositionsRiskTable({
  rows,
  onEdit,
}: {
  rows: RiskPositionRow[];
  onEdit: (trade: Trade) => void;
}) {
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Nessuna posizione aperta"
        description="Quando il bot aprirà posizioni, qui vedrai le protezioni (SL/TP/trailing) e la distanza dallo stop."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-(--color-line)">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-(--color-line) bg-(--color-panel)/60">
            {HEADERS.map((h, i) => (
              <th
                key={h || `c${i}`}
                scope="col"
                className="px-2 py-2 text-left text-xs font-medium text-(--color-muted)"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.trade.id}
              className="bg-(--color-panel)/40 transition-colors hover:bg-(--color-hover)/60 [&>td]:border-y [&>td]:border-(--color-line)"
            >
              <td className="px-2 py-2 font-medium">
                <Link href={`/symbol/${encodeURIComponent(row.live.symbol)}`} className="hover:underline">
                  {row.live.symbol}
                </Link>
              </td>
              <td className="tnum px-2 py-2">{formatNumber(row.value, { maximumFractionDigits: 0 })}</td>
              <td className="tnum px-2 py-2 text-(--color-muted)">{row.valuePct.toFixed(1)}%</td>
              <td className="px-2 py-2"><Coverage row={row} /></td>
              <td className="px-2 py-2"><StopCell row={row} /></td>
              <td className="px-2 py-2 text-right">
                <Button variant="secondary" className="h-7 px-2 text-xs" onClick={() => onEdit(row.trade)}>
                  Modifica
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
