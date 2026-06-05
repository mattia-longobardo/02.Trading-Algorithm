import { TrendingDown } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { formatNumber, formatPercent } from "@/lib/format";
import { pnlClass } from "@/components/trades/trade-row";
import type { LivePosition } from "@/lib/types";

function signedPnl(value: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatNumber(value, { maximumFractionDigits: 2 })}`;
}

function signedPct(value: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${formatPercent(value)}`;
}

function DirectionHint({ isBuy }: { isBuy: boolean }) {
  return (
    <span
      className={`ml-1 rounded px-1 py-0.5 text-[10px] font-medium ${
        isBuy
          ? "bg-(--color-accent)/15 text-(--color-accent)"
          : "bg-(--color-danger)/15 text-(--color-danger)"
      }`}
    >
      {isBuy ? "L" : "S"}
    </span>
  );
}

const HEADERS = ["Simbolo", "Qtà", "Entry", "Ultimo", "PnL", "PnL %", "TP", "SL"] as const;

function PositionRow({ pos }: { pos: LivePosition }) {
  const pnl = pos.unrealized_pnl;
  const pnlPct = pos.unrealized_pnl_pct;

  return (
    <tr className="bg-(--color-panel)/40 transition-colors hover:bg-(--color-hover)/60 [&>td]:border-y [&>td]:border-(--color-line)">
      {/* Simbolo — sticky */}
      <td className="sticky left-0 z-10 bg-(--color-panel) px-2 py-2 font-medium">
        <span className="inline-flex items-center gap-1">
          {pos.symbol}
          <DirectionHint isBuy={pos.is_buy} />
        </span>
      </td>

      {/* Qtà */}
      <td className="tnum px-2 py-2 text-right">{formatNumber(pos.units)}</td>

      {/* Entry */}
      <td className="tnum px-2 py-2 text-right">{formatNumber(pos.entry_price)}</td>

      {/* Ultimo (current_price) */}
      <td className="tnum px-2 py-2 text-right">{formatNumber(pos.current_price)}</td>

      {/* PnL */}
      <td
        className={`tnum px-2 py-2 text-right ${pnlClass(pnl ?? 0)}`}
      >
        {signedPnl(pnl)}
      </td>

      {/* PnL % */}
      <td
        className={`tnum px-2 py-2 text-right ${pnlClass(pnlPct ?? 0)}`}
      >
        {signedPct(pnlPct)}
      </td>

      {/* TP */}
      <td className="tnum px-2 py-2 text-right text-(--color-muted)">
        {formatNumber(pos.take_profit)}
      </td>

      {/* SL */}
      <td className="tnum px-2 py-2 text-right text-(--color-muted)">
        {formatNumber(pos.stop_loss)}
      </td>
    </tr>
  );
}

export function PositionsLiveTable({ positions }: { positions: LivePosition[] }) {
  if (positions.length === 0) {
    return (
      <EmptyState
        icon={TrendingDown}
        title="Nessuna posizione aperta"
        description="Non ci sono posizioni live al momento. I dati arrivano in tempo reale tramite SSE."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-(--color-line)">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-(--color-line) bg-(--color-panel)/60">
            {HEADERS.map((h) => (
              <th
                key={h}
                className={`px-2 py-2 text-xs font-medium text-(--color-muted) ${
                  h === "Simbolo" ? "sticky left-0 z-10 bg-(--color-panel)/60 text-left" : "text-right"
                }`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => (
            <PositionRow key={pos.id} pos={pos} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
