"use client";

import { LiveBadge } from "@/components/live/live-badge";
import { PositionsLiveTable } from "@/components/positions/positions-live-table";
import { useLiveStream } from "@/lib/use-live-stream";
import { formatCurrency } from "@/lib/format";

export default function PositionsPage() {
  const { snapshot, status } = useLiveStream();

  const currency = snapshot?.currency ?? "EUR";
  const equityStr = snapshot?.equity != null ? formatCurrency(snapshot.equity, currency) : "—";
  const cashStr = snapshot?.cash != null ? formatCurrency(snapshot.cash, currency) : "—";

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-semibold">Posizioni</h1>
          <p className="text-sm text-(--color-muted)">Posizioni aperte in tempo reale.</p>
        </div>
        <LiveBadge status={status} />
      </header>

      {/* Summary line */}
      <p className="tnum text-sm text-(--color-muted)">
        <span className="font-medium text-(--color-text)">Equity</span> {equityStr}
        <span className="mx-2 text-(--color-muted)">·</span>
        <span className="font-medium text-(--color-text)">Liquidità</span> {cashStr}
      </p>

      <PositionsLiveTable
        positions={snapshot?.positions ?? []}
        loading={status === "connecting" && snapshot === null}
      />
    </section>
  );
}
