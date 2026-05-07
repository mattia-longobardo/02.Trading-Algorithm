"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCcw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { formatNumber } from "@/lib/format";

type Category = "STOCK" | "CRYPTO";

interface UniverseEntry {
  symbol: string;
  category: Category;
  last_price: number | null;
  quote_error: string | null;
}

interface UniverseEnvelope {
  universe: {
    STOCK: UniverseEntry[];
    CRYPTO: UniverseEntry[];
  };
}

export default function UniversePage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const qc = useQueryClient();

  const universe = useQuery<UniverseEnvelope>({
    queryKey: ["universe"],
    queryFn: () => api.get<UniverseEnvelope>(`/api/universe`),
    refetchInterval: 60_000,
  });

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Universe</h1>
          <p className="text-sm text-(--color-muted)">
            Universe attivo monitorato dal bot. Le aggiunte manuali sono validate via Alpaca:
            il simbolo deve essere quotabile e presente nel catalogo.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => universe.refetch()}>
          <RefreshCcw className="size-4" /> Aggiorna
        </Button>
      </header>

      {isAdmin && <AddSymbolCard onAdded={() => qc.invalidateQueries({ queryKey: ["universe"] })} />}

      {(["STOCK", "CRYPTO"] as Category[]).map((category) => (
        <UniverseCategoryCard
          key={category}
          category={category}
          items={universe.data?.universe[category] ?? []}
          loading={universe.isLoading}
          isAdmin={isAdmin}
          onRemoved={() => qc.invalidateQueries({ queryKey: ["universe"] })}
        />
      ))}

      {!isAdmin && (
        <p className="text-xs text-(--color-muted)">
          Visualizzazione in sola lettura — solo gli admin possono aggiungere o rimuovere simboli.
        </p>
      )}
    </section>
  );
}

function AddSymbolCard({ onAdded }: { onAdded: () => void }) {
  const [category, setCategory] = useState<Category>("STOCK");
  const [symbol, setSymbol] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post<{ category: Category; symbol: string; added: boolean; already_present: boolean }>(
        `/api/universe/symbols`,
        { category, symbol }
      ),
    onSuccess: (data) => {
      if (data.already_present) {
        setSuccess(`${data.symbol} è già nel universe ${data.category.toLowerCase()}.`);
      } else {
        setSuccess(`${data.symbol} aggiunto al universe ${data.category.toLowerCase()}.`);
      }
      setSymbol("");
      onAdded();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Aggiungi simbolo</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-[10rem_1fr_auto]">
        <Select value={category} onValueChange={(v) => setCategory(v as Category)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="STOCK">STOCK</SelectItem>
            <SelectItem value="CRYPTO">CRYPTO</SelectItem>
          </SelectContent>
        </Select>
        <Input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder={category === "CRYPTO" ? "es. BTC/USD" : "es. AAPL"}
        />
        <Button
          onClick={() => {
            setError(null);
            setSuccess(null);
            mutation.mutate();
          }}
          disabled={!symbol.trim() || mutation.isPending}
        >
          <Plus className="size-4" /> Aggiungi
        </Button>
        {error && (
          <div className="md:col-span-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        )}
        {success && (
          <div className="md:col-span-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            {success}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function UniverseCategoryCard({
  category,
  items,
  loading,
  isAdmin,
  onRemoved,
}: {
  category: Category;
  items: UniverseEntry[];
  loading: boolean;
  isAdmin: boolean;
  onRemoved: () => void;
}) {
  const removeMutation = useMutation({
    mutationFn: (entry: UniverseEntry) =>
      api.delete(
        `/api/universe/symbols/${entry.category}/${encodeURIComponent(entry.symbol)}`
      ),
    onSuccess: onRemoved,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{category}</CardTitle>
        <Badge variant="muted">{items.length}</Badge>
      </CardHeader>
      <CardContent>
        {loading && <p className="text-sm text-(--color-muted)">Caricamento…</p>}
        {!loading && items.length === 0 && (
          <p className="text-sm text-(--color-muted)">Nessun simbolo {category.toLowerCase()} nell&apos;universe.</p>
        )}
        {items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-separate border-spacing-y-1 text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-(--color-muted)">
                  <th className="px-2 py-2">Simbolo</th>
                  <th className="px-2 py-2 text-right">Ultimo prezzo</th>
                  <th className="px-2 py-2">Stato quote</th>
                  {isAdmin && <th className="px-2 py-2 text-right">Azioni</th>}
                </tr>
              </thead>
              <tbody>
                {items.map((entry) => (
                  <tr
                    key={`${entry.category}:${entry.symbol}`}
                    className="bg-slate-950/40 [&>td]:border-y [&>td]:border-(--color-line)"
                  >
                    <td className="px-2 py-2 font-medium first:rounded-l-lg">{entry.symbol}</td>
                    <td className="px-2 py-2 text-right">
                      {entry.last_price != null ? formatNumber(entry.last_price) : "—"}
                    </td>
                    <td className="px-2 py-2">
                      {entry.quote_error ? (
                        <Badge variant="cancelled" title={entry.quote_error}>
                          quote ko
                        </Badge>
                      ) : (
                        <Badge variant="open">live</Badge>
                      )}
                    </td>
                    {isAdmin && (
                      <td className="px-2 py-2 text-right last:rounded-r-lg">
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => {
                            if (
                              confirm(
                                `Rimuovere ${entry.symbol} dal universe ${entry.category.toLowerCase()}?`
                              )
                            ) {
                              removeMutation.mutate(entry);
                            }
                          }}
                        >
                          <Trash2 className="size-4" />
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
