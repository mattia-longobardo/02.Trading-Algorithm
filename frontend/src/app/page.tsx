"use client";

import { useState } from "react";
import { triggerJob, type JobResponse } from "@/lib/api";

interface ActionDef {
  label: string;
  description: string;
  path: string;
}

const ACTIONS: ActionDef[] = [
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
    description: "Genera il report PnL della settimana appena conclusa.",
    path: "/api/report/generate",
  },
  {
    label: "Report trimestrale",
    description: "Report del trimestre appena concluso.",
    path: "/api/report/quarterly",
  },
  {
    label: "Report semestrale",
    description: "Report del semestre appena concluso.",
    path: "/api/report/biannual",
  },
  {
    label: "Report annuale",
    description: "Report dell'anno solare appena concluso.",
    path: "/api/report/annual",
  },
  {
    label: "Reset scheduler",
    description: "Sblocca lo scheduler se risulta in stallo.",
    path: "/api/scheduler/reset",
  },
];

export default function HomePage() {
  const [pending, setPending] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});

  async function run(action: ActionDef) {
    setPending(action.path);
    try {
      const result: JobResponse = await triggerJob(action.path);
      setResults((prev) => ({
        ...prev,
        [action.path]: { ok: result.status === "ok", message: result.message },
      }));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Errore sconosciuto";
      setResults((prev) => ({ ...prev, [action.path]: { ok: false, message } }));
    } finally {
      setPending(null);
    }
  }

  return (
    <section className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Dashboard</h1>
        <p className="mt-2 text-sm text-(--color-muted)">
          Trigger manuale dei job dello scheduler. Le chiamate usano lo stesso lock dei job
          schedulati: se uno è in esecuzione la risposta sarà <code>409 Conflict</code>.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {ACTIONS.map((action) => {
          const result = results[action.path];
          const isPending = pending === action.path;
          return (
            <article
              key={action.path}
              className="rounded-2xl border border-(--color-line) bg-(--color-panel)/80 p-5"
            >
              <h2 className="text-lg font-semibold">{action.label}</h2>
              <p className="mt-1 text-sm text-(--color-muted)">{action.description}</p>
              <button
                onClick={() => run(action)}
                disabled={isPending}
                className="mt-4 inline-flex items-center rounded-lg bg-(--color-accent) px-3 py-2 text-sm font-medium text-slate-950 transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isPending ? "In esecuzione..." : "Esegui"}
              </button>
              {result && (
                <p
                  className={`mt-3 text-sm ${
                    result.ok ? "text-(--color-accent)" : "text-rose-400"
                  }`}
                >
                  {result.message}
                </p>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
