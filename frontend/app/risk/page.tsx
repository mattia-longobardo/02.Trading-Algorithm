"use client";

import { LightbulbIcon } from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { RiskGauge, BAND_META } from "@/components/charts/risk-gauge";
import { RiskHistoryChart } from "@/components/charts/risk-history-chart";
import { PageHeader } from "@/components/page-header";
import { Stamp } from "@/components/stamp";
import { CardSkeleton, ErrorState } from "@/components/query-states";
import { useRiskHistory, useRiskScore } from "@/lib/queries";
import { fmtNum } from "@/lib/format";
import type { RiskComponent } from "@/lib/types";

function componentColor(v: number): string {
  if (v <= 3) return BAND_META.low.color;
  if (v <= 6) return BAND_META.medium.color;
  if (v <= 8) return BAND_META.high.color;
  return BAND_META.extreme.color;
}

function ComponentBar({ component }: { component: RiskComponent }) {
  const color = componentColor(component.value_0_10);
  return (
    <div className="border-border/60 space-y-1.5 border-b py-3 last:border-0">
      <div className="flex items-center justify-between gap-2 text-sm">
        <span className="font-medium">{component.label}</span>
        <span className="text-muted-foreground font-mono text-[11px] tracking-[0.04em] uppercase">
          peso {fmtNum(component.weight_pct, 0)}% ·{" "}
          <span className="text-foreground font-medium tabular-nums">
            {fmtNum(component.value_0_10, 1)}/10
          </span>
        </span>
      </div>
      <div className="bg-muted relative h-1.5 overflow-hidden rounded-[2px]">
        <div
          className="h-full rounded-[2px] transition-all duration-150"
          style={{
            width: `${(component.value_0_10 / 10) * 100}%`,
            background: color,
          }}
        />
        {/* soglie di fascia a 3, 6 e 8 */}
        {[3, 6, 8].map((t) => (
          <span
            key={t}
            className="bg-background/80 absolute top-0 h-full w-px"
            style={{ left: `${(t / 10) * 100}%` }}
          />
        ))}
      </div>
      <p className="text-muted-foreground text-xs">{component.explanation}</p>
      {component.suggestion && (
        <p className="text-caution flex items-start gap-1.5 text-xs">
          <LightbulbIcon className="mt-0.5 size-3.5 shrink-0" />
          {component.suggestion}
        </p>
      )}
    </div>
  );
}

export default function RiskPage() {
  const { data: score, isLoading, error } = useRiskScore();
  const { data: history } = useRiskHistory();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Risk score"
        title="Rischio"
        description="Punteggio composito deterministico 1–10, calcolato solo sulle posizioni bot. Nessun LLM: riproducibile e testabile."
      />

      {isLoading ? (
        <div className="grid gap-4 xl:grid-cols-3">
          <CardSkeleton className="h-72 w-full" />
          <CardSkeleton className="h-72 w-full xl:col-span-2" />
        </div>
      ) : error || !score ? (
        <ErrorState error={error} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-3">
          <Card>
            <CardHeader>
              <CardTitle>Risk score</CardTitle>
              <CardDescription>
                1–3 basso · 4–6 medio · 7–8 alto · 9–10 estremo
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <RiskGauge score={score.score} band={score.band} />
              <div className="flex flex-wrap justify-center gap-1.5">
                {(Object.keys(BAND_META) as (keyof typeof BAND_META)[]).map(
                  (band) => (
                    <Stamp
                      key={band}
                      tone="neutral"
                      className={
                        band === score.band
                          ? "border-current font-semibold"
                          : undefined
                      }
                      style={
                        band === score.band
                          ? { color: BAND_META[band].color }
                          : undefined
                      }
                    >
                      {BAND_META[band].label} {BAND_META[band].range}
                    </Stamp>
                  ),
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="xl:col-span-2">
            <CardHeader>
              <CardTitle>Breakdown per componente</CardTitle>
              <CardDescription>
                Ogni componente è normalizzata 0–10 con soglie esplicite di
                configurazione; lo score finale è la media pesata
              </CardDescription>
            </CardHeader>
            <CardContent>
              {score.components.length === 0 ? (
                <p className="text-muted-foreground py-8 text-center text-sm">
                  Nessuna componente disponibile — servono posizioni bot aperte
                </p>
              ) : (
                score.components.map((c) => (
                  <ComponentBar key={c.key} component={c} />
                ))
              )}
            </CardContent>
          </Card>
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Storico dello score</CardTitle>
          <CardDescription>Evoluzione del risk score nel tempo</CardDescription>
        </CardHeader>
        <CardContent>
          {history && history.points.length > 1 ? (
            <RiskHistoryChart points={history.points} />
          ) : (
            <p className="text-muted-foreground py-10 text-center text-sm">
              Storico non ancora disponibile — si accumula run dopo run
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
