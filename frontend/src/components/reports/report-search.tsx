"use client";

import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export interface ReportSearchProps {
  q: string;
  onQChange: (v: string) => void;
  fullText: boolean;
  onFullTextChange: (v: boolean) => void;
  typeFilter: string;
  onTypeFilterChange: (v: string) => void;
}

export function ReportSearch({
  q,
  onQChange,
  fullText,
  onFullTextChange,
  typeFilter,
  onTypeFilterChange,
}: ReportSearchProps) {
  return (
    <div className="grid gap-3 md:grid-cols-3">
      <div className="md:col-span-2 space-y-1">
        <label className="text-xs uppercase text-(--color-muted)">Cerca</label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-(--color-muted)" />
            <Input
              className="pl-9"
              value={q}
              onChange={(e) => onQChange(e.target.value)}
              placeholder="filename, tag o contenuto JSON…"
            />
          </div>
          <label className="flex items-center gap-2 text-xs text-(--color-muted)">
            <input
              type="checkbox"
              checked={fullText}
              onChange={(e) => onFullTextChange(e.target.checked)}
            />
            Full-text JSON
          </label>
        </div>
      </div>
      <div className="space-y-1">
        <label className="text-xs uppercase text-(--color-muted)">Tipo</label>
        <Select value={typeFilter} onValueChange={onTypeFilterChange}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">Tutti</SelectItem>
            <SelectItem value="weekly">Settimanale</SelectItem>
            <SelectItem value="quarterly">Trimestrale</SelectItem>
            <SelectItem value="biannual">Semestrale</SelectItem>
            <SelectItem value="annual">Annuale</SelectItem>
            <SelectItem value="other">Altro</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
