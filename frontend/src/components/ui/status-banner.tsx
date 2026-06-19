"use client";

import { AlertCircle, CheckCircle2, Info, TriangleAlert } from "lucide-react";
import { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Kind = "error" | "success" | "warning" | "info";

const kindStyles: Record<Kind, string> = {
  error: "border-(--color-danger)/50 bg-(--color-danger)/10 text-(--color-danger)",
  success: "border-(--color-accent)/50 bg-(--color-accent)/10 text-(--color-accent)",
  warning: "border-(--color-warning)/50 bg-(--color-warning)/10 text-(--color-warning)",
  info: "border-(--color-info)/50 bg-(--color-info)/10 text-(--color-info)",
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
