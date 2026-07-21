// Elenco completo dei fusi IANA per il selettore delle Impostazioni.
//
// `Intl.supportedValuesOf("timeZone")` è la fonte giusta: la lista arriva dal
// database tz del browser, quindi resta allineata senza doverla manutenere a
// mano. Il fallback copre i browser che non espongono l'API (e il rendering
// server-side, dove comunque il valore serve solo a disegnare il bottone).

import { tzOffsetLabel, tzOffsetMinutes } from "@/lib/format";
import type { SearchableOption } from "@/components/ui/searchable-select";

const FALLBACK_ZONES = [
  "UTC",
  "Europe/Rome", "Europe/London", "Europe/Paris", "Europe/Berlin", "Europe/Madrid",
  "Europe/Lisbon", "Europe/Amsterdam", "Europe/Zurich", "Europe/Athens", "Europe/Moscow",
  "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
  "America/Toronto", "America/Sao_Paulo", "America/Mexico_City",
  "Asia/Tokyo", "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore", "Asia/Seoul",
  "Asia/Kolkata", "Asia/Dubai", "Asia/Jerusalem",
  "Australia/Sydney", "Australia/Melbourne", "Pacific/Auckland",
];

export function allTimeZones(): string[] {
  try {
    const supported = Intl.supportedValuesOf?.("timeZone");
    if (supported?.length) {
      // "UTC" non è sempre incluso nella lista IANA restituita dal browser.
      return supported.includes("UTC") ? supported : ["UTC", ...supported];
    }
  } catch {
    // API non disponibile: si usa la lista di riserva.
  }
  return FALLBACK_ZONES;
}

/**
 * Opzioni per SearchableSelect: etichetta leggibile ("Europe / Rome"), offset
 * corrente come hint, e il nome IANA grezzo fra le keyword così la ricerca
 * risponde sia a "rome" che a "Europe/Rome" che a "utc+2".
 *
 * Ordinate per scostamento da UTC crescente — da UTC-12 a UTC+14 — invece che
 * alfabeticamente: chi scorre la lista ragiona in "quante ore avanti o
 * indietro", non per nome del continente. A parità di offset vince l'ordine
 * alfabetico, così le città dello stesso fuso restano vicine e prevedibili.
 */
export function timeZoneOptions(zones: string[] = allTimeZones()): SearchableOption[] {
  const now = new Date();
  return zones
    .map((zone) => {
      const offset = tzOffsetLabel(zone, now);
      return {
        minutes: tzOffsetMinutes(zone, now),
        option: {
          value: zone,
          label: zone.replace(/_/g, " ").replace("/", " / "),
          hint: offset,
          keywords: `${zone} ${offset}`,
        },
      };
    })
    .sort((a, b) => a.minutes - b.minutes || a.option.label.localeCompare(b.option.label))
    .map((entry) => entry.option);
}
