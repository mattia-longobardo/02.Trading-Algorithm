/**
 * Lettura in italiano dell'esito di una run.
 *
 * La pipeline è una catena che si può interrompere a ogni anello
 * (screener → analisti → debate → portfolio manager → risk gate → executor):
 * qui si stabilisce DOVE si è fermata e si scrive la frase che lo spiega, così
 * elenco e dettaglio raccontano la stessa storia con le stesse parole.
 */

import type { Decision, RunSummary } from "@/lib/types";

export type OutcomeTone = "approved" | "rejected" | "neutral" | "caution";

export interface RunOutcome {
  /** Timbro compatto per l'elenco. */
  label: string;
  tone: OutcomeTone;
  /** Frase completa per il dettaglio: dove si è fermata e perché. */
  headline: string;
}

/** Conteggi ricavati dai verdetti del debate, quando disponibili. */
export interface VerdictCounts {
  total: number;
  openLong: number;
  close: number;
  avoid: number;
}

export function countVerdicts(decisions: Decision[]): VerdictCounts {
  const counts: VerdictCounts = { total: 0, openLong: 0, close: 0, avoid: 0 };
  for (const decision of decisions) {
    if (decision.stage !== "debate") continue;
    counts.total += 1;
    const value = String(decision.payload?.decision ?? "");
    if (value === "open_long") counts.openLong += 1;
    else if (value === "close") counts.close += 1;
    else counts.avoid += 1;
  }
  return counts;
}

const plural = (n: number, one: string, many: string) =>
  `${n} ${n === 1 ? one : many}`;

export function describeRun(
  summary: RunSummary | null | undefined,
  verdicts?: VerdictCounts,
): RunOutcome {
  if (!summary) {
    return {
      label: "In corso",
      tone: "caution",
      headline:
        "Run ancora in corso (o interrotta prima del journal): il riepilogo non è stato scritto.",
    };
  }

  const { candidates, proposed, approved, rejected, executed } = summary;
  const actionable = verdicts ? verdicts.openLong + verdicts.close : null;

  if (executed > 0) {
    return {
      label: `${plural(executed, "ordine eseguito", "ordini eseguiti")}`,
      tone: "approved",
      headline: `La pipeline è arrivata in fondo: ${plural(executed, "ordine eseguito", "ordini eseguiti")} su ${plural(approved, "approvato", "approvati")} dal risk gate.`,
    };
  }

  if (candidates === 0) {
    return {
      label: "Nessun candidato",
      tone: "caution",
      headline:
        "Lo screener non ha prodotto candidati: nessun simbolo della watchlist è risultato tradabile con un prezzo corrente, quindi il resto della pipeline non è partito.",
    };
  }

  if (verdicts && verdicts.total === 0) {
    return {
      label: "Nessun verdetto",
      tone: "caution",
      headline: `I ${candidates} candidati non hanno prodotto verdetti: il debate non è arrivato in fondo (di norma per un errore degli analisti o del modello).`,
    };
  }

  if (actionable === 0) {
    return {
      label: "Tutti «evita»",
      tone: "neutral",
      headline: `Si è fermata al debate: il giudice ha risposto «evita» su tutti e ${verdicts!.total} i candidati, quindi al portfolio manager non è arrivato niente da trasformare in ordini. È il comportamento previsto — il giudice apre una posizione solo se il caso rialzista è nettamente più forte di quello ribassista.`,
    };
  }

  if (proposed === 0) {
    const source =
      actionable === null
        ? "dei verdetti operativi del debate"
        : `${plural(actionable, "verdetto operativo", "verdetti operativi")} del debate`;
    return {
      label: "Nessun ordine",
      tone: "neutral",
      headline: `Si è fermata al portfolio manager: nessuno ${source} è stato tradotto in un ordine.`,
    };
  }

  if (approved === 0) {
    return {
      label: "Tutti respinti",
      tone: "rejected",
      headline: `Si è fermata al risk gate: tutti e ${plural(rejected, "ordine proposto è stato respinto", "gli ordini proposti sono stati respinti")}. Le motivazioni sono nella sezione Risk gate.`,
    };
  }

  return {
    label: "Nessuna esecuzione",
    tone: "caution",
    headline: `${plural(approved, "ordine approvato", "ordini approvati")} dal risk gate, ma nessuna esecuzione è andata a buon fine: il dettaglio è nella sezione Esecuzioni.`,
  };
}
