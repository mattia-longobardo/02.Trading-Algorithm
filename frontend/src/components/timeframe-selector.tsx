"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

export type Timeframe = "1D" | "1W" | "1M" | "3M" | "6M" | "YTD" | "1Y" | "All";

const OPTIONS: { value: Timeframe; label: string }[] = [
  { value: "1D", label: "Ultimo giorno" },
  { value: "1W", label: "Ultima settimana" },
  { value: "1M", label: "Ultimo mese" },
  { value: "3M", label: "Ultimi 3 mesi" },
  { value: "6M", label: "Ultimi 6 mesi" },
  { value: "YTD", label: "Da inizio anno" },
  { value: "1Y", label: "Ultimo anno" },
  { value: "All", label: "Storico completo" },
];

export function TimeframeSelector({
  value,
  onChange,
}: {
  value: Timeframe;
  onChange: (value: Timeframe) => void;
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as Timeframe)}>
      <SelectTrigger className="w-52">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {OPTIONS.map((opt) => (
          <SelectItem key={opt.value} value={opt.value}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
