import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency } from "@/lib/format";
import type { AllocationCategory } from "@/lib/types";

const PIE_COLORS = ["#22c55e", "#38bdf8", "#a78bfa", "#f59e0b", "#f43f5e", "#facc15", "#34d399"];

// ---------------------------------------------------------------------------
// AllocationLegend
// ---------------------------------------------------------------------------
function AllocationLegend({
  items,
  currency,
}: {
  items: AllocationCategory[];
  currency: string;
}) {
  if (items.length === 0) return null;
  const total = items.reduce((sum, c) => sum + c.value, 0);
  return (
    <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
      {items.map((item, idx) => {
        const pct = total > 0 ? (item.value / total) * 100 : 0;
        return (
          <li key={item.category} className="flex items-center gap-2 truncate">
            <span
              className="inline-block size-2.5 shrink-0 rounded-full"
              style={{ background: PIE_COLORS[idx % PIE_COLORS.length] }}
            />
            <span className="truncate text-(--color-text)">{item.category}</span>
            <span className="tnum ml-auto tabular-nums text-(--color-muted)">
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
}

export function CategoryAllocationChart({
  byCategory,
  currency,
}: CategoryAllocationChartProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Allocazione aperta per categoria</CardTitle>
      </CardHeader>
      <CardContent className="flex h-72 flex-col">
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
                }) => {
                  const pct = props.percent ?? 0;
                  if (pct < 0.05) return null;
                  const RADIAN = Math.PI / 180;
                  const r = props.innerRadius + (props.outerRadius - props.innerRadius) / 2;
                  const x = props.cx + r * Math.cos(-props.midAngle * RADIAN);
                  const y = props.cy + r * Math.sin(-props.midAngle * RADIAN);
                  return (
                    <text
                      x={x}
                      y={y}
                      fill="#0f172a"
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
                  <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid #1f2937",
                  borderRadius: 8,
                  color: "#e2e8f0",
                }}
                labelStyle={{ color: "#94a3b8" }}
                itemStyle={{ color: "#e2e8f0" }}
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
        <AllocationLegend items={byCategory} currency={currency} />
      </CardContent>
    </Card>
  );
}
