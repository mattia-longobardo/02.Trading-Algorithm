import { HTMLAttributes } from "react";
import { cn } from "@/lib/cn";

export interface EmptyStateProps extends HTMLAttributes<HTMLDivElement> {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
  ...props
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-(--color-line) bg-slate-950/30 px-6 py-10 text-center",
        className
      )}
      {...props}
    >
      {Icon && (
        <div className="rounded-full bg-slate-800/60 p-3 text-(--color-muted)">
          <Icon className="size-5" />
        </div>
      )}
      <p className="text-sm font-medium text-(--color-text)">{title}</p>
      {description && (
        <p className="max-w-md text-xs leading-relaxed text-(--color-muted)">
          {description}
        </p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
