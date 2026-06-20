"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import { CloseTradeDialog } from "@/components/trades/close-trade-dialog";
import { EditTradeDialog } from "@/components/trades/edit-trade-dialog";
import {
  DEFAULT_TRADE_CATEGORY_FILTER,
  DEFAULT_TRADE_STATUS_FILTER,
  TRADE_CATEGORY_OPTIONS,
  TRADE_STATUS_OPTIONS,
  TradesFilters,
} from "@/components/trades/trades-filters";
import { TradesTable } from "@/components/trades/trades-table";
import { api } from "@/lib/api";
import { mergeLiveTradeValues } from "@/lib/trade-live-values";
import { useLiveStream } from "@/lib/use-live-stream";
import {
  type Trade,
  type TradeCategory,
  type TradeStatus,
} from "@/lib/types";

interface TradesEnvelope {
  items: Trade[];
  total: number;
  page: number;
  page_size: number;
}

export default function TradesPage() {
  const qc = useQueryClient();
  const { snapshot } = useLiveStream();
  const [statusFilter, setStatusFilter] = useState<TradeStatus[]>(DEFAULT_TRADE_STATUS_FILTER);
  const [categoryFilter, setCategoryFilter] = useState<TradeCategory[]>(
    DEFAULT_TRADE_CATEGORY_FILTER,
  );
  const [symbolFilter, setSymbolFilter] = useState("");
  const [editing, setEditing] = useState<Trade | null>(null);
  const [closing, setClosing] = useState<Trade | null>(null);

  const trades = useQuery<TradesEnvelope>({
    queryKey: ["trades", "orders", statusFilter, categoryFilter, symbolFilter],
    queryFn: async () => {
      if (statusFilter.length === 0 || categoryFilter.length === 0) {
        return { items: [], total: 0, page: 1, page_size: 500 };
      }

      const params = new URLSearchParams();
      params.set("page", "1");
      params.set("page_size", "500");
      if (statusFilter.length < TRADE_STATUS_OPTIONS.length) {
        params.set("status", statusFilter.join(","));
      }
      if (categoryFilter.length < TRADE_CATEGORY_OPTIONS.length) {
        params.set("category", categoryFilter.join(","));
      }
      if (symbolFilter.trim()) params.set("symbol", symbolFilter.trim().toUpperCase());
      return api.get<TradesEnvelope>(`/api/trades?${params.toString()}`);
    },
    refetchInterval: 30_000,
  });

  const rawItems = trades.data?.items ?? [];
  const items = useMemo(
    () => mergeLiveTradeValues(rawItems, snapshot?.positions ?? []),
    [rawItems, snapshot?.positions],
  );

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Trade</h1>
          <p className="text-sm text-(--color-muted)">
            Vista completa dei trade. Modifica i parametri, sblocca il trailing TP
            riallineando il massimo, oppure chiudi/annulla manualmente. Le
            modifiche e le chiusure sono registrate nell&apos;audit log.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => trades.refetch()}>
            <RefreshCcw className="size-4" /> Aggiorna
          </Button>
        </div>
      </header>

      <TradesFilters
        statusFilter={statusFilter}
        categoryFilter={categoryFilter}
        symbolFilter={symbolFilter}
        onStatusChange={setStatusFilter}
        onCategoryChange={setCategoryFilter}
        onSymbolChange={setSymbolFilter}
      />

      <Card>
        <CardHeader>
          <CardTitle>Trade</CardTitle>
          <span className="text-xs text-(--color-muted)">
            {trades.data
              ? `${items.length}/${trades.data.total} risultati`
              : "—"}
          </span>
        </CardHeader>
        <CardContent>
          <TradesTable
            items={items}
            loading={trades.isLoading}
            onEdit={setEditing}
            onClose={setClosing}
          />
        </CardContent>
      </Card>

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="bottom-0 left-0 right-0 top-auto w-full max-w-none translate-x-0 translate-y-0 rounded-t-2xl sm:bottom-auto sm:left-1/2 sm:right-auto sm:top-1/2 sm:w-full sm:max-w-lg sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl">
          {editing && (
            <EditTradeDialog
              trade={editing}
              onClose={() => setEditing(null)}
              onSaved={() => {
                setEditing(null);
                qc.invalidateQueries({ queryKey: ["trades"] });
              }}
            />
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(closing)} onOpenChange={(open) => !open && setClosing(null)}>
        <DialogContent className="bottom-0 left-0 right-0 top-auto w-full max-w-none translate-x-0 translate-y-0 rounded-t-2xl sm:bottom-auto sm:left-1/2 sm:right-auto sm:top-1/2 sm:w-full sm:max-w-lg sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl">
          {closing && (
            <CloseTradeDialog
              trade={closing}
              onClose={() => setClosing(null)}
              onDone={() => {
                setClosing(null);
                qc.invalidateQueries({ queryKey: ["trades"] });
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
