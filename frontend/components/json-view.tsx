import { ChevronRightIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Rendering leggibile di un payload JSON arbitrario.
 *
 * Lo scroll è su un div normale, non su ScrollArea: il viewport di Radix è
 * `size-full` e dentro un contenitore ad altezza automatica il `<pre>` usciva
 * dalla card, sovrapponendosi alle schede vicine.
 */
export function JsonView({
  value,
  className,
}: {
  value: unknown;
  className?: string;
}) {
  return (
    <div className={cn("max-h-72 w-full overflow-auto rounded-md", className)}>
      <pre className="bg-muted/50 text-foreground/90 min-w-0 rounded-md p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

/**
 * Dati grezzi a scomparsa: la UI racconta la run in italiano, il JSON resta
 * disponibile a un click per chi deve verificare il payload esatto.
 */
export function RawPayload({
  value,
  label = "Dati grezzi",
  className,
}: {
  value: unknown;
  label?: string;
  className?: string;
}) {
  return (
    <details className={cn("group mt-3", className)}>
      <summary className="text-muted-foreground hover:text-foreground inline-flex cursor-pointer list-none items-center gap-1 font-mono text-[10px] tracking-[0.08em] uppercase transition-colors [&::-webkit-details-marker]:hidden">
        <ChevronRightIcon
          aria-hidden="true"
          className="size-3 transition-transform group-open:rotate-90"
        />
        {label}
      </summary>
      <JsonView value={value} className="mt-2" />
    </details>
  );
}
