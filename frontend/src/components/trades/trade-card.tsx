"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatCurrency, formatDateTime, formatNumber, formatSignedPercent } from "@/lib/format";
import { type Trade } from "@/lib/types";
import {
  isTradeActionable,
  isTradeEditable,
  pnlClass,
  statusVariant,
  tradePnl,
  tradePnlPct,
} from "./trade-row";

export interface TradeCardProps {
  trade: Trade;
  onEdit: (t: Trade) => void;
  onClose: (t: Trade) => void;
}

export function TradeCard({ trade: t, onEdit, onClose }: TradeCardProps) {
  const [expanded, setExpanded] = useState(false);

  const ttpArmed = t.trailing_take_profit_price != null && t.high_water_mark != null;
  const tsArmed = t.trailing_stop_price != null;
  const pnl = tradePnl(t);
  const pnlPct = tradePnlPct(t);

  const isActionable = isTradeActionable(t);
  const isEditable = isTradeEditable(t);
  const closeLabel = t.status === "PENDING" ? "Annulla" : "Chiudi";

  return (
    <div className="rounded-lg border border-(--color-line) bg-(--color-panel)/40 p-3 text-sm">
      {/* Collapsed header row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Link
            href={`/symbol/${encodeURIComponent(t.symbol)}`}
            className="truncate font-medium hover:underline"
            title={t.symbol}
          >
            {t.symbol}
          </Link>
          <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
          <span className="text-xs text-(--color-muted)">{t.category}</span>
        </div>
        <span className={`tnum flex shrink-0 flex-col items-end font-medium ${pnlClass(pnl)}`}>
          <span>{formatCurrency(pnl, t.account_currency || "EUR")}</span>
          {pnlPct != null && (
            <span className="text-xs">{formatSignedPercent(pnlPct)}</span>
          )}
        </span>
      </div>

      {/* Toggle button */}
      <div className="mt-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-(--color-muted) hover:text-(--color-text)"
          aria-expanded={expanded}
          aria-controls={`trade-card-detail-${t.id}`}
        >
          {expanded ? (
            <>Nascondi dettagli <span aria-hidden="true">▲</span></>
          ) : (
            <>Dettagli <span aria-hidden="true">▼</span></>
          )}
        </button>
      </div>

      {/* Expanded detail section */}
      {expanded && (
        <dl id={`trade-card-detail-${t.id}`} className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          <div>
            <dt className="text-(--color-muted)">Dir.</dt>
            <dd>{t.direction}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Entry</dt>
            <dd className="tnum">{formatNumber(t.entry_price)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Uscita</dt>
            <dd className="tnum">{formatNumber(t.close_price)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Target Entry</dt>
            <dd className="tnum">{formatNumber(t.target_entry_price)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Qty</dt>
            <dd className="tnum">{formatNumber(t.quantity)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Capitale</dt>
            <dd className="tnum">{formatCurrency(t.allocated_capital, t.account_currency || "EUR")}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">TP</dt>
            <dd className="tnum">{formatNumber(t.take_profit)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">SL</dt>
            <dd className="tnum">{formatNumber(t.stop_loss)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">TTP dist</dt>
            <dd className="tnum">{formatNumber(t.trailing_take_profit_distance)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">TTP arm%</dt>
            <dd className="tnum">{formatNumber(t.trailing_take_profit_activation_pct)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">TTP trigger</dt>
            <dd
              className={`tnum ${ttpArmed ? "text-(--color-accent)" : "text-(--color-muted)"}`}
              title={ttpArmed ? "Trailing TP armato" : "Trailing TP non ancora armato"}
            >
              {formatNumber(t.trailing_take_profit_price)}
            </dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">HWM</dt>
            <dd className="tnum">{formatNumber(t.high_water_mark)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">TS dist</dt>
            <dd className="tnum">{formatNumber(t.trailing_stop_distance)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">TS trigger</dt>
            <dd
              className={`tnum ${tsArmed ? "text-(--color-danger)" : "text-(--color-muted)"}`}
              title={tsArmed ? "Trailing stop armato" : "Trailing stop non ancora armato"}
            >
              {formatNumber(t.trailing_stop_price)}
            </dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Prezzo</dt>
            <dd className="tnum">{formatNumber(t.current_price)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Motivo</dt>
            <dd>{t.close_reason ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Aperto</dt>
            <dd>{formatDateTime(t.open_timestamp ?? t.created_at)}</dd>
          </div>
          <div>
            <dt className="text-(--color-muted)">Chiuso</dt>
            <dd>{t.close_timestamp ? formatDateTime(t.close_timestamp) : "—"}</dd>
          </div>
        </dl>
      )}

      {/* Footer actions stay visible; inactive states are disabled. */}
      <div className="mt-3 flex justify-end gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={!isEditable}
          onClick={() => {
            if (isEditable) onEdit(t);
          }}
        >
          Modifica
        </Button>
        <Button
          size="sm"
          variant={isActionable ? "danger" : "secondary"}
          disabled={!isActionable}
          onClick={() => {
            if (isActionable) onClose(t);
          }}
        >
          {closeLabel}
        </Button>
      </div>
    </div>
  );
}
