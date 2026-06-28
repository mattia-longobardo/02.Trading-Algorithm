"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency } from "@/lib/format";
import type { AllocationCategory } from "@/lib/types";
import { useChartTheme } from "@/components/charts/use-chart-theme";

// Pick black or white text for legibility on top of a given slice color,
// using WCAG relative luminance so it works in both light and dark themes.
function readableTextColor(hex: string): string {
  const c = hex.replace("#", "");
  if (c.length < 6) return "#ffffff";
  const toLinear = (v: number) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  const r = toLinear(parseInt(c.slice(0, 2), 16));
  const g = toLinear(parseInt(c.slice(2, 4), 16));
  const b = toLinear(parseInt(c.slice(4, 6), 16));
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const contrastWhite = 1.05 / (luminance + 0.05);
  const contrastBlack = (luminance + 0.05) / 0.05;
  return contrastWhite >= contrastBlack ? "#ffffff" : "#0f172a";
}

// ---------------------------------------------------------------------------
// AllocationLegend
// ---------------------------------------------------------------------------
function AllocationLegend({
  items,
  currency,
  pieColors,
}: {
  items: AllocationCategory[];
  currency: string;
  pieColors: string[];
}) {
  if (items.length === 0) return null;
  const total = items.reduce((sum, c) => sum + c.value, 0);
  return (
    <ul className="mt-3 flex flex-col gap-y-1 text-xs">
      {items.map((item, idx) => {
        const pct = total > 0 ? (item.value / total) * 100 : 0;
        return (
          <li key={item.category} className="flex items-center gap-2">
            <span
              className="inline-block size-2.5 shrink-0 rounded-full"
              style={{ background: pieColors[idx % pieColors.length] }}
            />
            <span className="shrink-0 text-(--color-text)">{item.category}</span>
            <span className="tnum ml-auto truncate tabular-nums text-(--color-muted)">
              {formatCurrency(item.value, currency)} · {pct.toFixed(1)}%
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// CategoryAllocationChart
// ---------------------------------------------------------------------------
export interface CategoryAllocationChartProps {
  byCategory: AllocationCategory[];
  currency: string;
  loading?: boolean;
  error?: boolean;
}

export function CategoryAllocationChart({
  byCategory,
  currency,
  loading,
  error,
}: CategoryAllocationChartProps) {
  const theme = useChartTheme();

  if (error) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Allocazione aperta per categoria</CardTitle>
        </CardHeader>
        <CardContent className="flex h-56 sm:h-72 items-center justify-center">
          <p className="text-sm text-(--color-muted)">Errore nel caricamento</p>
        </CardContent>
      </Card>
    );
  }

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Allocazione aperta per categoria</CardTitle>
        </CardHeader>
        <CardContent className="flex h-56 sm:h-72 flex-col">
          <Skeleton className="flex-1 rounded-lg" />
        </CardContent>
      </Card>
    );
  }

  if (byCategory.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Allocazione aperta per categoria</CardTitle>
        </CardHeader>
        <CardContent className="flex h-56 sm:h-72 items-center justify-center">
          <p className="text-sm text-(--color-muted)">Nessun dato</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Allocazione aperta per categoria</CardTitle>
      </CardHeader>
      <CardContent className="flex h-56 sm:h-72 flex-col">
        <div className="flex-1">
          <ResponsiveContainer>
            <PieChart>
              <Pie
                data={byCategory}
                dataKey="value"
                nameKey="category"
                innerRadius={50}
                outerRadius={90}
                paddingAngle={2}
                labelLine={false}
                label={(props: {
                  cx: number;
                  cy: number;
                  midAngle: number;
                  innerRadius: number;
                  outerRadius: number;
                  percent?: number;
                  index?: number;
                }) => {
                  const pct = props.percent ?? 0;
                  if (pct < 0.05) return null;
                  const RADIAN = Math.PI / 180;
                  const r = props.innerRadius + (props.outerRadius - props.innerRadius) / 2;
                  const x = props.cx + r * Math.cos(-props.midAngle * RADIAN);
                  const y = props.cy + r * Math.sin(-props.midAngle * RADIAN);
                  const sliceColor = theme.pie[(props.index ?? 0) % theme.pie.length];
                  return (
                    <text
                      x={x}
                      y={y}
                      fill={readableTextColor(sliceColor)}
                      textAnchor="middle"
                      dominantBaseline="central"
                      fontSize={12}
                      fontWeight={600}
                    >
                      {`${(pct * 100).toFixed(1)}%`}
                    </text>
                  );
                }}
              >
                {byCategory.map((_, idx) => (
                  <Cell key={idx} fill={theme.pie[idx % theme.pie.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: theme.tooltipBg,
                  border: `1px solid ${theme.tooltipBorder}`,
                  borderRadius: 8,
                  color: theme.text,
                }}
                labelStyle={{ color: theme.axis }}
                itemStyle={{ color: theme.text }}
                formatter={(v: number, _name, item) => {
                  const total = byCategory.reduce((sum, c) => sum + c.value, 0);
                  const pct = total > 0 ? (v / total) * 100 : 0;
                  return [
                    `${formatCurrency(v, currency)} (${pct.toFixed(1)}%)`,
                    (item as { name?: string })?.name ?? "",
                  ];
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
        <AllocationLegend items={byCategory} currency={currency} pieColors={theme.pie} />
      </CardContent>
    </Card>
  );
}
