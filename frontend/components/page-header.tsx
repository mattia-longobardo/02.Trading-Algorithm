import { cn } from "@/lib/utils";

/**
 * Intestazione di pagina del registro: eyebrow mono con hairline rule,
 * titolo in Newsreader (l'unico posto dove compare la serif, col claim).
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  className,
}: {
  eyebrow: string;
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="space-y-1.5">
        <p className="eyebrow">{eyebrow}</p>
        <h1 className="font-display text-[28px] leading-tight font-medium tracking-[-0.01em]">
          {title}
        </h1>
        {description ? (
          <p className="text-muted-foreground max-w-2xl text-sm">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="shrink-0">{actions}</div> : null}
    </header>
  );
}

/** Eyebrow standalone per sezioni interne alle pagine. */
export function SectionLabel({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <p className={cn("eyebrow", className)}>{children}</p>;
}
