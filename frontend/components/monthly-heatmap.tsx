"use client";

import type { MonthlyRow } from "@/lib/types";
import { fmtPctSigned, ND } from "@/lib/format";

const MONTH_LABELS = [
  "Gen",
  "Feb",
  "Mar",
  "Apr",
  "Mag",
  "Giu",
  "Lug",
  "Ago",
  "Set",
  "Ott",
  "Nov",
  "Dic",
];

/**
 * Scala divergente rosso da stampa → neutro → verde da stampa, midpoint a 0,
 * theme-aware via token (--positive / --negative) e color-mix.
 * L'intensità satura a ±8%; i numeri restano sempre leggibili nelle celle
 * (codifica secondaria: il colore non è mai l'unica informazione).
 */
function mix(token: string, v: number): string {
  const t = Math.min(Math.abs(v) / 8, 1);
  const pct = Math.round(8 + t * 34); // 8% → 42%: l'inchiostro resta leggibile
  return `color-mix(in srgb, var(${token}) ${pct}%, transparent)`;
}

function cellStyle(v: number | null): React.CSSProperties {
  if (v == null) return {};
  if (v === 0) return { backgroundColor: "var(--muted)" };
  return { backgroundColor: mix(v > 0 ? "--positive" : "--negative", v) };
}

/** Heatmap dei rendimenti mensili mese × anno (§12.2). */
export function MonthlyHeatmap({ rows }: { rows: MonthlyRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="text-muted-foreground py-8 text-center text-sm">
        Nessun rendimento mensile — arriveranno con i primi trade chiusi
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-separate border-spacing-0.5 text-xs">
        <thead>
          <tr>
            <th className="text-muted-foreground p-1.5 text-left font-mono text-[11px] font-medium tracking-[0.1em] uppercase">
              Anno
            </th>
            {MONTH_LABELS.map((m) => (
              <th
                key={m}
                className="text-muted-foreground p-1.5 text-right font-mono text-[11px] font-medium tracking-[0.1em] uppercase"
              >
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.year}>
              <td className="p-1.5 font-mono font-medium tabular-nums">
                {row.year}
              </td>
              {row.months.map((v, i) => (
                <td
                  key={i}
                  className="rounded-[3px] p-1.5 text-right font-mono tabular-nums"
                  style={cellStyle(v)}
                  title={
                    v == null
                      ? undefined
                      : `${MONTH_LABELS[i]} ${row.year}: ${fmtPctSigned(v)}`
                  }
                >
                  {v == null ? (
                    <span className="text-muted-foreground/50">{ND}</span>
                  ) : (
                    fmtPctSigned(v, 1)
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="text-muted-foreground mt-3 flex items-center gap-2 font-mono text-[10px] tracking-[0.08em] uppercase">
        <span>Perdita</span>
        <span className="border-border flex h-2 w-28 overflow-hidden rounded-[2px] border">
          <span className="flex-1" style={{ background: mix("--negative", 8) }} />
          <span className="flex-1" style={{ background: mix("--negative", 3) }} />
          <span className="flex-1" style={{ background: "var(--muted)" }} />
          <span className="flex-1" style={{ background: mix("--positive", 3) }} />
          <span className="flex-1" style={{ background: mix("--positive", 8) }} />
        </span>
        <span>Guadagno</span>
        <span className="ml-1 normal-case">(saturazione a ±8%)</span>
      </div>
    </div>
  );
}
