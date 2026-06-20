"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBanner } from "@/components/ui/status-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { LiveBadge } from "@/components/live/live-badge";
import { EditTradeDialog } from "@/components/trades/edit-trade-dialog";
import { RiskScoreGauge } from "@/components/risk/risk-score-gauge";
import { RiskComponentsBreakdown } from "@/components/risk/risk-components-breakdown";
import { ExposureConcentrationCard } from "@/components/risk/exposure-concentration-card";
import { PositionRiskContribution } from "@/components/risk/position-risk-contribution";
import { PositionsRiskTable } from "@/components/risk/positions-risk-table";
import { RiskLimitsPanel } from "@/components/risk/risk-limits-panel";
import { WhatIfSimulator } from "@/components/risk/what-if-simulator";
import { useLiveStream } from "@/lib/use-live-stream";
import { useMinuteRefresh } from "@/lib/use-minute-refresh";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { buildRiskRows, RISK_HARD_THRESHOLD } from "@/lib/risk";
import type { RiskSnapshot, Trade } from "@/lib/types";

export default function RiskPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const { snapshot, status } = useLiveStream();
  useMinuteRefresh(["risk"]);
  const [editing, setEditing] = useState<Trade | null>(null);

  const risk = useQuery({
    queryKey: ["risk"],
    queryFn: () => api.get<RiskSnapshot>("/api/risk"),
  });
  const openTrades = useQuery({
    queryKey: ["trades", "OPEN"],
    queryFn: () => api.get<{ items: Trade[] }>("/api/trades?status=OPEN&page_size=200"),
  });

  const r = risk.data;
  const currency = snapshot?.currency ?? "USD";
  const rows = buildRiskRows(snapshot?.positions ?? [], openTrades.data?.items ?? []);
  const openSymbols = rows.map((row) => row.live.symbol);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold sm:text-3xl">Rischio</h1>
          <p className="text-sm text-(--color-muted)">
            Rischio di portfolio in tempo reale: score composito, esposizione, concentrazione e protezioni.
          </p>
        </div>
        <LiveBadge status={status} />
      </header>

      {risk.isError && (
        <StatusBanner kind="error">
          Impossibile caricare i dati di rischio. Riprova o controlla la connessione al backend.
        </StatusBanner>
      )}
      {r?.over_hard ? (
        <StatusBanner kind="error">Rischio di portfolio CRITICO: lo score ha superato la soglia hard.</StatusBanner>
      ) : r?.over_alert ? (
        <StatusBanner kind="warning">Attenzione: lo score di rischio ha superato la soglia di alert.</StatusBanner>
      ) : null}
      {r?.low_confidence && (
        <StatusBanner kind="info">
          Bassa confidenza: storico prezzi insufficiente per alcune posizioni; i valori usano volatilità di default.
        </StatusBanner>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Score di rischio</CardTitle></CardHeader>
          <CardContent>
            {risk.isLoading || !r ? (
              <Skeleton className="h-32 w-full rounded-lg" />
            ) : (
              <RiskScoreGauge score={r.score} budgetVol={r.budget_vol} hardThreshold={RISK_HARD_THRESHOLD} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Componenti</CardTitle></CardHeader>
          <CardContent>
            {risk.isLoading || !r ? (
              <Skeleton className="h-32 w-full rounded-lg" />
            ) : (
              <RiskComponentsBreakdown components={r.components} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Esposizione & concentrazione</CardTitle></CardHeader>
          <CardContent>
            {risk.isLoading || !r ? (
              <Skeleton className="h-32 w-full rounded-lg" />
            ) : (
              <ExposureConcentrationCard
                exposure={r.exposure}
                equity={snapshot?.equity ?? r.equity}
                cash={snapshot?.cash ?? null}
                nEff={r.n_eff}
                avgCorrelation={r.avg_correlation}
                hhi={r.hhi}
                currency={currency}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Contributo di rischio per posizione</CardTitle></CardHeader>
          <CardContent>
            {risk.isLoading || !r ? (
              <Skeleton className="h-40 w-full rounded-lg" />
            ) : (
              <PositionRiskContribution contributions={r.per_position_risk_contribution} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Posizioni & protezioni</CardTitle></CardHeader>
          <CardContent>
            <PositionsRiskTable rows={rows} onEdit={setEditing} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Limiti di rischio</CardTitle></CardHeader>
        <CardContent>
          <RiskLimitsPanel isAdmin={user?.role === "admin"} budgetVol={r?.budget_vol ?? 0} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Simulatore What-If</CardTitle></CardHeader>
        <CardContent>
          <WhatIfSimulator openSymbols={openSymbols} />
        </CardContent>
      </Card>

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="bottom-0 left-0 right-0 top-auto w-full max-w-none translate-x-0 translate-y-0 rounded-t-2xl sm:bottom-auto sm:left-1/2 sm:right-auto sm:top-1/2 sm:w-full sm:max-w-lg sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl">
          {editing && (
            <EditTradeDialog
              trade={editing}
              onClose={() => setEditing(null)}
              onSaved={() => {
                setEditing(null);
                qc.invalidateQueries({ queryKey: ["trades", "OPEN"] });
                qc.invalidateQueries({ queryKey: ["risk"] });
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
