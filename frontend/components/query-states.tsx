"use client";

import { AlertTriangleIcon } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";

/** Stato di errore inline (i toast sono riservati alle mutation). */
export function ErrorState({
  error,
  title = "Errore di caricamento",
}: {
  error: unknown;
  title?: string;
}) {
  return (
    <div className="border-destructive/30 bg-destructive/5 flex items-start gap-3 rounded-lg border p-4 text-sm">
      <AlertTriangleIcon className="text-destructive mt-0.5 size-4 shrink-0" />
      <div>
        <p className="font-medium">{title}</p>
        <p className="text-muted-foreground mt-0.5">{errorMessage(error)}</p>
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

export function CardSkeleton({ className }: { className?: string }) {
  return <Skeleton className={className ?? "h-32 w-full"} />;
}
