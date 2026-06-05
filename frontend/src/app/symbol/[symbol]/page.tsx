"use client";

import { useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { PriceChart } from "@/components/charts/price-chart";
import { LiveBadge } from "@/components/live/live-badge";
import { SymbolHeader } from "@/components/symbol/symbol-header";
import { SymbolTradeHistory } from "@/components/symbol/symbol-trade-history";
import { api } from "@/lib/api";
import { useLiveStream } from "@/lib/use-live-stream";
import type { Candle, Trade, TradeCategory } from "@/lib/types";

interface TradesEnvelope {
  items: Trade[];
  total: number;
  page: number;
  page_size: number;
}

interface CandlesEnvelope {
  symbol: string;
  category: string;
  granularity: string;
  candles: Candle[];
}

function symbolFrom(raw: string | string[] | undefined): string {
  const s = Array.isArray(raw) ? raw[0] : raw ?? "";
  return decodeURIComponent(s).toUpperCase();
}

export default function SymbolPage() {
  const params = useParams();
  const symbol = symbolFrom(params["symbol"]);

  // --- live stream ---
  const { snapshot, status } = useLiveStream();
  const livePosition = snapshot?.positions.find(
    (p) => p.symbol.toUpperCase() === symbol,
  );

  // --- trades ---
  const tradesQuery = useQuery<TradesEnvelope>({
    queryKey: ["trades", "symbol", symbol],
    queryFn: () => api.get<TradesEnvelope>("/api/trades?page=1&page_size=500"),
    enabled: !!symbol,
    staleTime: 30_000,
  });

  const allTrades = tradesQuery.data?.items ?? [];
  const symbolTrades = allTrades.filter(
    (t) => t.symbol.toUpperCase() === symbol,
  );

  // Derive category from the most-recent matching trade; fall back to CRYPTO.
  const category: TradeCategory =
    symbolTrades.length > 0
      ? [...symbolTrades].sort((a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
        )[0].category
      : "CRYPTO";

  // Find the open trade for this symbol (to build price lines).
  const openTrade = symbolTrades.find((t) => t.status === "OPEN") ?? undefined;

  // --- candles ---
  // Wait for the trades query to settle so `category` is derived before the
  // first candles fetch — otherwise the default "CRYPTO" fires a request that
  // a STOCK symbol would immediately supersede (double round-trip).
  const candlesQuery = useQuery<CandlesEnvelope>({
    queryKey: ["candles", symbol, category],
    queryFn: () =>
      api.get<CandlesEnvelope>(
        `/api/candles?symbol=${encodeURIComponent(symbol)}&category=${category}&count=120`,
      ),
    enabled: !!symbol && (tradesQuery.isSuccess || tradesQuery.isError),
    staleTime: 60_000,
  });

  const candles = candlesQuery.data?.candles ?? [];

  // --- price lines (memoized so the chart isn't torn down on every live tick) ---
  const priceLines = useMemo(() => {
    const lines: { price: number; color?: string; title?: string }[] = [];
    const src = livePosition ?? openTrade;
    if (src) {
      lines.push({ price: src.entry_price, title: "Entry" });
      if (src.take_profit != null) {
        lines.push({ price: src.take_profit, color: "#22d37f", title: "TP" });
      }
      if (src.stop_loss != null) {
        lines.push({ price: src.stop_loss, color: "#f06868", title: "SL" });
      }
    }
    return lines;
  }, [livePosition, openTrade]);

  // --- loading state ---
  const isLoading = tradesQuery.isLoading || candlesQuery.isLoading;

  return (
    <section className="space-y-6">
      {/* Header row */}
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-2">
          {/* Back link */}
          <Link
            href="/positions"
            className="inline-flex items-center gap-1 text-sm text-(--color-muted) hover:text-(--color-text) hover:underline"
          >
            <ArrowLeft className="size-3.5" />
            Posizioni
          </Link>

          {/* Symbol heading */}
          {isLoading ? (
            <div className="h-8 w-40 animate-pulse rounded-md bg-(--color-hover)" />
          ) : (
            <SymbolHeader
              symbol={symbol}
              category={category}
              livePosition={livePosition}
              openTrade={openTrade}
            />
          )}
        </div>

        <LiveBadge status={status} />
      </header>

      {/* Chart */}
      {candlesQuery.isLoading ? (
        <div className="flex h-[380px] w-full animate-pulse items-center justify-center rounded-xl border border-(--color-line) bg-(--color-panel)/40 text-sm text-(--color-muted)">
          Caricamento…
        </div>
      ) : candlesQuery.isError ? (
        <div className="flex h-[380px] w-full items-center justify-center rounded-xl border border-dashed border-(--color-line) bg-(--color-panel)/40 text-sm text-(--color-muted)">
          Impossibile caricare il grafico.
        </div>
      ) : candles.length === 0 ? (
        <div className="flex h-[380px] w-full items-center justify-center rounded-xl border border-dashed border-(--color-line) bg-(--color-panel)/40 text-sm text-(--color-muted)">
          Nessun dato di prezzo disponibile per {symbol}.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-(--color-line)">
          <PriceChart candles={candles} priceLines={priceLines} height={380} />
        </div>
      )}

      {/* Trade history */}
      <div className="space-y-3">
        <h2 className="text-base font-semibold">
          Storico trade
          {symbolTrades.length > 0 && (
            <span className="ml-2 text-sm font-normal text-(--color-muted)">
              ({symbolTrades.length})
            </span>
          )}
        </h2>
        {tradesQuery.isLoading ? (
          <p className="text-sm text-(--color-muted)">Caricamento…</p>
        ) : tradesQuery.isError ? (
          <p className="text-sm text-(--color-danger)">Impossibile caricare lo storico trade.</p>
        ) : (
          <SymbolTradeHistory trades={symbolTrades} />
        )}
      </div>
    </section>
  );
}
