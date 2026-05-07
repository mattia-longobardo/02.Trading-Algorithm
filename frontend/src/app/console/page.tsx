"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, RefreshCcw } from "lucide-react";
import { useState } from "react";
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
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatCurrency, formatDateTime, formatNumber } from "@/lib/format";
import type { Trade, TradeStatus } from "@/lib/types";

const STATUSES: TradeStatus[] = ["PENDING", "OPEN", "CLOSED", "CANCELLED"];

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
  { key: "target_entry_price", label: "Target entry", hint: "Prezzo desiderato per l'entrata. Per le crypto è il livello GPT, mentre entry_price è il limit IOC inviato ad Alpaca." },
  { key: "quantity", label: "Quantity", hint: "Numero di azioni o frazioni di crypto." },
  { key: "take_profit", label: "Take profit", hint: "Livello di chiusura in profitto. Quando viene raggiunto il bot chiude a mercato." },
  { key: "trailing_take_profit_distance", label: "Trailing TP distance", hint: "Distanza assoluta dal massimo (high water mark). Trailing TP attivo solo quando entrambi i campi trailing TP sono valorizzati." },
  { key: "trailing_take_profit_activation_pct", label: "Trailing TP activation %", hint: "Guadagno % oltre l'entry richiesto per armare il trailing TP. Esempio: 5 = +5% sopra entry." },
  { key: "stop_loss", label: "Stop loss", hint: "Stop hard di chiusura in perdita." },
  { key: "trailing_stop_distance", label: "Trailing stop distance", hint: "Distanza dal massimo per il trailing stop. Lascia vuoto se non vuoi un trailing stop." },
];

export default function ConsolePage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<TradeStatus | "ALL">("ALL");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [editing, setEditing] = useState<Trade | null>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  const [actionConfirm, setActionConfirm] = useState<JobAction | null>(null);

  const trades = useQuery<TradesEnvelope>({
    queryKey: ["trades", "console", statusFilter, symbolFilter],
    queryFn: () => {
      const params = new URLSearchParams();
      params.set("page", "1");
      params.set("page_size", "200");
      if (statusFilter !== "ALL") params.set("status", statusFilter);
      if (symbolFilter.trim()) params.set("symbol", symbolFilter.trim().toUpperCase());
      return api.get<TradesEnvelope>(`/api/trades?${params.toString()}`);
    },
    refetchInterval: 30_000,
  });

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Console</h1>
          <p className="text-sm text-(--color-muted)">
            Modifica i parametri dei trade e lancia i job manuali. Tutte le modifiche sono
            registrate nell&apos;audit log.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="secondary" size="sm" onClick={() => trades.refetch()}>
            <RefreshCcw className="size-4" /> Aggiorna
          </Button>
          <Button variant="outline" size="sm" onClick={() => setLegendOpen(true)}>
            <BookOpen className="size-4" /> Legenda
          </Button>
        </div>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Filtri</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
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
            <label className="text-xs uppercase text-(--color-muted)">Simbolo</label>
            <Input
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
              placeholder="es. AAPL o BTC/USD"
            />
          </div>
        </CardContent>
      </Card>

      {user?.role === "admin" && (
        <Card>
          <CardHeader>
            <CardTitle>Job manuali (admin)</CardTitle>
            <span className="text-xs text-(--color-muted)">Ogni esecuzione condivide il lock dello scheduler.</span>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {JOB_ACTIONS.map((action) => (
              <Card key={action.path} className="p-4">
                <h3 className="text-sm font-semibold">{action.label}</h3>
                <p className="mt-1 text-xs text-(--color-muted)">{action.description}</p>
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-3"
                  onClick={() => setActionConfirm(action)}
                >
                  Esegui
                </Button>
              </Card>
            ))}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Trade</CardTitle>
          <span className="text-xs text-(--color-muted)">
            {trades.data ? `${trades.data.items.length}/${trades.data.total} risultati` : "—"}
          </span>
        </CardHeader>
        <CardContent>
          <ConsoleTradesTable
            items={trades.data?.items ?? []}
            loading={trades.isLoading}
            onEdit={setEditing}
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

      <LegendDialog open={legendOpen} onClose={() => setLegendOpen(false)} />

      <Dialog open={Boolean(actionConfirm)} onOpenChange={(open) => !open && setActionConfirm(null)}>
        <DialogContent>
          {actionConfirm && (
            <RunActionForm
              action={actionConfirm}
              onClose={() => setActionConfirm(null)}
              onDone={() => {
                setActionConfirm(null);
                qc.invalidateQueries();
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}

interface JobAction {
  label: string;
  description: string;
  path: string;
}

const JOB_ACTIONS: JobAction[] = [
  {
    label: "Rigenera universo",
    description: "Aggiorna l'universo stock/crypto monitorato.",
    path: "/api/universe/generate",
  },
  {
    label: "Genera nuovi ordini",
    description: "Esegue il ciclo GPT batch e apre eventuali nuovi trade.",
    path: "/api/orders/generate",
  },
  {
    label: "Report settimanale",
    description: "Genera il report PnL della settimana.",
    path: "/api/report/generate",
  },
  {
    label: "Report trimestrale",
    description: "Report del trimestre concluso.",
    path: "/api/report/quarterly",
  },
  {
    label: "Report semestrale",
    description: "Report del semestre concluso.",
    path: "/api/report/biannual",
  },
  {
    label: "Report annuale",
    description: "Report dell'anno solare concluso.",
    path: "/api/report/annual",
  },
  {
    label: "Reset scheduler",
    description: "Sblocca lo scheduler in stallo.",
    path: "/api/scheduler/reset",
  },
];

function ConsoleTradesTable({
  items,
  loading,
  onEdit,
}: {
  items: Trade[];
  loading: boolean;
  onEdit: (t: Trade) => void;
}) {
  if (loading) return <p className="text-sm text-(--color-muted)">Caricamento…</p>;
  if (items.length === 0) return <p className="text-sm text-(--color-muted)">Nessun trade.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1000px] border-separate border-spacing-y-1 text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-(--color-muted)">
            <th className="px-2 py-2">Simbolo</th>
            <th className="px-2 py-2">Stato</th>
            <th className="px-2 py-2 text-right">Entry</th>
            <th className="px-2 py-2 text-right">Target</th>
            <th className="px-2 py-2 text-right">Qty</th>
            <th className="px-2 py-2 text-right">TP</th>
            <th className="px-2 py-2 text-right">TTP dist</th>
            <th className="px-2 py-2 text-right">TTP arm%</th>
            <th className="px-2 py-2 text-right">SL</th>
            <th className="px-2 py-2 text-right">TS dist</th>
            <th className="px-2 py-2 text-right">PnL</th>
            <th className="px-2 py-2"></th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => (
            <tr key={t.id} className="bg-slate-950/40 [&>td]:border-y [&>td]:border-(--color-line)">
              <td className="px-2 py-2 font-medium first:rounded-l-lg">{t.symbol}</td>
              <td className="px-2 py-2">
                <Badge variant={statusVariant(t.status)}>{t.status}</Badge>
              </td>
              <td className="px-2 py-2 text-right">{formatNumber(t.entry_price)}</td>
              <td className="px-2 py-2 text-right">{formatNumber(t.target_entry_price)}</td>
              <td className="px-2 py-2 text-right">{formatNumber(t.quantity)}</td>
              <td className="px-2 py-2 text-right">{formatNumber(t.take_profit)}</td>
              <td className="px-2 py-2 text-right">
                {formatNumber(t.trailing_take_profit_distance)}
              </td>
              <td className="px-2 py-2 text-right">
                {formatNumber(t.trailing_take_profit_activation_pct)}
              </td>
              <td className="px-2 py-2 text-right">{formatNumber(t.stop_loss)}</td>
              <td className="px-2 py-2 text-right">{formatNumber(t.trailing_stop_distance)}</td>
              <td
                className={`px-2 py-2 text-right ${pnlClass(t.realized_pnl + t.unrealized_pnl)}`}
              >
                {formatCurrency(t.realized_pnl + t.unrealized_pnl)}
              </td>
              <td className="px-2 py-2 text-right last:rounded-r-lg">
                <Button size="sm" variant="secondary" onClick={() => onEdit(t)}>
                  Modifica
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function statusVariant(status: string): "open" | "pending" | "closed" | "cancelled" | "default" {
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
          valori non positivi e applica la regola coppia per il trailing TP.
        </DialogDescription>
      </DialogHeader>
      <form
        className="space-y-3"
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
        {error && (
          <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        )}
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

function LegendDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const legend = useQuery({
    queryKey: ["legend"],
    queryFn: () => api.get<{ glossary_markdown: string; fields: string[] }>(`/api/legend`),
    enabled: open,
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Legenda colonne</DialogTitle>
          <DialogDescription>
            Origine: backend/README.md. Spiega ogni colonna usata dal bot e come viene aggiornata.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto rounded-lg border border-(--color-line) bg-slate-950/40 p-4 text-sm">
          {legend.isLoading && <p className="text-(--color-muted)">Caricamento…</p>}
          {legend.data && (
            <pre className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-(--color-text)">
              {legend.data.glossary_markdown}
            </pre>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RunActionForm({
  action,
  onClose,
  onDone,
}: {
  action: JobAction;
  onClose: () => void;
  onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.get<{ status: string; message: string }>(action.path),
    onSuccess: (data) => {
      setResult(data.message);
      setTimeout(onDone, 1500);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    },
  });

  return (
    <div>
      <DialogHeader>
        <DialogTitle>{action.label}</DialogTitle>
        <DialogDescription>{action.description}</DialogDescription>
      </DialogHeader>
      <p className="text-sm text-(--color-muted)">
        Confermi l&apos;esecuzione manuale di questo job? L&apos;azione condivide il lock dello
        scheduler: se un altro job è in corso riceverai un 409 Conflict.
      </p>
      {error && (
        <div className="mt-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}
      {result && (
        <div className="mt-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {result}
        </div>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Annulla
        </Button>
        <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          {mutation.isPending ? "Esecuzione…" : "Conferma"}
        </Button>
      </div>
    </div>
  );
}
