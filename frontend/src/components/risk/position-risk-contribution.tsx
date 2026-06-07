"use client";

import Link from "next/link";

export function PositionRiskContribution({ contributions }: { contributions: Record<string, number> }) {
  const rows = Object.entries(contributions)
    .map(([symbol, pct]) => ({ symbol, pct }))
    .sort((a, b) => b.pct - a.pct);

  if (rows.length === 0) {
    return <p className="text-sm text-(--color-muted)">Nessun contributo di rischio (nessuna posizione aperta).</p>;
  }

  const max = Math.max(...rows.map((r) => Math.abs(r.pct)), 1);

  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.symbol} className="flex items-center gap-3 text-sm">
          <Link
            href={`/symbol/${encodeURIComponent(r.symbol)}`}
            data-testid="contrib-symbol"
            className="w-16 shrink-0 truncate font-medium hover:underline"
          >
            {r.symbol}
          </Link>
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-(--color-line)">
            <div
              className="h-full rounded-full bg-(--color-accent)"
              style={{ width: `${(Math.abs(r.pct) / max) * 100}%` }}
            />
          </div>
          <span className="tnum w-12 shrink-0 text-right text-(--color-muted)">{r.pct.toFixed(1)}%</span>
        </li>
      ))}
    </ul>
  );
}
