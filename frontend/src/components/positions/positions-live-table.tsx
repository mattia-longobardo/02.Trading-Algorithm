"use client";

import Link from "next/link";
import { TrendingDown } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
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
      aria-label={isBuy ? "Long" : "Short"}
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

function PositionCard({ pos }: { pos: LivePosition }) {
  const pnl = pos.unrealized_pnl;
  const pnlPct = pos.unrealized_pnl_pct;
  return (
    <div className="rounded-xl border border-(--color-line) bg-(--color-panel)/40 p-3">
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-1 font-medium">
          <Link href={`/symbol/${encodeURIComponent(pos.symbol)}`} className="hover:underline">
            {pos.symbol}
          </Link>
          <DirectionHint isBuy={pos.is_buy} />
        </span>
        <span className={`tnum text-right text-sm font-semibold ${pnlClass(pnl ?? 0)}`}>
          {signedPnl(pnl)} <span className={`text-xs font-normal ${pnlClass(pnlPct ?? 0)}`}>({signedPct(pnlPct)})</span>
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-(--color-muted)">
        <div className="flex justify-between"><dt>Qtà</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.units)}</dd></div>
        <div className="flex justify-between"><dt>Ultimo</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.current_price)}</dd></div>
        <div className="flex justify-between"><dt>Entry</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.entry_price)}</dd></div>
        <div className="flex justify-between"><dt>TP</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.take_profit)}</dd></div>
        <div className="flex justify-between"><dt>SL</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.stop_loss)}</dd></div>
      </dl>
    </div>
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
          <Link
            href={`/symbol/${encodeURIComponent(pos.symbol)}`}
            className="hover:underline"
          >
            {pos.symbol}
          </Link>
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

export function PositionsLiveTable({
  positions,
  loading,
}: {
  positions: LivePosition[];
  loading?: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full rounded-lg" />
        ))}
      </div>
    );
  }

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
    <>
      {/* Phone: stacked cards (no horizontal scroll) */}
      <div data-testid="positions-card-list" className="space-y-2 md:hidden">
        {positions.map((pos) => (
          <PositionCard key={pos.id} pos={pos} />
        ))}
      </div>

      {/* Tablet/desktop: full table */}
      <div className="hidden overflow-x-auto rounded-xl border border-(--color-line) md:block">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="border-b border-(--color-line) bg-(--color-panel)/60">
              {HEADERS.map((h) => (
                <th
                  key={h}
                  scope="col"
                  className={`px-2 py-2 text-xs font-medium text-(--color-muted) ${
                    h === "Simbolo" ? "sticky left-0 z-10 bg-(--color-panel) text-left" : "text-right"
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
    </>
  );
}
