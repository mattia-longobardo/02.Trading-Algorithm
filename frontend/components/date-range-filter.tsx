"use client";

import * as React from "react";
import { CalendarDaysIcon } from "lucide-react";
import { endOfMonth, format, startOfMonth, startOfYear, subDays, subMonths } from "date-fns";
import { it } from "date-fns/locale";
import type { DateRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useIsMobile } from "@/hooks/use-mobile";
import type { DateRangeValue } from "@/lib/types";
import { cn } from "@/lib/utils";

const iso = (value: Date) => format(value, "yyyy-MM-dd");
const fromIso = (value: string) => new Date(`${value}T12:00:00`);

export function lastDaysRange(days = 90): DateRangeValue {
  const today = new Date();
  return { from: iso(subDays(today, days - 1)), to: iso(today) };
}

const presetRange = (key: string): DateRangeValue => {
  const today = new Date();
  if (key === "month") return { from: iso(startOfMonth(today)), to: iso(today) };
  if (key === "prev-month") {
    const previous = subMonths(today, 1);
    return { from: iso(startOfMonth(previous)), to: iso(endOfMonth(previous)) };
  }
  if (key === "ytd") return { from: iso(startOfYear(today)), to: iso(today) };
  return lastDaysRange(Number(key));
};

const presets = [
  ["1", "Oggi"], ["7", "7 giorni"], ["30", "30 giorni"],
  ["60", "60 giorni"], ["90", "90 giorni"], ["month", "Questo mese"],
  ["prev-month", "Mese scorso"], ["ytd", "Da inizio anno"],
] as const;

export function DateRangeFilter({ value, onChange, label = "Periodo", className }: {
  value: DateRangeValue;
  onChange: (value: DateRangeValue) => void;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<DateRange>({ from: fromIso(value.from), to: fromIso(value.to) });
  const isMobile = useIsMobile();

  // Il calendario parte dall'ultimo mese dell'intervallo: con due mesi
  // affiancati si vede la coda della selezione senza dover navigare.
  const [month, setMonth] = React.useState<Date>(fromIso(value.to));

  const draftIso = draft.from && draft.to
    ? { from: iso(draft.from), to: iso(draft.to) }
    : null;
  const activePreset = draftIso
    ? presets.find(([key]) => {
        const range = presetRange(key);
        return range.from === draftIso.from && range.to === draftIso.to;
      })?.[0]
    : undefined;

  const applyPreset = (key: string) => {
    const next = presetRange(key);
    setDraft({ from: fromIso(next.from), to: fromIso(next.to) });
    setMonth(fromIso(next.to));
  };

  const apply = () => {
    if (!draftIso) return;
    onChange(draftIso);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={(next) => {
      setOpen(next);
      if (next) {
        setDraft({ from: fromIso(value.from), to: fromIso(value.to) });
        setMonth(fromIso(value.to));
      }
    }}>
      <PopoverTrigger asChild>
        <Button variant="outline" className={cn("justify-start font-mono text-xs tabular-nums", className)} aria-label={`${label}: seleziona intervallo`}>
          <CalendarDaysIcon data-icon="inline-start" aria-hidden="true" />
          <span className="text-muted-foreground mr-1 hidden sm:inline">{label}</span>
          {format(fromIso(value.from), "dd MMM yy", { locale: it })} – {format(fromIso(value.to), "dd MMM yy", { locale: it })}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-auto max-w-[96vw] gap-0 p-0">
        <div className="flex flex-col sm:flex-row">
          {/* Preset in colonna: una voce per riga, invece del wrap orizzontale
              che li spezzava in due file disallineate. */}
          <div className="border-b p-2 sm:w-40 sm:shrink-0 sm:border-r sm:border-b-0">
            <p className="text-muted-foreground px-2 pt-1 pb-2 font-mono text-[10px] tracking-[0.14em] uppercase">
              Intervalli
            </p>
            <div className="grid grid-cols-2 gap-1 sm:grid-cols-1" aria-label="Intervalli predefiniti">
              {presets.map(([key, text]) => (
                <Button
                  key={key}
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-pressed={activePreset === key}
                  onClick={() => applyPreset(key)}
                  className={cn(
                    "h-7 justify-start px-2 text-xs font-normal",
                    activePreset === key && "bg-accent text-accent-foreground font-medium",
                  )}
                >
                  {text}
                </Button>
              ))}
            </div>
          </div>

          <div className="p-2">
            <Calendar
              mode="range"
              required
              selected={draft}
              onSelect={setDraft}
              month={month}
              onMonthChange={setMonth}
              numberOfMonths={isMobile ? 1 : 2}
              showOutsideDays={false}
              locale={it}
              captionLayout="dropdown"
              startMonth={new Date(2015, 0)}
              endMonth={new Date()}
              disabled={{ after: new Date() }}
            />
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 border-t px-3 py-2.5">
          <span className="text-muted-foreground font-mono text-[11px] tabular-nums">
            {draft.from ? format(draft.from, "dd/MM/yyyy") : "—"} – {draft.to ? format(draft.to, "dd/MM/yyyy") : "—"}
          </span>
          <Button size="sm" disabled={!draftIso} onClick={apply}>Applica</Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
