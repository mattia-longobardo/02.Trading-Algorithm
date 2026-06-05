"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, RefreshCcw, Trash2 } from "lucide-react";
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
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatNumber } from "@/lib/format";

type Category = "STOCK" | "CRYPTO";

const CATEGORIES: Category[] = ["STOCK", "CRYPTO"];

// The backend keys the universe dict by broker; with the eToro-only backend
// there is exactly one key. Named here so the literal isn't scattered around.
const ETORO_PROVIDER = "etoro";

interface UniverseEntry {
  symbol: string;
  category: Category;
  provider: string;
  last_price: number | null;
  quote_error: string | null;
}

interface UniverseEnvelope {
  universe: Record<string, Record<Category, UniverseEntry[]>>;
  active_providers: string[];
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

  const etoroEntries =
    universe.data?.universe?.[ETORO_PROVIDER] ?? ({} as Record<Category, UniverseEntry[]>);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Universe</h1>
          <p className="text-sm text-(--color-muted)">
            Universe attivo monitorato dal bot. Le aggiunte manuali sono validate via eToro.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => universe.refetch()}>
          <RefreshCcw className="size-4" /> Aggiorna
        </Button>
      </header>

      <div className="space-y-4">
        {isAdmin && (
          <AddSymbolCard onAdded={() => qc.invalidateQueries({ queryKey: ["universe"] })} />
        )}
        {CATEGORIES.map((category) => (
          <UniverseCategoryCard
            key={category}
            category={category}
            items={etoroEntries[category] ?? []}
            loading={universe.isLoading}
            isAdmin={isAdmin}
            onRemoved={() => qc.invalidateQueries({ queryKey: ["universe"] })}
          />
        ))}
      </div>

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
      api.post<{
        provider: string;
        category: Category;
        symbol: string;
        added: boolean;
        already_present: boolean;
      }>(`/api/universe/symbols`, { provider: ETORO_PROVIDER, category, symbol }),
    onSuccess: (data) => {
      const label = `Universe · ${data.category.toLowerCase()}`;
      if (data.already_present) {
        setSuccess(`${data.symbol} è già nel ${label}.`);
      } else {
        setSuccess(`${data.symbol} aggiunto al ${label}.`);
      }
      setSymbol("");
      onAdded();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  const placeholder = category === "CRYPTO" ? "es. BTC/USD" : "es. AAPL";

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
            {CATEGORIES.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Input
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          placeholder={placeholder}
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
          <StatusBanner kind="error" className="md:col-span-3">
            {error}
          </StatusBanner>
        )}
        {success && (
          <StatusBanner kind="success" className="md:col-span-3">
            {success}
          </StatusBanner>
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
        `/api/universe/symbols/${entry.provider}/${entry.category}/${encodeURIComponent(entry.symbol)}`,
      ),
    onSuccess: onRemoved,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Universe · {category}</CardTitle>
        <Badge variant="muted">{items.length}</Badge>
      </CardHeader>
      <CardContent>
        {loading && <p className="text-sm text-(--color-muted)">Caricamento…</p>}
        {!loading && items.length === 0 && (
          <EmptyState
            icon={Globe}
            title={`Universe ${category} vuoto`}
            description={
              <>
                Aggiungi simboli manualmente con il form sopra oppure aspetta la
                rigenerazione settimanale (domenica 22:00 UTC).
              </>
            }
          />
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
                    key={`${entry.provider}:${entry.category}:${entry.symbol}`}
                    className="bg-slate-950/40 transition-colors hover:bg-slate-900/60 [&>td]:border-y [&>td]:border-(--color-line)"
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
                                `Rimuovere ${entry.symbol} dall'universe ${entry.category.toLowerCase()}?`,
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
