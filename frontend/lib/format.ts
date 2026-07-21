// Formattatori condivisi (locale it-IT).
//
// Importi: il backend espone tutto in USD (eToro ragiona in dollari). Questi
// formattatori ricevono l'importo *già convertito* e la sigla della valuta da
// stampare: la conversione vive in lib/money.tsx, così qui non c'è stato.
//
// Date: il fuso è sempre esplicito. `timeZone: undefined` = fuso del browser,
// "UTC" = orario di esecuzione, la timezone delle impostazioni = lettura utente.

export const ND = "n/d";

const cache = new Map<string, Intl.NumberFormat>();

function money(currency: string, compact: boolean): Intl.NumberFormat {
  const key = `${currency}|${compact}`;
  let fmt = cache.get(key);
  if (!fmt) {
    fmt = new Intl.NumberFormat("it-IT", {
      style: "currency",
      currency,
      ...(compact
        ? { notation: "compact" as const, maximumFractionDigits: 1 }
        : { maximumFractionDigits: 2 }),
    });
    cache.set(key, fmt);
  }
  return fmt;
}

const numFmt = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 2 });

export function fmtMoney(v: number | null | undefined, currency = "USD"): string {
  return v == null ? ND : money(currency, false).format(v);
}

export function fmtMoneyCompact(v: number | null | undefined, currency = "USD"): string {
  return v == null ? ND : money(currency, true).format(v);
}

/** Importo con segno esplicito (+/−) per PnL e variazioni. */
export function fmtMoneySigned(v: number | null | undefined, currency = "USD"): string {
  if (v == null) return ND;
  const s = money(currency, false).format(Math.abs(v));
  return v >= 0 ? `+${s}` : `−${s}`;
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return ND;
  return new Intl.NumberFormat("it-IT", { maximumFractionDigits: digits }).format(v);
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null) return ND;
  return `${numFmt.format(Number(v.toFixed(digits)))}%`;
}

/** Percentuale con segno esplicito (+/−) per PnL e variazioni. */
export function fmtPctSigned(v: number | null | undefined, digits = 2): string {
  if (v == null) return ND;
  const s = fmtPct(Math.abs(v), digits);
  return v >= 0 ? `+${s}` : `−${s}`;
}

function parse(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Una data senza orario ("2026-07-21") indica un giorno di calendario, non un
 * istante: JS la parsa a mezzanotte UTC, quindi riformattarla in un fuso a
 * ovest di Greenwich la farebbe scalare al giorno precedente. In quel caso il
 * fuso va ignorato e si legge la data così com'è.
 */
function zoneFor(iso: string | null | undefined, timeZone?: string) {
  return iso && DATE_ONLY.test(iso) ? "UTC" : timeZone;
}

export function fmtDateTime(iso: string | null | undefined, timeZone?: string): string {
  const d = parse(iso);
  if (!d) return iso || ND;
  return d.toLocaleString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  });
}

/** Solo l'ora (HH:MM) nel fuso indicato — per «prossima run» in barra. */
export function fmtTime(iso: string | null | undefined, timeZone?: string): string {
  const d = parse(iso);
  if (!d) return ND;
  return d.toLocaleTimeString("it-IT", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  });
}

export function fmtDate(iso: string | null | undefined, timeZone?: string): string {
  const d = parse(iso);
  if (!d) return iso || ND;
  return d.toLocaleDateString("it-IT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: zoneFor(iso, timeZone),
  });
}

export function fmtDateShort(iso: string, timeZone?: string): string {
  const d = parse(iso);
  if (!d) return iso;
  return d.toLocaleDateString("it-IT", {
    day: "2-digit",
    month: "short",
    timeZone: zoneFor(iso, timeZone),
  });
}

/**
 * Sigla del fuso (CEST, UTC, JST…) per etichettare gli orari mostrati.
 * Senza sigla un orario in un fuso diverso da quello del browser è ambiguo.
 */
export function tzAbbrev(timeZone: string, at: Date = new Date()): string {
  try {
    const part = new Intl.DateTimeFormat("en-US", {
      timeZone,
      timeZoneName: "short",
    })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName");
    return part?.value ?? timeZone;
  } catch {
    return timeZone;
  }
}

/**
 * Scostamento del fuso da UTC in minuti (negativo a ovest di Greenwich).
 * Serve a ordinare l'elenco dei fusi: l'ordine alfabetico dei nomi IANA non
 * dice niente a chi cerca «quello due ore avanti».
 */
export function tzOffsetMinutes(timeZone: string, at: Date = new Date()): number {
  try {
    const part = new Intl.DateTimeFormat("en-US", {
      timeZone,
      timeZoneName: "longOffset",
    })
      .formatToParts(at)
      .find((p) => p.type === "timeZoneName");
    // "GMT+02:00" → 120 · "GMT-05:30" → -330 · "GMT" → 0
    const raw = (part?.value ?? "GMT").replace("GMT", "");
    if (!raw) return 0;
    const sign = raw[0] === "-" ? -1 : 1;
    const [hours, minutes] = raw.slice(1).split(":").map(Number);
    return sign * (hours * 60 + (minutes || 0));
  } catch {
    return 0;
  }
}

/** Offset UTC del fuso, es. "UTC+2" o "UTC+5:30" — mostrato accanto al nome. */
export function tzOffsetLabel(timeZone: string, at: Date = new Date()): string {
  const total = tzOffsetMinutes(timeZone, at);
  if (total === 0) return "UTC";
  const sign = total < 0 ? "-" : "+";
  const hours = Math.floor(Math.abs(total) / 60);
  const minutes = Math.abs(total) % 60;
  return `UTC${sign}${hours}${minutes ? `:${String(minutes).padStart(2, "0")}` : ""}`;
}

/** Classe colore PnL: verde da stampa positivo, rosso da stampa negativo. */
export function pnlClass(v: number | null | undefined): string {
  if (v == null) return "text-muted-foreground";
  if (v > 0) return "text-positive";
  if (v < 0) return "text-negative";
  return "text-muted-foreground";
}
