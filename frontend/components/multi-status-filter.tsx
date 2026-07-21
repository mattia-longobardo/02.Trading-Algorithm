"use client";

import { ListFilterIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export interface StatusOption { value: string; label: string }

export function MultiStatusFilter({ options, value, onChange }: {
  options: StatusOption[];
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const toggle = (status: string, checked: boolean) => {
    onChange(checked ? [...value, status] : value.filter((item) => item !== status));
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="outline" className="justify-start">
          <ListFilterIcon data-icon="inline-start" aria-hidden="true" />
          {value.length === 0 ? "Tutti gli stati" : `${value.length} stati selezionati`}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 gap-1 p-2">
        {options.map((option) => (
          <Label key={option.value} htmlFor={`status-${option.value}`} className="hover:bg-accent flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 font-normal">
            <Checkbox id={`status-${option.value}`} checked={value.includes(option.value)} onCheckedChange={(checked) => toggle(option.value, checked === true)} />
            {option.label}
          </Label>
        ))}
        <Button variant="ghost" size="sm" className="mt-1 justify-start" disabled={value.length === 0} onClick={() => onChange([])}>Mostra tutti</Button>
      </PopoverContent>
    </Popover>
  );
}
