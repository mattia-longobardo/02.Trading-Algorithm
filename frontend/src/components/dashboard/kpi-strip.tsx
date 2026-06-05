import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import type { Metrics } from "@/lib/types";

// ---------------------------------------------------------------------------
// Kpi — single metric tile
// ---------------------------------------------------------------------------
function Kpi({
  title,
  value,
  subtitle,
  accent,
}: {
  title: string;
  value: string;
  subtitle?: string;
  accent?: "positive" | "negative";
}) {
  const tone =
    accent === "positive"
      ? "text-emerald-400"
      : accent === "negative"
      ? "text-rose-400"
      : "text-(--color-text)";
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wide text-(--color-muted)">{title}</p>
      <p className={`tnum mt-1 text-xl font-semibold tabular-nums ${tone}`}>{value}</p>
      {subtitle && <p className="tnum mt-1 text-xs tabular-nums text-(--color-muted)">{subtitle}</p>}
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
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-6">
        {Array.from({ length: 11 }).map((_, i) => (
          <Card key={i} className="p-4">
            <Skeleton className="h-3 w-16" />
            <Skeleton className="mt-2 h-6 w-24" />
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4 xl:grid-cols-6">
      <Kpi
        title="PnL totale"
        value={formatCurrency(m?.total_pnl_abs, m?.currency ?? "EUR")}
        accent={(m?.total_pnl_abs ?? 0) >= 0 ? "positive" : "negative"}
        subtitle={formatPercent(m?.total_pnl_pct)}
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
    </div>
  );
}
