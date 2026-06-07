"use client";

import { formatCurrency } from "@/lib/format";

export interface ExposureConcentrationCardProps {
  exposure: number; // 0-1
  equity: number;
  cash: number | null;
  nEff: number;
  avgCorrelation: number;
  hhi: number;
  currency: string;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-(--color-muted)" title={hint}>{label}</dt>
      <dd className="tnum font-medium text-(--color-text)">{value}</dd>
    </div>
  );
}

export function ExposureConcentrationCard({
  exposure, equity, cash, nEff, avgCorrelation, hhi, currency,
}: ExposureConcentrationCardProps) {
  const invested = equity * exposure;
  const expPct = Math.max(0, Math.min(100, exposure * 100));
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="flex items-center justify-between">
          <span className="text-(--color-muted)">Esposizione</span>
          <span className="tnum font-semibold text-(--color-text)">{expPct.toFixed(1)}%</span>
        </div>
        <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-(--color-line)">
          <div className="h-full rounded-full bg-(--color-info)" style={{ width: `${expPct}%` }} />
        </div>
        <p className="mt-1 text-xs text-(--color-muted)">
          Investito <span className="tnum">{formatCurrency(invested, currency)}</span> su equity{" "}
          <span className="tnum">{formatCurrency(equity, currency)}</span>
        </p>
      </div>
      <dl className="space-y-1.5">
        <Stat label="Liquidità" value={cash != null ? formatCurrency(cash, currency) : "—"} />
        <Stat label="Posizioni efficaci (n_eff)" value={nEff.toFixed(1)} hint="1 / HHI: numero equivalente di posizioni indipendenti." />
        <Stat label="Concentrazione (HHI)" value={hhi.toFixed(2)} hint="Herfindahl-Hirschman: 1 = tutto in una posizione." />
        <Stat label="Correlazione media" value={avgCorrelation.toFixed(2)} hint="Correlazione media a coppie tra le posizioni." />
      </dl>
    </div>
  );
}
