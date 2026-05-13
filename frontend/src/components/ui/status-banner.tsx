"use client";

import { AlertCircle, CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Kind = "error" | "success" | "warning" | "info";

const kindStyles: Record<Kind, string> = {
  error: "border-rose-500/50 bg-rose-500/10 text-rose-200",
  success: "border-emerald-500/50 bg-emerald-500/10 text-emerald-200",
  warning: "border-amber-500/50 bg-amber-500/10 text-amber-200",
  info: "border-sky-500/50 bg-sky-500/10 text-sky-200",
};

const kindIcons: Record<Kind, React.ComponentType<{ className?: string }>> = {
  error: AlertCircle,
  success: CheckCircle2,
  warning: TriangleAlert,
  info: Info,
};

export interface StatusBannerProps extends HTMLAttributes<HTMLDivElement> {
  kind: Kind;
  /** When set, hides the leading icon (e.g. for one-line layouts). */
  noIcon?: boolean;
}

export function StatusBanner({
  kind,
  noIcon,
  className,
  children,
  ...props
}: StatusBannerProps) {
  const Icon = kindIcons[kind];
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      aria-live={kind === "error" ? "assertive" : "polite"}
      className={cn(
        "flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
        kindStyles[kind],
        className
      )}
      {...props}
    >
      {!noIcon && <Icon className="mt-0.5 size-4 shrink-0" />}
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
