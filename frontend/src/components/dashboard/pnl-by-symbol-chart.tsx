import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatCurrency } from "@/lib/format";
import type { PnlBySymbolRow } from "@/lib/types";

export interface PnlBySymbolChartProps {
  items: PnlBySymbolRow[];
  currency: string;
  loading?: boolean;
}

export function PnlBySymbolChart({ items, currency }: PnlBySymbolChartProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>PnL per simbolo</CardTitle>
      </CardHeader>
      <CardContent className="h-72">
        <ResponsiveContainer>
          <BarChart data={items}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="symbol" stroke="#94a3b8" fontSize={12} />
            <YAxis
              stroke="#94a3b8"
              fontSize={12}
              tickFormatter={(v) => formatCurrency(v, currency)}
              width={80}
            />
            <Tooltip
              contentStyle={{
                background: "#0f172a",
                border: "1px solid #1f2937",
                borderRadius: 8,
              }}
              labelStyle={{ color: "#e2e8f0" }}
              itemStyle={{ color: "#e2e8f0" }}
              formatter={(v: number) => {
                const color = v < 0 ? "#f43f5e" : v > 0 ? "#22c55e" : "#e2e8f0";
                return [
                  <span key="pnl" style={{ color, fontWeight: 600 }}>
                    {formatCurrency(v, currency)}
                  </span>,
                  "PnL",
                ];
              }}
            />
            <Bar dataKey="pnl_abs" name="PnL">
              {items.map((entry, idx) => (
                <Cell key={idx} fill={entry.pnl_abs < 0 ? "#f43f5e" : "#22c55e"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}
