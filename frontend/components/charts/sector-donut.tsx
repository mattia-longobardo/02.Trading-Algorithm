"use client";

import * as React from "react";
import { Pie, PieChart } from "recharts";

import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";
import type { Position } from "@/lib/types";
import { fmtPct } from "@/lib/format";
import { useDisplay } from "@/lib/money";

const PALETTE = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
];

const MAX_SLICES = 5; // 5 colori validati: oltre, i settori minori confluiscono in "Altro"

interface Slice {
  sector: string;
  value: number;
  fill: string;
}

function buildSlices(positions: Position[]): Slice[] {
  const bySector = new Map<string, number>();
  for (const p of positions) {
    const sector = p.sector ?? "Sconosciuto";
    const value = p.amount_usd + (p.unrealized_pnl_usd ?? 0);
    bySector.set(sector, (bySector.get(sector) ?? 0) + value);
  }
  const sorted = [...bySector.entries()].sort((a, b) => b[1] - a[1]);
  const head = sorted.slice(0, MAX_SLICES - (sorted.length > MAX_SLICES ? 1 : 0));
  const tail = sorted.slice(head.length);
  const slices: Slice[] = head.map(([sector, value], i) => ({
    sector,
    value,
    fill: PALETTE[i],
  }));
  if (tail.length > 0) {
    slices.push({
      sector: "Altro",
      value: tail.reduce((acc, [, v]) => acc + v, 0),
      fill: PALETTE[MAX_SLICES - 1],
    });
  }
  return slices;
}

/** Donut di allocazione per settore delle sole posizioni bot. */
export function SectorDonut({ positions }: { positions: Position[] }) {
  const slices = React.useMemo(() => buildSlices(positions), [positions]);
  const total = slices.reduce((acc, s) => acc + s.value, 0);
  const d = useDisplay();

  if (slices.length === 0) {
    return (
      <p className="text-muted-foreground py-10 text-center text-sm">
        Nessuna posizione aperta
      </p>
    );
  }

  const chartConfig = { value: { label: "Valore" } } satisfies ChartConfig;

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row">
      <ChartContainer
        config={chartConfig}
        className="aspect-square h-[200px] shrink-0"
      >
        <PieChart>
          <ChartTooltip
            content={
              <ChartTooltipContent
                hideLabel
                formatter={(value, _name, item) => (
                  <div className="flex w-full items-center gap-2">
                    <span
                      className="size-2 shrink-0 rounded-[2px]"
                      style={{ background: (item.payload as Slice).fill }}
                    />
                    <span className="text-muted-foreground">
                      {(item.payload as Slice).sector}
                    </span>
                    <span className="text-foreground ml-auto font-mono font-medium tabular-nums">
                      {d.money(typeof value === "number" ? value : null)}
                    </span>
                  </div>
                )}
              />
            }
          />
          <Pie
            data={slices}
            dataKey="value"
            nameKey="sector"
            innerRadius={55}
            outerRadius={85}
            paddingAngle={2}
            stroke="var(--card)"
            strokeWidth={2}
          />
        </PieChart>
      </ChartContainer>
      <ul className="w-full space-y-1.5 text-sm">
        {slices.map((s) => (
          <li key={s.sector} className="flex items-center gap-2 border-b border-border/60 pb-1.5 last:border-0 last:pb-0">
            <span
              className="size-2.5 shrink-0 rounded-[2px]"
              style={{ background: s.fill }}
            />
            <span className="truncate text-[13px]">{s.sector}</span>
            <span className="text-muted-foreground ml-auto font-mono text-xs tabular-nums">
              {fmtPct(total > 0 ? (s.value / total) * 100 : null, 1)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
