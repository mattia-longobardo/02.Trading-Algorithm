"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Loader2, RefreshCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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
import { buildTradesExcelFilename, downloadTradesExcel } from "@/lib/trade-export";
import { mergeLiveTradeValues } from "@/lib/trade-live-values";
import { useToast } from "@/lib/toast";
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

const EXPORT_PAGE_SIZE = 500;

function dateInputValue(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function defaultExportFrom(): string {
  const from = new Date();
  from.setDate(from.getDate() - 90);
  return dateInputValue(from);
}

function dateBoundToIso(value: string, endOfDay: boolean): string | null {
  if (!value) return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return null;
  const date = new Date(year, month - 1, day);
  if (Number.isNaN(date.getTime())) return null;
  const hour = endOfDay ? 23 : 0;
  const minute = endOfDay ? 59 : 0;
  const second = endOfDay ? 59 : 0;
  const millisecond = endOfDay ? 999 : 0;
  date.setHours(hour, minute, second, millisecond);
  return date.toISOString();
}

export default function TradesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { snapshot } = useLiveStream();
  const [statusFilter, setStatusFilter] = useState<TradeStatus[]>(DEFAULT_TRADE_STATUS_FILTER);
  const [categoryFilter, setCategoryFilter] = useState<TradeCategory[]>(
    DEFAULT_TRADE_CATEGORY_FILTER,
  );
  const [symbolFilter, setSymbolFilter] = useState("");
  const [editing, setEditing] = useState<Trade | null>(null);
  const [closing, setClosing] = useState<Trade | null>(null);
  const [exportFrom, setExportFrom] = useState(defaultExportFrom);
  const [exportTo, setExportTo] = useState(() => dateInputValue(new Date()));
  const [exporting, setExporting] = useState(false);

  const trades = useQuery<TradesEnvelope>({
    queryKey: ["trades", "orders", statusFilter, categoryFilter, symbolFilter, exportFrom, exportTo],
    queryFn: async () => {
      if (statusFilter.length === 0 || categoryFilter.length === 0) {
        return { items: [], total: 0, page: 1, page_size: 500 };
      }

      const params = new URLSearchParams();
      params.set("page", "1");
      params.set("page_size", "500");
      appendTradeFilters(params);
      appendDateBounds(params);
      return api.get<TradesEnvelope>(`/api/trades?${params.toString()}`);
    },
    refetchInterval: 30_000,
  });

  const rawItems = trades.data?.items ?? [];
  const items = useMemo(
    () => mergeLiveTradeValues(rawItems, snapshot?.positions ?? []),
    [rawItems, snapshot?.positions],
  );
  const exportRangeInvalid = Boolean(exportFrom && exportTo && exportFrom > exportTo);

  function appendTradeFilters(params: URLSearchParams) {
    if (statusFilter.length < TRADE_STATUS_OPTIONS.length) {
      params.set("status", statusFilter.join(","));
    }
    if (categoryFilter.length < TRADE_CATEGORY_OPTIONS.length) {
      params.set("category", categoryFilter.join(","));
    }
    if (symbolFilter.trim()) params.set("symbol", symbolFilter.trim().toUpperCase());
  }

  function appendDateBounds(params: URLSearchParams) {
    const fromIso = dateBoundToIso(exportFrom, false);
    const toIso = dateBoundToIso(exportTo, true);
    if (fromIso) params.set("from", fromIso);
    if (toIso) params.set("to", toIso);
  }

  async function fetchExportTrades(): Promise<Trade[]> {
    if (statusFilter.length === 0 || categoryFilter.length === 0) return [];

    const baseParams = new URLSearchParams();
    appendTradeFilters(baseParams);
    appendDateBounds(baseParams);

    const exported: Trade[] = [];
    let page = 1;
    let total = Number.POSITIVE_INFINITY;

    while (exported.length < total) {
      const params = new URLSearchParams(baseParams);
      params.set("page", String(page));
      params.set("page_size", String(EXPORT_PAGE_SIZE));
      const response = await api.get<TradesEnvelope>(`/api/trades?${params.toString()}`);
      exported.push(...response.items);
      total = response.total;
      if (response.items.length < EXPORT_PAGE_SIZE) break;
      page += 1;
    }

    return mergeLiveTradeValues(exported, snapshot?.positions ?? []);
  }

  function handleExport() {
    if (exportRangeInvalid || !exportFrom || !exportTo || exporting) return;

    setExporting(true);
    const promise = fetchExportTrades()
      .then((exportItems) => {
        if (exportItems.length > 0) {
          downloadTradesExcel(exportItems, buildTradesExcelFilename(exportFrom, exportTo));
        }
        return exportItems.length;
      })
      .finally(() => setExporting(false));

    void toast
      .track(promise, {
        loading: "Generazione Excel",
        success: (count) =>
          count === 0 ? "Nessun trade da esportare" : `${count} trade esportati`,
        error: "Export Excel non riuscito",
      })
      .catch(() => undefined);
  }

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold sm:text-3xl">Trade</h1>
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
          <CardTitle>Periodo</CardTitle>
          <span className="text-xs text-(--color-muted)">
            Filtra la tabella sottostante e l&apos;export Excel.
          </span>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
          <div className="space-y-1">
            <label htmlFor="trade-export-from" className="text-xs uppercase text-(--color-muted)">
              Da
            </label>
            <Input
              id="trade-export-from"
              type="date"
              value={exportFrom}
              max={exportTo || undefined}
              aria-invalid={exportRangeInvalid}
              onChange={(e) => setExportFrom(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="trade-export-to" className="text-xs uppercase text-(--color-muted)">
              A
            </label>
            <Input
              id="trade-export-to"
              type="date"
              value={exportTo}
              min={exportFrom || undefined}
              aria-invalid={exportRangeInvalid}
              onChange={(e) => setExportTo(e.target.value)}
            />
          </div>
          <div className="md:self-end">
            <Button
              type="button"
              className="w-full md:w-auto"
              disabled={exporting || exportRangeInvalid || !exportFrom || !exportTo}
              onClick={handleExport}
            >
              {exporting ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Download className="size-4" />
              )}
              Scarica
            </Button>
          </div>
          {exportRangeInvalid && (
            <p className="text-sm text-(--color-danger) md:col-span-3" role="alert">
              Periodo non valido.
            </p>
          )}
        </CardContent>
      </Card>

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
