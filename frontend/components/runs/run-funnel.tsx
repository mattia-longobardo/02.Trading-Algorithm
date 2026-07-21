"use client";

import { ChevronRightIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * L'imbuto della run: quanti elementi sopravvivono a ogni anello della catena.
 * Gli anelli a zero sono spenti, così si vede a colpo d'occhio dove si è rotta.
 */

export interface FunnelStep {
  label: string;
  value: number;
  hint: string;
}

export function RunFunnel({
  steps,
  className,
}: {
  steps: FunnelStep[];
  className?: string;
}) {
  // Il primo anello a zero è il punto di rottura: da lì in poi è tutto spento
  // per costruzione, ma va evidenziato solo lui.
  const breakIndex = steps.findIndex((step) => step.value === 0);

  return (
    <ol className={cn("flex flex-wrap items-stretch gap-1.5", className)}>
      {steps.map((step, i) => {
        const empty = step.value === 0;
        const isBreak = i === breakIndex;
        return (
          <li key={step.label} className="flex items-stretch gap-1.5">
            <div
              title={step.hint}
              className={cn(
                "flex min-w-[104px] flex-col justify-between rounded-md border px-3 py-2",
                empty ? "border-dashed" : "border-border bg-muted/30",
                isBreak && "border-caution/60 bg-caution/5",
              )}
            >
              <span
                className={cn(
                  "font-mono text-[10px] tracking-[0.08em] uppercase",
                  isBreak ? "text-caution" : "text-muted-foreground",
                )}
              >
                {step.label}
              </span>
              <span
                className={cn(
                  "font-display text-2xl leading-none font-medium tabular-nums",
                  empty && "text-muted-foreground/50",
                  isBreak && "text-caution",
                )}
              >
                {step.value}
              </span>
            </div>
            {i < steps.length - 1 ? (
              <ChevronRightIcon
                aria-hidden="true"
                className="text-muted-foreground/40 size-4 self-center"
              />
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
