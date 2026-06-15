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
    <div className="overflow-x-auto rounded-xl border border-(--color-line)">
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
  );
}
