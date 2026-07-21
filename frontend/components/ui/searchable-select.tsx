"use client";

/**
 * Select con campo di ricerca, per elenchi troppo lunghi da scorrere a mano
 * (le ~450 timezone IANA, le valute). Scritto sui primitivi già in uso —
 * Popover + Input — invece di aggiungere `cmdk` come dipendenza per un solo
 * componente.
 */

import * as React from "react";
import { CheckIcon, ChevronsUpDownIcon, SearchIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export interface SearchableOption {
  value: string;
  label: string;
  /** Testo secondario (offset del fuso, nome della valuta…). */
  hint?: string;
  /** Termini extra su cui deve rispondere la ricerca. */
  keywords?: string;
}

function normalise(text: string) {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[_/]/g, " ");
}

export function SearchableSelect({
  value,
  onValueChange,
  options,
  placeholder = "Seleziona…",
  searchPlaceholder = "Cerca…",
  emptyText = "Nessun risultato",
  id,
  className,
  disabled,
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: SearchableOption[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  id?: string;
  className?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [highlight, setHighlight] = React.useState(0);
  const listRef = React.useRef<HTMLDivElement>(null);

  const selected = options.find((option) => option.value === value);

  const filtered = React.useMemo(() => {
    const terms = normalise(query).split(/\s+/).filter(Boolean);
    if (!terms.length) return options;
    return options.filter((option) => {
      const haystack = normalise(
        `${option.value} ${option.label} ${option.hint ?? ""} ${option.keywords ?? ""}`,
      );
      return terms.every((term) => haystack.includes(term));
    });
  }, [options, query]);

  // Lo stato si aggiorna negli handler, non in effetti: la riga evidenziata
  // riparte dall'alto a ogni ricerca e all'apertura si posiziona sul valore
  // corrente, così Invio non cambia niente per sbaglio.
  const changeQuery = (next: string) => {
    setQuery(next);
    setHighlight(0);
  };

  const toggle = (next: boolean) => {
    setOpen(next);
    if (next) {
      setQuery("");
      const index = options.findIndex((option) => option.value === value);
      setHighlight(index < 0 ? 0 : index);
    }
  };

  React.useEffect(() => {
    if (!open) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-index="${highlight}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [highlight, open]);

  const choose = (option: SearchableOption) => {
    onValueChange(option.value);
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!filtered.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setHighlight((current) => (current + step + filtered.length) % filtered.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      const option = filtered[highlight];
      if (option) choose(option);
    }
  };

  return (
    <Popover open={open} onOpenChange={disabled ? undefined : toggle}>
      <PopoverTrigger asChild>
        <Button
          id={id}
          type="button"
          variant="outline"
          role="combobox"
          aria-expanded={open}
          disabled={disabled}
          className={cn("w-full justify-between font-normal", className)}
        >
          <span className={cn("truncate", !selected && "text-muted-foreground")}>
            {selected ? selected.label : placeholder}
          </span>
          {selected?.hint && (
            <span className="text-muted-foreground ml-auto shrink-0 font-mono text-[11px] tabular-nums">
              {selected.hint}
            </span>
          )}
          <ChevronsUpDownIcon className="text-muted-foreground ml-1 size-3.5 shrink-0" aria-hidden="true" />
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-(--radix-popover-trigger-width) min-w-56 gap-0 p-0"
        onKeyDown={onKeyDown}
      >
        <div className="relative border-b">
          <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2" aria-hidden="true" />
          <Input
            autoFocus
            value={query}
            onChange={(event) => changeQuery(event.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="h-9 rounded-none border-0 pl-8 shadow-none focus-visible:ring-0"
          />
        </div>
        <div ref={listRef} role="listbox" className="max-h-64 overflow-y-auto p-1">
          {filtered.length === 0 ? (
            <p className="text-muted-foreground px-3 py-6 text-center text-xs">{emptyText}</p>
          ) : (
            filtered.map((option, index) => {
              const active = option.value === value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="option"
                  aria-selected={active}
                  data-index={index}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => choose(option)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm",
                    index === highlight && "bg-accent text-accent-foreground",
                  )}
                >
                  <CheckIcon
                    className={cn("size-3.5 shrink-0", active ? "opacity-100" : "opacity-0")}
                    aria-hidden="true"
                  />
                  <span className="truncate">{option.label}</span>
                  {option.hint && (
                    <span className="text-muted-foreground ml-auto shrink-0 font-mono text-[11px] tabular-nums">
                      {option.hint}
                    </span>
                  )}
                </button>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
