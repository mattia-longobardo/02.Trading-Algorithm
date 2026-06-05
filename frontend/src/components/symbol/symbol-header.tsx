"use client";

import { Badge } from "@/components/ui/badge";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import { pnlClass } from "@/components/trades/trade-row";
import type { LivePosition, Trade, TradeCategory } from "@/lib/types";

interface SymbolHeaderProps {
  symbol: string;
  category: TradeCategory;
  livePosition?: LivePosition;
  openTrade?: Trade;
}

function categoryVariant(category: TradeCategory): "default" | "muted" {
  return category === "CRYPTO" ? "default" : "muted";
}

export function SymbolHeader({ symbol, category, livePosition, openTrade }: SymbolHeaderProps) {
  // Prefer live data; fall back to the open trade's current/entry price.
  const currentPrice =
    livePosition?.current_price ?? openTrade?.current_price ?? openTrade?.entry_price ?? null;

  const unrealizedPnl =
    livePosition?.unrealized_pnl ?? openTrade?.unrealized_pnl ?? null;
  const unrealizedPct =
    livePosition?.unrealized_pnl_pct ?? null;

  const hasPnl = unrealizedPnl !== null;
  const pnlValue = unrealizedPnl ?? 0;

  return (
    <div className="flex flex-wrap items-start gap-4">
      {/* Symbol + category */}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold leading-tight">{symbol}</h1>
          <Badge variant={categoryVariant(category)}>{category}</Badge>
        </div>

        {/* Prices */}
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
          {currentPrice !== null && (
            <span className="tnum font-medium">
              {formatNumber(currentPrice, { maximumFractionDigits: 4 })}
            </span>
          )}

          {hasPnl && (
            <span className={`tnum ${pnlClass(pnlValue)}`}>
              {pnlValue > 0 ? "+" : ""}
              {formatCurrency(pnlValue, openTrade?.account_currency ?? "EUR")}
              {unrealizedPct !== null && (
                <span className="ml-1 text-xs opacity-80">
                  ({unrealizedPct > 0 ? "+" : ""}
                  {formatPercent(unrealizedPct)})
                </span>
              )}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
