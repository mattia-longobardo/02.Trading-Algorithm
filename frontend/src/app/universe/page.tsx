"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Plus, RefreshCcw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatNumber } from "@/lib/format";
import { useProviders } from "@/lib/use-providers";
import { type Provider, PROVIDER_LABELS } from "@/lib/types";

type Category = "STOCK" | "CRYPTO";

interface UniverseEntry {
  symbol: string;
  category: Category;
  provider: Provider;
  last_price: number | null;
  quote_error: string | null;
}

interface UniverseEnvelope {
  universe: Record<Provider, Record<Category, UniverseEntry[]>>;
  active_providers: Provider[];
}

const PROVIDER_CATEGORIES: Record<Provider, Category[]> = {
  alpaca: ["STOCK", "CRYPTO"],
};

export default function UniversePage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const qc = useQueryClient();
  const providers = useProviders();

  const universe = useQuery<UniverseEnvelope>({
    queryKey: ["universe"],
    queryFn: () => api.get<UniverseEnvelope>(`/api/universe`),
    refetchInterval: 60_000,
  });

  const activeProviders = useMemo<Provider[]>(() => {
    if (universe.data?.active_providers?.length) {
      return universe.data.active_providers;
    }
    return providers.active;
  }, [universe.data, providers.active]);

  if (!providers.isLoading && !providers.isError && activeProviders.length === 0) {
    return (
      <section className="space-y-6">
        <header>
          <h1 className="text-3xl font-semibold">Universe</h1>
          <p className="text-sm text-(--color-muted)">
            Nessun broker configurato. Imposta le credenziali Alpaca nel <code>.env</code>{" "}
            del backend e riavvia per popolare l&apos;universe.
          </p>
        </header>
      </section>
    );
  }

  const defaultProvider: Provider = activeProviders[0] ?? "alpaca";

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Universe</h1>
          <p className="text-sm text-(--color-muted)">
            Universe attivo monitorato dal bot. Le aggiunte manuali sono validate via il broker
            corrispondente.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => universe.refetch()}>
          <RefreshCcw className="size-4" /> Aggiorna
        </Button>
      </header>

      <Tabs defaultValue={defaultProvider}>
        <TabsList>
          {activeProviders.map((p) => (
            <TabsTrigger key={p} value={p}>
              {PROVIDER_LABELS[p]}
            </TabsTrigger>
          ))}
        </TabsList>
        {activeProviders.map((provider) => (
          <TabsContent key={provider} value={provider}>
            <ProviderUniverseSection
              provider={provider}
              isAdmin={isAdmin}
              loading={universe.isLoading}
              entries={universe.data?.universe?.[provider] ?? ({} as Record<Category, UniverseEntry[]>)}
              onMutated={() => qc.invalidateQueries({ queryKey: ["universe"] })}
            />
          </TabsContent>
        ))}
      </Tabs>

      {!isAdmin && (
        <p className="text-xs text-(--color-muted)">
          Visualizzazione in sola lettura — solo gli admin possono aggiungere o rimuovere simboli.
        </p>
      )}
    </section>
  );
}

function ProviderUniverseSection({
  provider,
  isAdmin,
  loading,
  entries,
  onMutated,
}: {
  provider: Provider;
  isAdmin: boolean;
  loading: boolean;
  entries: Record<Category, UniverseEntry[]>;
  onMutated: () => void;
}) {
  const categories = PROVIDER_CATEGORIES[provider];
  return (
    <div className="space-y-4">
      {isAdmin && <AddSymbolCard provider={provider} onAdded={onMutated} />}
      {categories.map((category) => (
        <UniverseCategoryCard
          key={`${provider}:${category}`}
          provider={provider}
          category={category}
          items={entries[category] ?? []}
          loading={loading}
          isAdmin={isAdmin}
          onRemoved={onMutated}
        />
      ))}
    </div>
  );
}

function AddSymbolCard({
  provider,
  onAdded,
}: {
  provider: Provider;
  onAdded: () => void;
}) {
  const categories = PROVIDER_CATEGORIES[provider];
  const [category, setCategory] = useState<Category>(categories[0]);
  const [symbol, setSymbol] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post<{
        provider: Provider;
        category: Category;
        symbol: string;
        added: boolean;
        already_present: boolean;
      }>(`/api/universe/symbols`, { provider, category, symbol }),
    onSuccess: (data) => {
      const label = `${PROVIDER_LABELS[data.provider]} · ${data.category.toLowerCase()}`;
      if (data.already_present) {
        setSuccess(`${data.symbol} è già nel universe ${label}.`);
      } else {
        setSuccess(`${data.symbol} aggiunto al universe ${label}.`);
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
        <CardTitle>Aggiungi simbolo — {PROVIDER_LABELS[provider]}</CardTitle>
      </CardHeader>
      <CardContent
        className={
          categories.length > 1
            ? "grid gap-3 md:grid-cols-[10rem_1fr_auto]"
            : "grid gap-3 md:grid-cols-[1fr_auto]"
        }
      >
        {categories.length > 1 && (
          <Select value={category} onValueChange={(v) => setCategory(v as Category)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
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
  provider,
  category,
  items,
  loading,
  isAdmin,
  onRemoved,
}: {
  provider: Provider;
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
        <CardTitle>
          {PROVIDER_LABELS[provider]} · {category}
        </CardTitle>
        <Badge variant="muted">{items.length}</Badge>
      </CardHeader>
      <CardContent>
        {loading && <p className="text-sm text-(--color-muted)">Caricamento…</p>}
        {!loading && items.length === 0 && (
          <EmptyState
            icon={Globe}
            title={`Universe ${PROVIDER_LABELS[provider]} · ${category} vuoto`}
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
                                `Rimuovere ${entry.symbol} dal universe ${PROVIDER_LABELS[entry.provider]} ${entry.category.toLowerCase()}?`,
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

