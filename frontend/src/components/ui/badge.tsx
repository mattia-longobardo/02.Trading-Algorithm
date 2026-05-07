import { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "default" | "open" | "pending" | "closed" | "cancelled" | "admin" | "user" | "muted";

const variantStyles: Record<Variant, string> = {
  default: "bg-slate-800 text-(--color-text)",
  open: "bg-emerald-500/20 text-emerald-300",
  pending: "bg-amber-500/20 text-amber-300",
  closed: "bg-sky-500/20 text-sky-300",
  cancelled: "bg-rose-500/20 text-rose-300",
  admin: "bg-violet-500/20 text-violet-300",
  user: "bg-slate-500/20 text-slate-200",
  muted: "bg-slate-700/40 text-(--color-muted)",
};

export function Badge({
  className,
  variant = "default",
  ...props
}: HTMLAttributes<HTMLSpanElement> & { variant?: Variant }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium",
        variantStyles[variant],
        className
      )}
      {...props}
    />
  );
}
