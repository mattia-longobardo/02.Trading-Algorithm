import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber, formatPercent, formatSignedPercent } from "@/lib/format";
import type { Metrics } from "@/lib/types";

// ---------------------------------------------------------------------------
// Kpi — single metric tile
// ---------------------------------------------------------------------------
function Kpi({
  title,
  value,
  subtitle,
  accent,
  subtitleProminent,
}: {
  title: string;
  value: string;
  subtitle?: string;
  accent?: "positive" | "negative";
  /** Render the subtitle (e.g. a percentage) large, bold and accent-colored. */
  subtitleProminent?: boolean;
}) {
  const tone =
    accent === "positive"
      ? "text-(--color-accent)"
      : accent === "negative"
      ? "text-(--color-danger)"
      : "text-(--color-text)";
  const subtitleClass = subtitleProminent
    ? `tnum mt-1 break-words text-lg font-semibold leading-tight tabular-nums ${tone}`
    : "tnum mt-1 break-words text-xs leading-tight tabular-nums text-(--color-muted)";
  return (
    <Card className="p-3 sm:p-4">
      <p className="text-xs uppercase text-(--color-muted)">{title}</p>
      <p className={`tnum mt-1 break-words text-xl font-semibold leading-tight tabular-nums ${tone}`}>
        {value}
      </p>
      {subtitle && <p className={subtitleClass}>{subtitle}</p>}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// KpiStrip — the full KPI grid
// ---------------------------------------------------------------------------
export interface KpiStripProps {
  metrics: Metrics | undefined;
  loading?: boolean;
}

export function KpiStrip({ metrics: m, loading }: KpiStripProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-3 min-[430px]:grid-cols-2 md:grid-cols-4 md:gap-4 xl:grid-cols-6">
        {Array.from({ length: 12 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-2 h-6 w-24" />
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3 min-[430px]:grid-cols-2 md:grid-cols-4 md:gap-4 xl:grid-cols-6">
      <Kpi
        title="PnL realizzato"
        value={formatCurrency(m?.total_pnl_abs, m?.currency ?? "EUR")}
        accent={(m?.total_pnl_abs ?? 0) >= 0 ? "positive" : "negative"}
        subtitle={formatSignedPercent(m?.total_pnl_pct)}
        subtitleProminent
      />
      <Kpi
        title="PnL non realizzato"
        value={formatCurrency(m?.unrealized_pnl_abs, m?.currency ?? "EUR")}
        accent={(m?.unrealized_pnl_abs ?? 0) >= 0 ? "positive" : "negative"}
      />
      <Kpi title="Win rate" value={formatPercent((m?.win_rate ?? 0) * 100)} />
      <Kpi
        title="Profit factor"
        value={formatNumber(m?.profit_factor, { maximumFractionDigits: 2 })}
      />
      <Kpi
        title="Max drawdown"
        value={formatCurrency(m?.max_drawdown, m?.currency ?? "EUR")}
        accent="negative"
      />
      <Kpi title="Sharpe" value={formatNumber(m?.sharpe, { maximumFractionDigits: 2 })} />
      <Kpi
        title="Equity account"
        value={formatCurrency(m?.account_equity, m?.currency ?? "EUR")}
        accent={(m?.account_return_abs ?? 0) >= 0 ? "positive" : "negative"}
        subtitle={
          m?.account_return_pct != null ? formatSignedPercent(m.account_return_pct) : undefined
        }
        subtitleProminent
      />
      <Kpi
        title="Avg win"
        value={formatCurrency(m?.avg_win, m?.currency ?? "EUR")}
        accent="positive"
      />
      <Kpi
        title="Avg loss"
        value={formatCurrency(m?.avg_loss, m?.currency ?? "EUR")}
        accent="negative"
      />
      <Kpi
        title="# Trade"
        value={m ? formatNumber(m.n_trades, { maximumFractionDigits: 0 }) : "—"}
      />
      <Kpi
        title="# Aperti"
        value={m ? formatNumber(m.n_open, { maximumFractionDigits: 0 }) : "—"}
      />
      <Kpi
        title="# Pending"
        value={m ? formatNumber(m.n_pending, { maximumFractionDigits: 0 }) : "—"}
      />
      <Kpi
        title="Captured R"
        value={m?.avg_captured_r != null ? m.avg_captured_r.toFixed(2) + "R" : "—"}
        subtitle={m?.avg_planned_rr != null ? `planned ${m.avg_planned_rr.toFixed(2)}R` : undefined}
      />
    </div>
  );
}
