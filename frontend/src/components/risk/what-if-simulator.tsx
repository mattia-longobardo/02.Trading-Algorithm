"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import type { RiskProjection, TradeCategory } from "@/lib/types";

function signed(value: number, digits = 1): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(digits)}`;
}

/** Per lo score, un delta negativo è "buono" (verde). */
function deltaClass(value: number): string {
  if (value > 0) return "text-(--color-danger)";
  if (value < 0) return "text-(--color-accent)";
  return "text-(--color-muted)";
}

export function WhatIfSimulator({ openSymbols }: { openSymbols: string[] }) {
  const [symbol, setSymbol] = useState("");
  const [category, setCategory] = useState<TradeCategory>("STOCK");
  const [value, setValue] = useState("");
  const [suggest, setSuggest] = useState(false);
  const [closeSymbols, setCloseSymbols] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { category };
      if (symbol.trim()) body.symbol = symbol.trim().toUpperCase();
      if (!suggest && value.trim()) {
        const num = Number(value);
        if (Number.isNaN(num) || num <= 0) throw new Error("Valore non valido");
        body.value = num;
      }
      if (closeSymbols.length) body.close_symbols = closeSymbols;
      if (!body.symbol && !closeSymbols.length) throw new Error("Inserisci un simbolo da aprire o seleziona posizioni da chiudere");
      return api.post<RiskProjection>("/api/risk/project", body);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  const result = mutation.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1">
          <label htmlFor="wi-symbol" className="text-xs uppercase text-(--color-muted)">Simbolo (apri)</label>
          <Input id="wi-symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="es. AAPL" />
        </div>
        <div className="space-y-1">
          <label htmlFor="wi-cat" className="text-xs uppercase text-(--color-muted)">Categoria</label>
          <select
            id="wi-cat"
            className="h-9 w-full rounded-lg border border-(--color-line) bg-(--color-panel)/50 px-3 text-sm text-(--color-text)"
            value={category}
            onChange={(e) => setCategory(e.target.value as TradeCategory)}
          >
            <option value="STOCK">STOCK</option>
            <option value="CRYPTO">CRYPTO</option>
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor="wi-value" className="text-xs uppercase text-(--color-muted)">Valore (USD)</label>
          <Input
            id="wi-value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={suggest}
            inputMode="decimal"
            placeholder={suggest ? "auto" : "es. 1000"}
          />
          <label className="flex items-center gap-1 text-xs text-(--color-muted)">
            <input type="checkbox" checked={suggest} onChange={(e) => setSuggest(e.target.checked)} />
            Suggerisci size
          </label>
        </div>
        {openSymbols.length > 0 && (
          <div className="space-y-1">
            <label className="text-xs uppercase text-(--color-muted)">Chiudi (simulato)</label>
            <div className="flex flex-wrap gap-1">
              {openSymbols.map((s) => {
                const on = closeSymbols.includes(s);
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() =>
                      setCloseSymbols((prev) => (on ? prev.filter((x) => x !== s) : [...prev, s]))
                    }
                    className={`rounded px-2 py-1 text-xs ${
                      on ? "bg-(--color-danger)/20 text-(--color-danger)" : "bg-(--color-line) text-(--color-muted)"
                    }`}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <Button
          onClick={() => {
            setError(null);
            mutation.mutate();
          }}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Calcolo…" : "Simula"}
        </Button>
      </div>

      {error && <StatusBanner kind="error">{error}</StatusBanner>}

      {result && (
        <div className="rounded-xl border border-(--color-line) bg-(--color-panel)/40 p-4">
          <div className="flex items-center justify-center gap-4 text-center">
            <div>
              <p className="text-xs text-(--color-muted)">Score attuale</p>
              <p className="tnum text-2xl font-semibold">{result.current.score.toFixed(0)}</p>
            </div>
            <span className="text-(--color-muted)">▸</span>
            <div>
              <p className="text-xs text-(--color-muted)">Proiettato</p>
              <p className="tnum text-2xl font-semibold">{result.projected.score.toFixed(0)}</p>
            </div>
            <div className={`tnum text-lg font-semibold ${deltaClass(result.delta.score)}`}>
              {signed(result.delta.score)}
            </div>
          </div>
          {result.suggested_size > 0 && (
            <p className="mt-2 text-center text-xs text-(--color-muted)">
              Size suggerita: <span className="tnum">{result.suggested_size.toFixed(0)} USD</span>
            </p>
          )}
          {result.projected.over_hard && (
            <StatusBanner kind="error">Supererebbe la soglia di rischio critica.</StatusBanner>
          )}
          <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <dt className="text-(--color-muted)">Δ Esposizione</dt>
              <dd className={`tnum ${deltaClass(result.delta.exposure)}`}>{signed(result.delta.exposure * 100)}%</dd>
            </div>
            <div>
              <dt className="text-(--color-muted)">Δ Volatilità</dt>
              <dd className={`tnum ${deltaClass(result.delta.portfolio_vol)}`}>{signed(result.delta.portfolio_vol * 100)}%</dd>
            </div>
            <div>
              <dt className="text-(--color-muted)">Δ n_eff</dt>
              <dd className={`tnum ${deltaClass(-result.delta.n_eff)}`}>{signed(result.delta.n_eff)}</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
