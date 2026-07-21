import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Timbro di verdetto — la firma visiva del registro.
 * Chip rettangolare, bordo 1px, radius 3px, mono maiuscolo:
 * ogni stato dell'applicazione è un timbro (APPROVATO, RESPINTO, DEMO, REALE…).
 */
const stampVariants = cva(
  "inline-flex h-[18px] w-fit shrink-0 items-center gap-1 rounded-[3px] border px-1.5 font-mono text-[10px] font-medium tracking-[0.08em] whitespace-nowrap uppercase select-none [&>svg]:size-2.5",
  {
    variants: {
      tone: {
        /* verdetti */
        approved: "border-positive/50 text-positive",
        rejected: "border-negative/50 text-negative",
        neutral: "border-border text-muted-foreground",
        caution: "border-caution/50 text-caution",
        accent: "border-primary/50 text-primary",
        /* stati pieni: gli unici timbri a inchiostro pieno */
        "solid-danger": "border-negative bg-negative text-white dark:text-[#141517]",
        "solid-caution": "border-caution bg-caution text-white dark:text-[#141517]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Stamp({
  className,
  tone,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof stampVariants>) {
  return (
    <span
      data-slot="stamp"
      className={cn(stampVariants({ tone }), className)}
      {...props}
    />
  );
}

/** Indicatore a pallino con etichetta mono: stato dei sistemi di sicurezza. */
export function DotIndicator({
  label,
  active,
  activeTone = "danger",
  className,
}: {
  label: string;
  /** true = condizione anomala (kill switch attivo, breaker scattato) */
  active: boolean;
  activeTone?: "danger" | "caution";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 font-mono text-[10px] tracking-[0.08em] uppercase",
        active
          ? activeTone === "danger"
            ? "text-negative"
            : "text-caution"
          : "text-muted-foreground",
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          active
            ? activeTone === "danger"
              ? "bg-negative"
              : "bg-caution"
            : "bg-positive",
        )}
      />
      {label}
    </span>
  );
}
