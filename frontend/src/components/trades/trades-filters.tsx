"use client";

import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { type TradeCategory, type TradeStatus } from "@/lib/types";

const STATUSES: TradeStatus[] = ["PENDING", "OPEN", "CLOSED", "CANCELLED"];
const CATEGORIES: TradeCategory[] = ["STOCK", "CRYPTO"];

interface TradesFiltersProps {
  statusFilter: TradeStatus | "ALL";
  categoryFilter: TradeCategory | "ALL";
  symbolFilter: string;
  onStatusChange: (value: TradeStatus | "ALL") => void;
  onCategoryChange: (value: TradeCategory | "ALL") => void;
  onSymbolChange: (value: string) => void;
}

export function TradesFilters({
  statusFilter,
  categoryFilter,
  symbolFilter,
  onStatusChange,
  onCategoryChange,
  onSymbolChange,
}: TradesFiltersProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Filtri</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Stato</label>
          <Select
            value={statusFilter}
            onValueChange={(v) => onStatusChange(v as TradeStatus | "ALL")}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">Tutti</SelectItem>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Categoria</label>
          <Select
            value={categoryFilter}
            onValueChange={(v) => onCategoryChange(v as TradeCategory | "ALL")}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">Tutte</SelectItem>
              {CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Cerca simbolo</label>
          <Input
            value={symbolFilter}
            onChange={(e) => onSymbolChange(e.target.value)}
            placeholder="es. AAPL, BTC/USD, LINK/EUR"
          />
        </div>
      </CardContent>
    </Card>
  );
}
