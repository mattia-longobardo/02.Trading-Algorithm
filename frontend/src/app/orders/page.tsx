"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Inbox, RefreshCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import { formatCurrency, formatDateTime, formatNumber } from "@/lib/format";
import {
  PROVIDER_LABELS,
  type Provider,
  type Trade,
  type TradeCategory,
  type TradeStatus,
} from "@/lib/types";

const STATUSES: TradeStatus[] = ["PENDING", "OPEN", "CLOSED", "CANCELLED"];
const CATEGORIES: TradeCategory[] = ["STOCK", "CRYPTO"];
const PROVIDERS: Provider[] = ["alpaca"];

interface TradesEnvelope {
  items: Trade[];
  total: number;
  page: number;
  page_size: number;
}

const EDITABLE_FIELDS: Array<{
  key: keyof Trade;
  label: string;
  hint: string;
}> = [
  {
    key: "target_entry_price",
    label: "Target entry",
    hint: "Prezzo desiderato per l'entrata. Per le crypto è il livello GPT; entry_price è invece il limit IOC inviato al broker.",
  },
  {
    key: "quantity",
    label: "Quantity",
    hint: "Numero di azioni o frazioni di crypto. Obbligatorio (>0).",
  },
  {
    key: "take_profit",
    label: "Take profit",
    hint: "Livello di chiusura in profitto. Quando viene raggiunto il bot chiude a mercato.",
  },
  {
    key: "trailing_take_profit_distance",
    label: "Trailing TP distance",
    hint: "Distanza assoluta dal massimo (high-water mark). Trailing TP attivo solo se entrambi i campi trailing TP sono valorizzati.",
  },
  {
    key: "trailing_take_profit_activation_pct",
    label: "Trailing TP activation %",
    hint: "Guadagno % oltre l'entry richiesto per armare il trailing TP. Esempio: 5 = +5% sopra entry.",
  },
  {
    key: "stop_loss",
    label: "Stop loss",
    hint: "Stop hard di chiusura in perdita.",
  },
  {
    key: "trailing_stop_distance",
    label: "Trailing stop distance",
    hint: "Distanza assoluta dal massimo per il trailing stop. Lascia vuoto se non vuoi un trailing stop.",
  },
  {
    key: "high_water_mark",
    label: "High-water mark",
    hint: "Massimo storico osservato dal bot, usato come riferimento per trailing TP/SL. Modificarlo \"resetta\" il trailing senza aspettare il prossimo tick.",
  },
];

export default function OrdersPage() {
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<TradeStatus | "ALL">("ALL");
  const [categoryFilter, setCategoryFilter] = useState<TradeCategory | "ALL">("ALL");
  const [providerFilter, setProviderFilter] = useState<Provider | "ALL">("ALL");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [editing, setEditing] = useState<Trade | null>(null);
  const [closing, setClosing] = useState<Trade | null>(null);

  const trades = useQuery<TradesEnvelope>({
    queryKey: ["trades", "orders", statusFilter, categoryFilter, symbolFilter],
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("page", "1");
      params.set("page_size", "500");
      if (statusFilter !== "ALL") params.set("status", statusFilter);
      if (categoryFilter !== "ALL") params.set("category", categoryFilter);
      if (symbolFilter.trim()) params.set("symbol", symbolFilter.trim().toUpperCase());
      return api.get<TradesEnvelope>(`/api/trades?${params.toString()}`);
    },
    refetchInterval: 30_000,
  });

  // Provider filter is applied client-side because the backend list endpoint
  // doesn't expose it (the field is on the row itself).
  const items = useMemo(() => {
    const rows = trades.data?.items ?? [];
    if (providerFilter === "ALL") return rows;
    return rows.filter((t) => (t.provider ?? "alpaca") === providerFilter);
  }, [trades.data?.items, providerFilter]);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Ordini</h1>
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

      <Card>
        <CardHeader>
          <CardTitle>Filtri</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-4">
          <div className="space-y-1">
            <label className="text-xs uppercase text-(--color-muted)">Stato</label>
            <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as TradeStatus | "ALL")}>
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
              onValueChange={(v) => setCategoryFilter(v as TradeCategory | "ALL")}
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
            <label className="text-xs uppercase text-(--color-muted)">Broker</label>
            <Select
              value={providerFilter}
              onValueChange={(v) => setProviderFilter(v as Provider | "ALL")}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">Tutti</SelectItem>
                {PROVIDERS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {PROVIDER_LABELS[p]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1">
            <label className="text-xs uppercase text-(--color-muted)">Cerca simbolo</label>
            <Input
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
              placeholder="es. AAPL, BTC/USD, LINK/EUR"
            />
          </div>
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
          <OrdersTable
            items={items}
            loading={trades.isLoading}
            onEdit={setEditing}
            onClose={setClosing}
          />
        </CardContent>
      </Card>

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent>
          {editing && (
            <EditTradeForm
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
        <DialogContent>
          {closing && (
            <CloseTradeForm
              trade={closing}
              onCancel={() => setClosing(null)}
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

function OrdersTable({
  items,
  loading,
  onEdit,
  onClose,
}: {
  items: Trade[];
  loading: boolean;
  onEdit: (t: Trade) => void;
  onClose: (t: Trade) => void;
}) {
  if (loading) return <p className="text-sm text-(--color-muted)">Caricamento…</p>;
  if (items.length === 0)
    return (
      <EmptyState
        icon={Inbox}
        title="Nessun trade"
        description="Nessun trade per i filtri selezionati. Allenta i filtri di stato/categoria/broker o cerca un simbolo diverso."
      />
    );
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1600px] border-separate border-spacing-y-1 text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-(--color-muted)">
            <th className="px-2 py-2">ID</th>
            <th className="px-2 py-2">Simbolo</th>
            <th className="px-2 py-2">Stato</th>
            <th className="px-2 py-2">Cat.</th>
            <th className="px-2 py-2">Broker</th>
            <th className="px-2 py-2">Dir.</th>
            <th className="px-2 py-2 text-right">Entry</th>
            <th className="px-2 py-2 text-right">Target</th>
            <th className="px-2 py-2 text-right">Qty</th>
            <th className="px-2 py-2 text-right">Capitale</th>
            <th className="px-2 py-2 text-right">TP</th>
            <th className="px-2 py-2 text-right">TTP dist</th>
            <th className="px-2 py-2 text-right">TTP arm%</th>
            <th className="px-2 py-2 text-right">TTP trigger</th>
            <th className="px-2 py-2 text-right">HWM</th>
            <th className="px-2 py-2 text-right">SL</th>
            <th className="px-2 py-2 text-right">TS dist</th>
            <th className="px-2 py-2 text-right">TS trigger</th>
            <th className="px-2 py-2 text-right">Prezzo</th>
            <th className="px-2 py-2 text-right">PnL</th>
            <th className="px-2 py-2">Motivo</th>
            <th className="px-2 py-2">Aperto</th>
            <th className="px-2 py-2">Chiuso</th>
            <th className="px-2 py-2 text-right"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => {
            const ttpArmed =
              t.trailing_take_profit_price != null && t.high_water_mark != null;
            const tsArmed = t.trailing_stop_price != null;
            return (
              <tr
                key={t.id}
                className="bg-slate-950/40 transition-colors hover:bg-slate-900/60 [&>td]:border-y [&>td]:border-(--color-line)"
              >
                <td className="px-2 py-2 text-(--color-muted) first:rounded-l-lg">#{t.id}</td>
                <td className="px-2 py-2 font-medium">{t.symbol}</td>
                <td className="px-2 py-2">
                  <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
                </td>
                <td className="px-2 py-2 text-(--color-muted)">{t.category}</td>
                <td className="px-2 py-2 text-(--color-muted)">
                  {PROVIDER_LABELS[(t.provider ?? "alpaca") as Provider] ??
                    (t.provider ?? "alpaca").toUpperCase()}
                </td>
                <td className="px-2 py-2 text-(--color-muted)">{t.direction}</td>
                <td className="px-2 py-2 text-right">{formatNumber(t.entry_price)}</td>
                <td className="px-2 py-2 text-right">{formatNumber(t.target_entry_price)}</td>
                <td className="px-2 py-2 text-right">{formatNumber(t.quantity)}</td>
                <td className="px-2 py-2 text-right">
                  {formatCurrency(t.allocated_capital, t.account_currency || "EUR")}
                </td>
                <td className="px-2 py-2 text-right">{formatNumber(t.take_profit)}</td>
                <td className="px-2 py-2 text-right">{formatNumber(t.trailing_take_profit_distance)}</td>
                <td className="px-2 py-2 text-right">
                  {formatNumber(t.trailing_take_profit_activation_pct)}
                </td>
                <td
                  className={`px-2 py-2 text-right ${
                    ttpArmed ? "text-emerald-300" : "text-(--color-muted)"
                  }`}
                  title={ttpArmed ? "Trailing TP armato" : "Trailing TP non ancora armato"}
                >
                  {formatNumber(t.trailing_take_profit_price)}
                </td>
                <td className="px-2 py-2 text-right">{formatNumber(t.high_water_mark)}</td>
                <td className="px-2 py-2 text-right">{formatNumber(t.stop_loss)}</td>
                <td className="px-2 py-2 text-right">{formatNumber(t.trailing_stop_distance)}</td>
                <td
                  className={`px-2 py-2 text-right ${
                    tsArmed ? "text-rose-300" : "text-(--color-muted)"
                  }`}
                  title={tsArmed ? "Trailing stop armato" : "Trailing stop non ancora armato"}
                >
                  {formatNumber(t.trailing_stop_price)}
                </td>
                <td className="px-2 py-2 text-right">{formatNumber(t.current_price)}</td>
                <td
                  className={`px-2 py-2 text-right ${pnlClass(
                    (t.realized_pnl ?? 0) + (t.unrealized_pnl ?? 0)
                  )}`}
                >
                  {formatCurrency(
                    (t.realized_pnl ?? 0) + (t.unrealized_pnl ?? 0),
                    t.account_currency || "EUR"
                  )}
                </td>
                <td className="px-2 py-2 text-(--color-muted)">{t.close_reason ?? "—"}</td>
                <td className="px-2 py-2 text-(--color-muted)">
                  {formatDateTime(t.open_timestamp ?? t.created_at)}
                </td>
                <td className="px-2 py-2 text-(--color-muted)">
                  {t.close_timestamp ? formatDateTime(t.close_timestamp) : "—"}
                </td>
                <td className="px-2 py-2 text-right last:rounded-r-lg">
                  <div className="flex justify-end gap-2">
                    <Button size="sm" variant="secondary" onClick={() => onEdit(t)}>
                      Modifica
                    </Button>
                    {(t.status === "PENDING" || t.status === "OPEN") && (
                      <Button
                        size="sm"
                        variant="danger"
                        onClick={() => onClose(t)}
                      >
                        {t.status === "PENDING" ? "Annulla" : "Chiudi"}
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function statusVariant(
  status: string
): "open" | "pending" | "closed" | "cancelled" | "default" {
  switch (status) {
    case "OPEN":
      return "open";
    case "PENDING":
      return "pending";
    case "CLOSED":
      return "closed";
    case "CANCELLED":
      return "cancelled";
    default:
      return "default";
  }
}

function pnlClass(value: number): string {
  if (value > 0) return "text-emerald-400";
  if (value < 0) return "text-rose-400";
  return "text-(--color-text)";
}

function EditTradeForm({
  trade,
  onClose,
  onSaved,
}: {
  trade: Trade;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {};
    for (const f of EDITABLE_FIELDS) {
      const raw = trade[f.key];
      seed[f.key as string] = raw === null || raw === undefined ? "" : String(raw);
    }
    return seed;
  });
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: async () => {
      const body: Record<string, number | null> = {};
      for (const f of EDITABLE_FIELDS) {
        const raw = values[f.key as string];
        if (raw === "") {
          if (f.key === "quantity") {
            throw new Error("La quantità è obbligatoria");
          }
          body[f.key as string] = null;
        } else {
          const num = Number(raw);
          if (Number.isNaN(num)) {
            throw new Error(`${f.label} non è un numero valido`);
          }
          body[f.key as string] = num;
        }
      }
      return api.patch(`/api/trades/${trade.id}`, body);
    },
    onSuccess: onSaved,
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    },
  });

  return (
    <div>
      <DialogHeader>
        <DialogTitle>
          Modifica trade #{trade.id} — {trade.symbol}
        </DialogTitle>
        <DialogDescription>
          Solo i parametri editabili sono modificabili. La validazione del backend impedisce
          valori non positivi e applica la regola coppia per il trailing TP (entrambi
          valorizzati o entrambi vuoti).
        </DialogDescription>
      </DialogHeader>
      <form
        className="space-y-3 max-h-[60vh] overflow-y-auto pr-1"
        onSubmit={(e) => {
          e.preventDefault();
          setError(null);
          mutation.mutate();
        }}
      >
        {EDITABLE_FIELDS.map((f) => (
          <div key={f.key as string} className="space-y-1">
            <label className="flex items-center justify-between text-xs uppercase text-(--color-muted)">
              <span>{f.label}</span>
              <span className="lowercase normal-case">{f.key}</span>
            </label>
            <Input
              inputMode="decimal"
              value={values[f.key as string] ?? ""}
              onChange={(e) =>
                setValues((prev) => ({ ...prev, [f.key as string]: e.target.value }))
              }
              placeholder="—"
            />
            <p className="text-xs text-(--color-muted)">{f.hint}</p>
          </div>
        ))}
        {error && <StatusBanner kind="error">{error}</StatusBanner>}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Annulla
          </Button>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? "Salvataggio…" : "Salva"}
          </Button>
        </div>
      </form>
    </div>
  );
}

function CloseTradeForm({
  trade,
  onCancel,
  onDone,
}: {
  trade: Trade;
  onCancel: () => void;
  onDone: () => void;
}) {
  const isPending = trade.status === "PENDING";
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.post<{ trade: Trade }>(`/api/trades/${trade.id}/close`),
    onSuccess: onDone,
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    },
  });

  return (
    <div>
      <DialogHeader>
        <DialogTitle>
          {isPending ? "Annulla ordine pending" : "Chiudi trade a mercato"} — #{trade.id}{" "}
          {trade.symbol}
        </DialogTitle>
        <DialogDescription>
          {isPending
            ? "L'ordine pending verrà annullato presso il broker (se ancora aperto) e il trade marcato come CANCELLED con motivo MANUAL_CANCEL."
            : "Verrà inviato un ordine di chiusura a mercato. Il PnL si consoliderà non appena il broker conferma il fill (riconciliato dal job monitor_trades). Motivo: MANUAL_CLOSE."}
        </DialogDescription>
      </DialogHeader>
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-md border border-(--color-line) bg-slate-950/40 p-2">
          <p className="text-(--color-muted)">Entry</p>
          <p className="font-medium">{formatNumber(trade.entry_price)}</p>
        </div>
        <div className="rounded-md border border-(--color-line) bg-slate-950/40 p-2">
          <p className="text-(--color-muted)">Prezzo corrente</p>
          <p className="font-medium">{formatNumber(trade.current_price)}</p>
        </div>
        <div className="rounded-md border border-(--color-line) bg-slate-950/40 p-2">
          <p className="text-(--color-muted)">Quantità</p>
          <p className="font-medium">{formatNumber(trade.quantity)}</p>
        </div>
        <div className="rounded-md border border-(--color-line) bg-slate-950/40 p-2">
          <p className="text-(--color-muted)">PnL stimato</p>
          <p className={`font-medium ${pnlClass((trade.realized_pnl ?? 0) + (trade.unrealized_pnl ?? 0))}`}>
            {formatCurrency(
              (trade.realized_pnl ?? 0) + (trade.unrealized_pnl ?? 0),
              trade.account_currency || "EUR"
            )}
          </p>
        </div>
      </div>
      {error && (
        <StatusBanner kind="error" className="mt-3">
          {error}
        </StatusBanner>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>
          Indietro
        </Button>
        <Button
          variant="danger"
          disabled={mutation.isPending}
          onClick={() => {
            setError(null);
            mutation.mutate();
          }}
        >
          {mutation.isPending
            ? "Invio…"
            : isPending
              ? "Conferma annullamento"
              : "Conferma chiusura"}
        </Button>
      </div>
    </div>
  );
}
