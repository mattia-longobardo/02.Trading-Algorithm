"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatCurrency, formatDateTime, formatNumber } from "@/lib/format";
import { type Trade } from "@/lib/types";

export function statusVariant(
  status: string
): "open" | "pending" | "closed" | "cancelled" | "default" {
  switch (status) {
    case "OPEN":
      return "open";
    case "PENDING":
      return "pending";
    case "CLOSED":
      return "closed";
    case "CANCELLED":
      return "cancelled";
    default:
      return "default";
  }
}

export function pnlClass(value: number): string {
  if (value > 0) return "text-(--color-accent)";
  if (value < 0) return "text-(--color-danger)";
  return "text-(--color-text)";
}

interface TradeRowProps {
  trade: Trade;
  onEdit: (t: Trade) => void;
  onClose: (t: Trade) => void;
}

export function TradeRow({ trade: t, onEdit, onClose }: TradeRowProps) {
  const ttpArmed = t.trailing_take_profit_price != null && t.high_water_mark != null;
  const tsArmed = t.trailing_stop_price != null;
  const pnl = (t.realized_pnl ?? 0) + (t.unrealized_pnl ?? 0);

  return (
    <tr className="bg-(--color-panel)/40 transition-colors hover:bg-(--color-hover)/60 [&>td]:border-y [&>td]:border-(--color-line)">
      {/* Sticky first column: symbol */}
      <td className="sticky left-0 z-10 bg-(--color-panel) px-2 py-2 font-medium">
        {t.symbol}
      </td>
      <td className="px-2 py-2 text-(--color-muted)">#{t.id}</td>
      <td className="px-2 py-2">
        <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
      </td>
      <td className="px-2 py-2 text-(--color-muted)">{t.category}</td>
      <td className="px-2 py-2 text-(--color-muted)">{t.direction}</td>
      <td className="tnum px-2 py-2 text-right">{formatNumber(t.entry_price)}</td>
      <td className="tnum px-2 py-2 text-right">{formatNumber(t.target_entry_price)}</td>
      <td className="tnum px-2 py-2 text-right">{formatNumber(t.quantity)}</td>
      <td className="tnum px-2 py-2 text-right">
        {formatCurrency(t.allocated_capital, t.account_currency || "EUR")}
      </td>
      <td className="tnum px-2 py-2 text-right">{formatNumber(t.take_profit)}</td>
      <td className="tnum px-2 py-2 text-right">
        {formatNumber(t.trailing_take_profit_distance)}
      </td>
      <td className="tnum px-2 py-2 text-right">
        {formatNumber(t.trailing_take_profit_activation_pct)}
      </td>
      <td
        className={`tnum px-2 py-2 text-right ${
          ttpArmed ? "text-(--color-accent)" : "text-(--color-muted)"
        }`}
        title={ttpArmed ? "Trailing TP armato" : "Trailing TP non ancora armato"}
      >
        {formatNumber(t.trailing_take_profit_price)}
      </td>
      <td className="tnum px-2 py-2 text-right">{formatNumber(t.high_water_mark)}</td>
      <td className="tnum px-2 py-2 text-right">{formatNumber(t.stop_loss)}</td>
      <td className="tnum px-2 py-2 text-right">{formatNumber(t.trailing_stop_distance)}</td>
      <td
        className={`tnum px-2 py-2 text-right ${
          tsArmed ? "text-(--color-danger)" : "text-(--color-muted)"
        }`}
        title={tsArmed ? "Trailing stop armato" : "Trailing stop non ancora armato"}
      >
        {formatNumber(t.trailing_stop_price)}
      </td>
      <td className="tnum px-2 py-2 text-right">{formatNumber(t.current_price)}</td>
      <td className={`tnum px-2 py-2 text-right ${pnlClass(pnl)}`}>
        {formatCurrency(pnl, t.account_currency || "EUR")}
      </td>
      <td className="px-2 py-2 text-(--color-muted)">{t.close_reason ?? "—"}</td>
      <td className="px-2 py-2 text-(--color-muted)">
        {formatDateTime(t.open_timestamp ?? t.created_at)}
      </td>
      <td className="px-2 py-2 text-(--color-muted)">
        {t.close_timestamp ? formatDateTime(t.close_timestamp) : "—"}
      </td>
      <td className="px-2 py-2 text-right">
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="secondary" onClick={() => onEdit(t)}>
            Modifica
          </Button>
          {(t.status === "PENDING" || t.status === "OPEN") && (
            <Button size="sm" variant="danger" onClick={() => onClose(t)}>
              {t.status === "PENDING" ? "Annulla" : "Chiudi"}
            </Button>
          )}
        </div>
      </td>
    </tr>
  );
}
