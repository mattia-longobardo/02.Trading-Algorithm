"use client";

import * as React from "react";
import { ChevronRightIcon, TrendingDownIcon, TrendingUpIcon } from "lucide-react";

import { RawPayload } from "@/components/json-view";
import { Stamp } from "@/components/stamp";
import { SideBadge } from "@/components/status-badges";
import { useDisplay } from "@/lib/money";
import { cn } from "@/lib/utils";
import type { Decision } from "@/lib/types";

/**
 * Lettura umana delle decisioni di una run.
 *
 * Ogni fase scrive a journal un payload diverso; qui ciascuno diventa prosa,
 * timbri e barre. Il JSON originale resta a un click di distanza (RawPayload)
 * per chi deve verificare il dato esatto, ma non è più la vista di default.
 */

// --- accessori difensivi sui payload (arrivano dal DB come JSON libero) ------

const str = (v: unknown, fallback = ""): string =>
  typeof v === "string" ? v : fallback;

const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;

function groupBySymbol(decisions: Decision[]): [string, Decision[]][] {
  const map = new Map<string, Decision[]>();
  for (const decision of decisions) {
    const list = map.get(decision.symbol) ?? [];
    list.push(decision);
    map.set(decision.symbol, list);
  }
  return [...map.entries()];
}

/** Intestazione comune a tutte le schede: titolo + timbri a destra. */
function CardHead({
  symbol,
  children,
}: {
  symbol: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
      <span className="font-mono text-sm font-medium">{symbol}</span>
      <div className="flex flex-wrap items-center gap-1.5">{children}</div>
    </div>
  );
}

function Panel({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("rounded-md border p-4", className)}>{children}</div>
  );
}

// --- analisti ----------------------------------------------------------------

const ANALYST_LABELS: Record<string, string> = {
  fundamental: "Fondamentale",
  technical: "Tecnico",
  sentiment: "Sentiment",
  macro: "Macro",
};

const ANALYST_ORDER = ["fundamental", "technical", "sentiment", "macro"];

/** Barra bipolare −1…+1 con lo zero al centro: verde a destra, rosso a sinistra. */
function ScoreBar({ score }: { score: number }) {
  const clamped = Math.max(-1, Math.min(1, score));
  const width = (Math.abs(clamped) / 2) * 100;
  const positive = clamped >= 0;
  return (
    <div className="bg-muted relative h-1.5 w-full overflow-hidden rounded-[2px]">
      <span
        aria-hidden
        className="bg-border absolute top-0 left-1/2 h-full w-px"
      />
      <div
        className={cn(
          "absolute top-0 h-full rounded-[2px]",
          positive ? "bg-positive" : "bg-negative",
        )}
        style={
          positive
            ? { left: "50%", width: `${width}%` }
            : { right: "50%", width: `${width}%` }
        }
      />
    </div>
  );
}

function signed(value: number, digits = 2): string {
  return `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(digits)}`;
}

export function AnalystSection({ decisions }: { decisions: Decision[] }) {
  const groups = groupBySymbol(decisions);
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      {groups.map(([symbol, items]) => {
        const sorted = [...items].sort(
          (a, b) =>
            ANALYST_ORDER.indexOf(str(a.payload.analyst)) -
            ANALYST_ORDER.indexOf(str(b.payload.analyst)),
        );
        const scores = sorted
          .map((item) => num(item.payload.score))
          .filter((v): v is number => v !== null);
        const consensus = scores.length
          ? scores.reduce((a, b) => a + b, 0) / scores.length
          : null;
        return (
          <Panel key={symbol}>
            <CardHead symbol={symbol}>
              {consensus !== null ? (
                <span className="text-muted-foreground font-mono text-[11px] tracking-[0.04em] uppercase">
                  consenso{" "}
                  <span
                    className={cn(
                      "font-medium tabular-nums",
                      consensus >= 0 ? "text-positive" : "text-negative",
                    )}
                  >
                    {signed(consensus)}
                  </span>
                </span>
              ) : null}
            </CardHead>
            <div className="space-y-3">
              {sorted.map((item) => {
                const score = num(item.payload.score);
                const analyst = str(item.payload.analyst, "?");
                return (
                  <div key={item.id} className="space-y-1.5">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[13px] font-medium">
                        {ANALYST_LABELS[analyst] ?? analyst}
                      </span>
                      <span
                        className={cn(
                          "font-mono text-[11px] font-medium tabular-nums",
                          score === null
                            ? "text-muted-foreground"
                            : score >= 0
                              ? "text-positive"
                              : "text-negative",
                        )}
                      >
                        {score === null ? "n/d" : signed(score)}
                      </span>
                    </div>
                    {score !== null ? <ScoreBar score={score} /> : null}
                    <p className="text-muted-foreground text-[13px] leading-relaxed">
                      {str(item.payload.summary, "—")}
                    </p>
                  </div>
                );
              })}
            </div>
            <RawPayload value={sorted.map((item) => item.payload)} />
          </Panel>
        );
      })}
    </div>
  );
}

// --- debate ------------------------------------------------------------------

const DEBATE_META: Record<
  string,
  { label: string; tone: "approved" | "caution" | "neutral"; note: string }
> = {
  open_long: {
    label: "Apri long",
    tone: "approved",
    note: "Il giudice ha ritenuto il caso rialzista nettamente più forte.",
  },
  close: {
    label: "Chiudi",
    tone: "caution",
    note: "Il giudice propone di liquidare la posizione esistente.",
  },
  avoid: {
    label: "Evita",
    tone: "neutral",
    note: "Nessuna operazione: il caso rialzista non è nettamente più forte di quello ribassista.",
  },
};

interface Turn {
  role: string;
  round: number;
  text: string;
}

function parseTranscript(payload: Record<string, unknown>): Turn[] {
  const raw = payload.transcript;
  if (!Array.isArray(raw)) return [];
  return raw
    .map((entry) => {
      const item = (entry ?? {}) as Record<string, unknown>;
      return {
        role: str(item.role, "?"),
        round: num(item.round) ?? 0,
        text: str(item.text),
      };
    })
    // Il turno "judge" contiene la risposta grezza del modello (JSON): il suo
    // contenuto è già rappresentato da verdetto, convinzione e motivazione.
    .filter((turn) => turn.text && turn.role !== "judge");
}

function ConvictionBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="bg-muted h-1.5 w-24 overflow-hidden rounded-[2px]">
        <div
          className="bg-primary h-full rounded-[2px]"
          style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        />
      </div>
      <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
        {Math.round(value * 100)}%
      </span>
    </div>
  );
}

function DebateTurn({ turn }: { turn: Turn }) {
  const isBull = turn.role === "bull";
  return (
    <div
      className={cn(
        "rounded-md border-l-2 py-1.5 pl-3",
        isBull
          ? "border-positive/60 bg-positive/[0.04]"
          : "border-negative/60 bg-negative/[0.04]",
      )}
    >
      <div
        className={cn(
          "mb-1 flex items-center gap-1.5 font-mono text-[10px] tracking-[0.08em] uppercase",
          isBull ? "text-positive" : "text-negative",
        )}
      >
        {isBull ? (
          <TrendingUpIcon aria-hidden="true" className="size-3" />
        ) : (
          <TrendingDownIcon aria-hidden="true" className="size-3" />
        )}
        {isBull ? "Rialzista" : "Ribassista"} · round {turn.round}
      </div>
      <p className="text-[13px] leading-relaxed">{turn.text}</p>
    </div>
  );
}

export function DebateSection({ decisions }: { decisions: Decision[] }) {
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      {decisions.map((decision) => {
        const key = str(decision.payload.decision, "avoid");
        const meta = DEBATE_META[key] ?? {
          label: key,
          tone: "neutral" as const,
          note: "",
        };
        const conviction = num(decision.payload.conviction);
        const turns = parseTranscript(decision.payload);
        return (
          <Panel key={decision.id}>
            <CardHead symbol={decision.symbol}>
              <Stamp tone={meta.tone}>{meta.label}</Stamp>
            </CardHead>

            {conviction !== null ? (
              <div className="mb-3 flex items-center gap-2">
                <span className="text-muted-foreground font-mono text-[10px] tracking-[0.08em] uppercase">
                  Convinzione
                </span>
                <ConvictionBar value={conviction} />
              </div>
            ) : null}

            <p className="text-[13px] leading-relaxed">
              {str(decision.payload.rationale, "Nessuna motivazione registrata.")}
            </p>

            {meta.note ? (
              <p className="text-muted-foreground mt-2 text-xs italic">
                {meta.note}
              </p>
            ) : null}

            {turns.length ? (
              <details className="group mt-3">
                <summary className="text-muted-foreground hover:text-foreground inline-flex cursor-pointer list-none items-center gap-1 font-mono text-[10px] tracking-[0.08em] uppercase transition-colors [&::-webkit-details-marker]:hidden">
                  <ChevronRightIcon
                    aria-hidden="true"
                    className="size-3 transition-transform group-open:rotate-90"
                  />
                  Dibattito — {turns.length} interventi
                </summary>
                <div className="mt-2 space-y-2">
                  {turns.map((turn, i) => (
                    <DebateTurn key={i} turn={turn} />
                  ))}
                </div>
              </details>
            ) : null}

            <RawPayload value={decision.payload} />
          </Panel>
        );
      })}
    </div>
  );
}

// --- ordini proposti ---------------------------------------------------------

export function OrdersSection({ decisions }: { decisions: Decision[] }) {
  const d = useDisplay();
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      {decisions.map((decision) => {
        const side = str(decision.payload.side) === "sell" ? "sell" : "buy";
        const amount = num(decision.payload.amount_usd);
        const conviction = num(decision.payload.conviction);
        return (
          <Panel key={decision.id}>
            <CardHead symbol={decision.symbol}>
              <SideBadge side={side} />
              <Stamp tone="neutral">
                {str(decision.payload.asset_type, "—")}
              </Stamp>
            </CardHead>
            <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-2 text-[13px] sm:grid-cols-3">
              <div>
                <dt className="text-muted-foreground font-mono text-[10px] tracking-[0.08em] uppercase">
                  Importo
                </dt>
                <dd className="font-mono font-medium tabular-nums">
                  {amount === null ? "—" : d.money(amount)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground font-mono text-[10px] tracking-[0.08em] uppercase">
                  Settore
                </dt>
                <dd>{str(decision.payload.sector, "—")}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground font-mono text-[10px] tracking-[0.08em] uppercase">
                  Convinzione
                </dt>
                <dd>
                  {conviction === null ? (
                    "—"
                  ) : (
                    <ConvictionBar value={conviction} />
                  )}
                </dd>
              </div>
            </dl>
            <p className="text-muted-foreground text-[13px] leading-relaxed">
              {str(decision.payload.rationale, "Nessuna motivazione registrata.")}
            </p>
            <RawPayload value={decision.payload} />
          </Panel>
        );
      })}
    </div>
  );
}

// --- risk gate ---------------------------------------------------------------

export function RiskSection({ decisions }: { decisions: Decision[] }) {
  const d = useDisplay();
  return (
    <div className="space-y-3">
      {decisions.map((decision) => {
        const approved = decision.payload.approved === true;
        const order = (decision.payload.order ?? {}) as Record<string, unknown>;
        const amount = num(order.amount_usd);
        const reasons = Array.isArray(decision.payload.reasons)
          ? (decision.payload.reasons as unknown[]).map((r) => str(r))
          : [];
        return (
          <Panel
            key={decision.id}
            className={approved ? "border-positive/30" : "border-negative/30"}
          >
            <CardHead symbol={decision.symbol}>
              <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
                {amount === null ? "" : d.money(amount)}
              </span>
              <Stamp tone={approved ? "approved" : "rejected"}>
                {approved ? "Approvato" : "Respinto"}
              </Stamp>
            </CardHead>
            {approved ? (
              <p className="text-muted-foreground text-[13px]">
                Nessun limite violato: l&apos;ordine passa all&apos;executor.
              </p>
            ) : (
              <ul className="space-y-1.5">
                {reasons.length === 0 ? (
                  <li className="text-muted-foreground text-[13px]">
                    Respinto senza motivazione registrata.
                  </li>
                ) : (
                  reasons.map((reason, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-2 text-[13px] leading-relaxed"
                    >
                      <span
                        aria-hidden
                        className="bg-negative mt-[7px] size-1 shrink-0 rounded-full"
                      />
                      {reason}
                    </li>
                  ))
                )}
              </ul>
            )}
            <RawPayload value={decision.payload} />
          </Panel>
        );
      })}
    </div>
  );
}

// --- anomalie di riconciliazione ---------------------------------------------

export function AnomalySection({ decisions }: { decisions: Decision[] }) {
  const d = useDisplay();
  return (
    <div className="space-y-3">
      {decisions.map((decision) => {
        const pnl = num(decision.payload.realized_pnl_usd);
        return (
          <Panel key={decision.id} className="border-caution/40 bg-caution/5">
            <CardHead symbol={decision.symbol}>
              {pnl !== null ? (
                <span
                  className={cn(
                    "font-mono text-[11px] font-medium tabular-nums",
                    pnl >= 0 ? "text-positive" : "text-negative",
                  )}
                >
                  {d.moneySigned(pnl)}
                </span>
              ) : null}
              <Stamp tone="caution">Chiusa fuori dal bot</Stamp>
            </CardHead>
            <p className="text-[13px] leading-relaxed">
              {str(
                decision.payload.detail,
                "Posizione del registry non più presente sul conto eToro.",
              )}
            </p>
            <RawPayload value={decision.payload} />
          </Panel>
        );
      })}
    </div>
  );
}
