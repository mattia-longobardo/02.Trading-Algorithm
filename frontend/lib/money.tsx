"use client";

/**
 * Valuta e fuso di visualizzazione, in un unico posto.
 *
 * eToro ragiona in dollari: equity, cash, PnL e prezzi arrivano dall'API in
 * USD e in USD restano nel journal. La valuta scelta nelle Impostazioni è
 * quindi solo un modo di *leggere* gli stessi numeri, applicato al momento del
 * rendering con i tassi BCE serviti da /fx/rates. Nessun dato viene riscritto,
 * così cambiare valuta non altera lo storico.
 *
 * Stesso ragionamento per il fuso: l'esecuzione è sempre in UTC, la timezone
 * delle Impostazioni serve solo a mostrare gli orari all'utente.
 */

import * as React from "react";

import {
  fmtDate,
  fmtDateShort,
  fmtDateTime,
  fmtMoney,
  fmtMoneyCompact,
  fmtMoneySigned,
  fmtTime,
  tzAbbrev,
} from "@/lib/format";
import { useFxRates, useSettings } from "@/lib/queries";

export interface Display {
  /** Sigla ISO della valuta di visualizzazione (USD se non configurata). */
  currency: string;
  /** Moltiplicatore USD→valuta; 1 finché i tassi non sono disponibili. */
  rate: number;
  /** true quando si stanno mostrando dollari perché il tasso manca. */
  fxStale: boolean;
  /** Timezone IANA di sola presentazione. */
  timeZone: string;
  /** Sigla del fuso (CEST, JST…) per etichettare gli orari. */
  tzLabel: string;

  /** USD → valuta di visualizzazione, senza formattazione. */
  convert(usd: number | null | undefined): number | null;
  /** Importo USD formattato nella valuta di visualizzazione. */
  money(usd: number | null | undefined): string;
  moneyCompact(usd: number | null | undefined): string;
  moneySigned(usd: number | null | undefined): string;

  /** Data/ora nel fuso di visualizzazione. */
  dateTime(iso: string | null | undefined): string;
  time(iso: string | null | undefined): string;
  date(iso: string | null | undefined): string;
  dateShort(iso: string): string;
}

const FALLBACK: Display = buildDisplay("USD", 1, false, "UTC");

function buildDisplay(
  currency: string,
  rate: number,
  fxStale: boolean,
  timeZone: string,
): Display {
  const convert = (usd: number | null | undefined) =>
    usd == null ? null : usd * rate;
  return {
    currency,
    rate,
    fxStale,
    timeZone,
    tzLabel: tzAbbrev(timeZone),
    convert,
    money: (usd) => fmtMoney(convert(usd), currency),
    moneyCompact: (usd) => fmtMoneyCompact(convert(usd), currency),
    moneySigned: (usd) => fmtMoneySigned(convert(usd), currency),
    dateTime: (iso) => fmtDateTime(iso, timeZone),
    time: (iso) => fmtTime(iso, timeZone),
    date: (iso) => fmtDate(iso, timeZone),
    dateShort: (iso) => fmtDateShort(iso, timeZone),
  };
}

const DisplayContext = React.createContext<Display>(FALLBACK);

/** Fuso del browser: default sensato finché le impostazioni non arrivano. */
function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function DisplayProvider({ children }: { children: React.ReactNode }) {
  const settings = useSettings();
  const fx = useFxRates();

  const currency = settings.data?.currency?.toUpperCase() || "USD";
  const timeZone = settings.data?.timezone || browserTimeZone();
  const rate = currency === "USD" ? 1 : fx.data?.rates?.[currency];

  const value = React.useMemo(
    // Tasso mancante ⇒ si mostrano dollari e lo si dichiara (fxStale), invece
    // di stampare numeri convertiti con un cambio inventato.
    () =>
      rate
        ? buildDisplay(currency, rate, Boolean(fx.data?.stale), timeZone)
        : buildDisplay("USD", 1, currency !== "USD", timeZone),
    [currency, rate, fx.data?.stale, timeZone],
  );

  return (
    <DisplayContext.Provider value={value}>{children}</DisplayContext.Provider>
  );
}

/** Formattatori di importi e date già allineati alle impostazioni. */
export function useDisplay(): Display {
  return React.useContext(DisplayContext);
}
