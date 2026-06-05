"use client";

import { cn } from "@/lib/cn";
import type { LiveStatus } from "@/lib/types";

const CONFIG: Record<
  LiveStatus,
  { label: string; dotClass: string; textClass: string }
> = {
  live: {
    label: "● Live",
    dotClass: "text-(--color-accent)",
    textClass: "text-(--color-accent)",
  },
  stale: {
    label: "● In ritardo",
    dotClass: "text-(--color-muted)",
    textClass: "text-(--color-muted)",
  },
  reconnecting: {
    label: "● Riconnessione…",
    dotClass: "text-(--color-warning)",
    textClass: "text-(--color-warning)",
  },
  connecting: {
    label: "● Connessione…",
    dotClass: "text-(--color-muted)",
    textClass: "text-(--color-muted)",
  },
};

interface LiveBadgeProps {
  status: LiveStatus;
  className?: string;
}

export function LiveBadge({ status, className }: LiveBadgeProps) {
  const { label, textClass } = CONFIG[status];

  return (
    <span
      role="status"
      aria-live="polite"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-(--color-line) bg-(--color-panel) px-2.5 py-0.5 text-xs font-medium",
        textClass,
        className,
      )}
    >
      {label}
    </span>
  );
}
