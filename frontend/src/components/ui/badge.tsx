import { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

type Variant = "default" | "open" | "pending" | "closed" | "cancelled" | "admin" | "user" | "muted";

const variantStyles: Record<Variant, string> = {
  default: "bg-(--color-hover) text-(--color-text)",
  open: "bg-(--color-accent)/15 text-(--color-accent)",
  pending: "bg-(--color-warning)/15 text-(--color-warning)",
  closed: "bg-(--color-info)/15 text-(--color-info)",
  cancelled: "bg-(--color-danger)/15 text-(--color-danger)",
  admin: "bg-(--color-info)/15 text-(--color-info)",
  user: "bg-(--color-hover) text-(--color-text)",
  muted: "bg-(--color-hover) text-(--color-muted)",
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
