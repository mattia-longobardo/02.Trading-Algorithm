"use client";

import type { RiskComponents } from "@/lib/types";

const ROWS: Array<{ key: keyof RiskComponents; label: string; hint: string }> = [
  { key: "vol", label: "Volatilità", hint: "Volatilità di portfolio rispetto al budget di rischio." },
  { key: "concentration", label: "Concentrazione", hint: "Quanto il capitale è concentrato in poche posizioni (HHI)." },
  { key: "correlation", label: "Correlazione", hint: "Correlazione media tra le posizioni: alta = poca diversificazione." },
  { key: "exposure", label: "Esposizione", hint: "Capitale investito rispetto all'equity totale." },
];

function clamp(v: number): number {
  return Math.max(0, Math.min(100, v));
}

export function RiskComponentsBreakdown({ components }: { components: RiskComponents }) {
  return (
    <ul className="space-y-3">
      {ROWS.map((r) => {
        const value = components[r.key] ?? 0;
        const w = clamp(value);
        return (
          <li key={r.key}>
            <div className="flex items-center justify-between text-sm">
              <span className="text-(--color-text)" title={r.hint}>{r.label}</span>
              <span className="tnum text-(--color-muted)">{Math.round(value)}</span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-(--color-line)">
              <div
                data-testid={`risk-bar-${r.key}`}
                className="h-full rounded-full bg-(--color-accent)"
                style={{ width: `${w}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
