import { ScrollArea } from "@/components/ui/scroll-area";

/** Rendering leggibile di un payload JSON arbitrario. */
export function JsonView({ value }: { value: unknown }) {
  return (
    <ScrollArea className="max-h-72 w-full">
      <pre className="bg-muted/50 text-foreground/90 overflow-x-auto rounded-md p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
        {JSON.stringify(value, null, 2)}
      </pre>
    </ScrollArea>
  );
}
