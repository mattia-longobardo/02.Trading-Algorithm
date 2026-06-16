"use client";

import { useMemo, useState } from "react";
import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/cn";

export type DateRange = { from: Date | null; to: Date | null };

type Preset = { label: string; days: number | null };

// days=null means "All history" (no bounds).
const PRESETS: Preset[] = [
  { label: "Ultimo giorno", days: 1 },
  { label: "Ultima settimana", days: 7 },
  { label: "Ultimo mese", days: 30 },
  { label: "Ultimi 3 mesi", days: 90 },
  { label: "Ultimi 6 mesi", days: 180 },
  { label: "Ultimo anno", days: 365 },
  { label: "Storico completo", days: null },
];

const WEEKDAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"];
const MONTHS = [
  "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
  "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
];

function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function sameDay(a: Date | null, b: Date | null): boolean {
  return !!a && !!b && startOfDay(a).getTime() === startOfDay(b).getTime();
}

function inRange(day: Date, from: Date | null, to: Date | null): boolean {
  if (!from || !to) return false;
  const t = startOfDay(day).getTime();
  return t >= startOfDay(from).getTime() && t <= startOfDay(to).getTime();
}

function formatShort(d: Date): string {
  return d.toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "2-digit" });
}

export function formatRangeLabel(range: DateRange): string {
  if (!range.from && !range.to) return "Storico completo";
  if (range.from && range.to) {
    if (sameDay(range.from, range.to)) return formatShort(range.from);
    return `${formatShort(range.from)} – ${formatShort(range.to)}`;
  }
  if (range.from) return `Dal ${formatShort(range.from)}`;
  return "Storico completo";
}

// 6-week (42-cell) grid starting on Monday for the given month.
function monthGrid(year: number, month: number): Date[] {
  const first = new Date(year, month, 1);
  const offset = (first.getDay() + 6) % 7; // Monday = 0
  const start = new Date(year, month, 1 - offset);
  return Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
}

export function DateRangePicker({
  value,
  onChange,
}: {
  value: DateRange;
  onChange: (range: DateRange) => void;
}) {
  const [open, setOpen] = useState(false);
  const initial = value.from ?? value.to ?? new Date();
  const [viewYear, setViewYear] = useState(initial.getFullYear());
  const [viewMonth, setViewMonth] = useState(initial.getMonth());

  const days = useMemo(() => monthGrid(viewYear, viewMonth), [viewYear, viewMonth]);

  function applyPreset(p: Preset) {
    if (p.days === null) {
      onChange({ from: null, to: null });
    } else {
      const to = new Date();
      const from = new Date();
      from.setDate(from.getDate() - p.days);
      onChange({ from: startOfDay(from), to: startOfDay(to) });
    }
    setOpen(false);
  }

  function pickDay(day: Date) {
    const d = startOfDay(day);
    // First click (or restart): set "from" and clear "to".
    if (!value.from || (value.from && value.to)) {
      onChange({ from: d, to: null });
      return;
    }
    // Second click: set the other end, ordered.
    if (d.getTime() < value.from.getTime()) {
      onChange({ from: d, to: value.from });
    } else {
      onChange({ from: value.from, to: d });
    }
  }

  function shiftMonth(delta: number) {
    const next = new Date(viewYear, viewMonth + delta, 1);
    setViewYear(next.getFullYear());
    setViewMonth(next.getMonth());
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="inline-flex h-9 items-center gap-2 rounded-lg border border-(--color-line) bg-(--color-field) px-3 text-sm text-(--color-text) transition-colors hover:border-(--color-muted) focus:outline-none focus:ring-2 focus:ring-(--color-accent)/40"
        >
          <CalendarDays className="size-4 text-(--color-muted)" />
          <span className="tnum tabular-nums">{formatRangeLabel(value)}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-auto">
        <div className="flex flex-col gap-3 sm:flex-row">
          {/* Presets */}
          <div className="flex min-w-40 flex-col gap-1 sm:border-r sm:border-(--color-line) sm:pr-3">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => applyPreset(p)}
                className="rounded-md px-2 py-1.5 text-left text-sm text-(--color-text) transition-colors hover:bg-(--color-hover)"
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Calendar */}
          <div className="w-64">
            <div className="mb-2 flex items-center justify-between">
              <button
                type="button"
                aria-label="Mese precedente"
                onClick={() => shiftMonth(-1)}
                className="rounded-md p-1 text-(--color-muted) hover:bg-(--color-hover) hover:text-(--color-text)"
              >
                <ChevronLeft className="size-4" />
              </button>
              <span className="text-sm font-medium capitalize">
                {MONTHS[viewMonth]} {viewYear}
              </span>
              <button
                type="button"
                aria-label="Mese successivo"
                onClick={() => shiftMonth(1)}
                className="rounded-md p-1 text-(--color-muted) hover:bg-(--color-hover) hover:text-(--color-text)"
              >
                <ChevronRight className="size-4" />
              </button>
            </div>
            <div className="grid grid-cols-7 gap-0.5 text-center text-[10px] uppercase text-(--color-muted)">
              {WEEKDAYS.map((w) => (
                <span key={w} className="py-1">{w}</span>
              ))}
            </div>
            <div className="grid grid-cols-7 gap-0.5">
              {days.map((day) => {
                const isCurrentMonth = day.getMonth() === viewMonth;
                const selectedEdge = sameDay(day, value.from) || sameDay(day, value.to);
                const within = inRange(day, value.from, value.to);
                return (
                  <button
                    key={day.toISOString()}
                    type="button"
                    onClick={() => pickDay(day)}
                    className={cn(
                      "h-8 rounded-md text-xs tabular-nums transition-colors",
                      !isCurrentMonth && "text-(--color-muted)/50",
                      isCurrentMonth && "text-(--color-text)",
                      within && !selectedEdge && "bg-(--color-accent)/15",
                      selectedEdge
                        ? "bg-(--color-accent) text-black font-semibold"
                        : "hover:bg-(--color-hover)"
                    )}
                  >
                    {day.getDate()}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
}
