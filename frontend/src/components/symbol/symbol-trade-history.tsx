"use client";

import { ReceiptText } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatDateTime, formatNumber } from "@/lib/format";
import { pnlClass, statusVariant, tradePnl } from "@/components/trades/trade-row";
import type { Trade } from "@/lib/types";

const HEADERS = ["Stato", "Entry", "Chiusura/Corrente", "Qty", "PnL", "Aperto", "Chiuso"] as const;

function TradeHistoryRow({ trade: t }: { trade: Trade }) {
  const pnl = tradePnl(t);
  const closeOrCurrent = t.close_price ?? t.current_price;

  return (
    <tr className="bg-(--color-panel)/40 transition-colors hover:bg-(--color-hover)/60 [&>td]:border-y [&>td]:border-(--color-line)">
      {/* Status */}
      <td className="px-3 py-2">
        <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
      </td>

      {/* Entry */}
      <td className="tnum px-3 py-2 text-right">{formatNumber(t.entry_price)}</td>

      {/* Close / current */}
      <td className="tnum px-3 py-2 text-right">{formatNumber(closeOrCurrent)}</td>

      {/* Qty */}
      <td className="tnum px-3 py-2 text-right">{formatNumber(t.quantity)}</td>

      {/* PnL */}
      <td className={`tnum px-3 py-2 text-right ${pnlClass(pnl)}`}>
        {t.account_currency
          ? formatCurrency(pnl, t.account_currency)
          : formatNumber(pnl, { maximumFractionDigits: 2 })}
      </td>

      {/* Opened */}
      <td className="px-3 py-2 text-right text-(--color-muted)">
        {formatDateTime(t.open_timestamp ?? t.created_at)}
      </td>

      {/* Closed */}
      <td className="px-3 py-2 text-right text-(--color-muted)">
        {t.close_timestamp ? formatDateTime(t.close_timestamp) : "—"}
      </td>
    </tr>
  );
}

function TradeHistoryCard({ trade: t }: { trade: Trade }) {
  const pnl = tradePnl(t);
  const closeOrCurrent = t.close_price ?? t.current_price;

  return (
    <div className="rounded-lg border border-(--color-line) bg-(--color-panel)/40 p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
        <span className={`tnum text-right font-semibold ${pnlClass(pnl)}`}>
          {t.account_currency
            ? formatCurrency(pnl, t.account_currency)
            : formatNumber(pnl, { maximumFractionDigits: 2 })}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <div className="flex justify-between gap-2">
          <dt className="text-(--color-muted)">Entry</dt>
          <dd className="tnum text-(--color-text)">{formatNumber(t.entry_price)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-(--color-muted)">Chiusura/corr.</dt>
          <dd className="tnum text-(--color-text)">{formatNumber(closeOrCurrent)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-(--color-muted)">Qty</dt>
          <dd className="tnum text-(--color-text)">{formatNumber(t.quantity)}</dd>
        </div>
        <div className="flex justify-between gap-2">
          <dt className="text-(--color-muted)">Aperto</dt>
          <dd className="text-right text-(--color-text)">{formatDateTime(t.open_timestamp ?? t.created_at)}</dd>
        </div>
        <div className="col-span-2 flex justify-between gap-2">
          <dt className="text-(--color-muted)">Chiuso</dt>
          <dd className="text-right text-(--color-text)">
            {t.close_timestamp ? formatDateTime(t.close_timestamp) : "—"}
          </dd>
        </div>
      </dl>
    </div>
  );
}

export function SymbolTradeHistory({ trades }: { trades: Trade[] }) {
  if (trades.length === 0) {
    return (
      <EmptyState
        icon={ReceiptText}
        title="Nessun trade per questo simbolo"
        description="Non sono presenti trade registrati per questo simbolo."
      />
    );
  }

  return (
    <>
    <div className="space-y-2 md:hidden">
      {trades.map((t) => (
        <TradeHistoryCard key={t.id} trade={t} />
      ))}
    </div>
    <div className="hidden overflow-x-auto rounded-xl border border-(--color-line) md:block">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-(--color-line) bg-(--color-panel)/60">
            {HEADERS.map((h) => (
              <th
                key={h}
                scope="col"
                className={`px-3 py-2 text-xs font-medium text-(--color-muted) ${
                  h === "Stato" ? "text-left" : "text-right"
                }`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <TradeHistoryRow key={t.id} trade={t} />
          ))}
        </tbody>
      </table>
    </div>
    </>
  );
}
