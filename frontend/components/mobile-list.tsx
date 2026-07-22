import { cn } from "@/lib/utils";

/**
 * Vista mobile dei registri tabellari: sotto il breakpoint `md` le tabelle
 * larghe diventano schede impilate (stessa estetica dei Panel delle run:
 * bordo hairline, etichette mono maiuscole, valori tabulari).
 *
 * Pattern d'uso — entrambe le viste nel DOM, la CSS decide quale mostrare:
 *   <div className="max-md:hidden"><Table>…</Table></div>
 *   <MobileList>…</MobileList>   ← ha già `md:hidden`
 */
export function MobileList({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <ul className={cn("flex flex-col gap-2 md:hidden", className)}>
      {children}
    </ul>
  );
}

export function MobileItem({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <li className={cn("rounded-md border p-3", className)}>{children}</li>
  );
}

/** Prima riga della scheda: identità a sinistra, timbri/azioni a destra. */
export function MobileItemHeader({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5",
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Griglia di coppie etichetta/valore sotto l'intestazione. */
export function MobileFields({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <dl className={cn("mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2", className)}>
      {children}
    </dl>
  );
}

export function MobileField({
  label,
  children,
  className,
  wide,
}: {
  label: string;
  children: React.ReactNode;
  className?: string;
  /** Occupa l'intera riga (dettagli, note, date lunghe). */
  wide?: boolean;
}) {
  return (
    <div className={cn(wide && "col-span-2", className)}>
      <dt className="text-muted-foreground font-mono text-[10px] tracking-[0.08em] uppercase">
        {label}
      </dt>
      <dd className="mt-0.5 text-[13px]">{children}</dd>
    </div>
  );
}
