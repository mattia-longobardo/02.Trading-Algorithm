"use client";

import { Check, ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/cn";
import { type TradeCategory, type TradeStatus } from "@/lib/types";

export const TRADE_STATUS_OPTIONS: TradeStatus[] = ["PENDING", "OPEN", "CLOSED", "CANCELLED"];
export const DEFAULT_TRADE_STATUS_FILTER: TradeStatus[] = ["PENDING", "OPEN", "CLOSED"];
export const TRADE_CATEGORY_OPTIONS: TradeCategory[] = ["STOCK", "CRYPTO"];
export const DEFAULT_TRADE_CATEGORY_FILTER: TradeCategory[] = ["STOCK", "CRYPTO"];

interface TradesFiltersProps {
  statusFilter: TradeStatus[];
  categoryFilter: TradeCategory[];
  symbolFilter: string;
  onStatusChange: (value: TradeStatus[]) => void;
  onCategoryChange: (value: TradeCategory[]) => void;
  onSymbolChange: (value: string) => void;
}

interface PresetOption<T extends string> {
  label: string;
  values: readonly T[];
}

interface MultiSelectDropdownProps<T extends string> {
  label: string;
  options: readonly T[];
  selected: readonly T[];
  presets: readonly PresetOption<T>[];
  summary: string;
  onChange: (values: T[]) => void;
}

function normalizeSelection<T extends string>(values: readonly T[], options: readonly T[]): T[] {
  const selected = new Set(values);
  return options.filter((option) => selected.has(option));
}

function toggleOption<T extends string>(
  option: T,
  selected: readonly T[],
  options: readonly T[],
): T[] {
  const next = new Set(selected);
  if (next.has(option)) {
    next.delete(option);
  } else {
    next.add(option);
  }
  return normalizeSelection(Array.from(next), options);
}

function sameSelection<T extends string>(a: readonly T[], b: readonly T[]): boolean {
  return a.length === b.length && a.every((value) => b.includes(value));
}

function statusSummary(selected: readonly TradeStatus[]): string {
  if (sameSelection(selected, TRADE_STATUS_OPTIONS)) return "Tutti";
  if (sameSelection(selected, DEFAULT_TRADE_STATUS_FILTER)) return "Attivi";
  if (selected.length === 0) return "Nessuno";
  if (selected.length <= 2) return selected.join(", ");
  return `${selected.length} stati`;
}

function categorySummary(selected: readonly TradeCategory[]): string {
  if (sameSelection(selected, TRADE_CATEGORY_OPTIONS)) return "Tutte";
  if (selected.length === 0) return "Nessuna";
  return selected.join(", ");
}

function MultiSelectDropdown<T extends string>({
  label,
  options,
  selected,
  presets,
  summary,
  onChange,
}: MultiSelectDropdownProps<T>) {
  return (
    <div className="space-y-1">
      <label className="text-xs uppercase text-(--color-muted)">{label}</label>
      <Popover>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="h-9 w-full justify-between px-3 font-normal"
            aria-label={`${label}: ${summary}`}
          >
            <span className="truncate">{summary}</span>
            <ChevronDown className="size-4 shrink-0 text-(--color-muted)" aria-hidden="true" />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[var(--radix-popover-trigger-width)] min-w-56 p-1">
          <div className="space-y-1">
            {presets.map((preset) => {
              const active = sameSelection(selected, preset.values);
              return (
                <button
                  key={preset.label}
                  type="button"
                  className={cn(
                    "flex h-8 w-full items-center rounded-md px-2 text-left text-sm transition-colors hover:bg-(--color-hover)",
                    active && "bg-(--color-hover) text-(--color-text)",
                  )}
                  aria-pressed={active}
                  onClick={() => onChange(normalizeSelection(preset.values, options))}
                >
                  {preset.label}
                </button>
              );
            })}
          </div>
          <div className="my-1 h-px bg-(--color-line)" />
          <div className="space-y-1">
            {options.map((option) => {
              const checked = selected.includes(option);
              return (
                <button
                  key={option}
                  type="button"
                  className={cn(
                    "flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-(--color-hover)",
                    checked && "text-(--color-text)",
                  )}
                  aria-pressed={checked}
                  onClick={() => onChange(toggleOption(option, selected, options))}
                >
                  <span className="flex size-4 items-center justify-center rounded border border-(--color-line)">
                    {checked && <Check className="size-3 text-(--color-accent)" aria-hidden="true" />}
                  </span>
                  <span>{option}</span>
                </button>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

export function TradesFilters({
  statusFilter,
  categoryFilter,
  symbolFilter,
  onStatusChange,
  onCategoryChange,
  onSymbolChange,
}: TradesFiltersProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Filtri</CardTitle>
      </CardHeader>
      <CardContent className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <MultiSelectDropdown
          label="Stato"
          options={TRADE_STATUS_OPTIONS}
          selected={statusFilter}
          presets={[
            { label: "Attivi", values: DEFAULT_TRADE_STATUS_FILTER },
            { label: "Tutti", values: TRADE_STATUS_OPTIONS },
          ]}
          summary={statusSummary(statusFilter)}
          onChange={onStatusChange}
        />
        <MultiSelectDropdown
          label="Categoria"
          options={TRADE_CATEGORY_OPTIONS}
          selected={categoryFilter}
          presets={[{ label: "Tutte", values: TRADE_CATEGORY_OPTIONS }]}
          summary={categorySummary(categoryFilter)}
          onChange={onCategoryChange}
        />
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Cerca</label>
          <Input
            value={symbolFilter}
            onChange={(e) => onSymbolChange(e.target.value)}
            placeholder="Simbolo o nome, anche parziale"
          />
        </div>
      </CardContent>
    </Card>
  );
}
