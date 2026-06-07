"use client";

import { riskBand } from "@/lib/risk";
import { useChartTheme } from "@/components/charts/use-chart-theme";

const BAND_LABEL: Record<string, string> = {
  calm: "Sotto controllo",
  warning: "Attenzione",
  critical: "Critico",
};

export interface RiskScoreGaugeProps {
  score: number;
  budgetVol: number;
  hardThreshold: number;
}

export function RiskScoreGauge({ score, budgetVol, hardThreshold }: RiskScoreGaugeProps) {
  const theme = useChartTheme();
  const band = riskBand(score);
  const color =
    band === "critical" ? theme.negative : band === "warning" ? "#f59e0b" : theme.positive;

  // Semicerchio: 180° → 0°, raggio 80, centro (100,100).
  const R = 80;
  const CX = 100;
  const CY = 100;
  const arc = `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`;
  const L = Math.PI * R;
  const frac = Math.max(0, Math.min(1, score / 100));
  const remaining = Math.max(0, hardThreshold - score);

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 120" className="w-full max-w-[260px]" role="img" aria-label={`Rischio ${Math.round(score)} su 100`}>
        <path d={arc} fill="none" stroke={theme.grid} strokeWidth={14} strokeLinecap="round" />
        <path
          d={arc}
          fill="none"
          stroke={color}
          strokeWidth={14}
          strokeLinecap="round"
          strokeDasharray={`${frac * L} ${L}`}
        />
        <text x={CX} y={CY - 6} textAnchor="middle" fontSize={34} fontWeight={700} fill={theme.text}>
          {Math.round(score)}
        </text>
        <text x={CX} y={CY + 16} textAnchor="middle" fontSize={11} fill={theme.axis}>
          / 100
        </text>
      </svg>
      <div className="mt-1 text-center">
        <p className="text-sm font-semibold" style={{ color }}>
          {BAND_LABEL[band]}
        </p>
        <p className="text-xs text-(--color-muted)">
          Margine alla soglia critica: <span className="tnum">{remaining.toFixed(1)}</span> · vol budget{" "}
          <span className="tnum">{(budgetVol * 100).toFixed(0)}%</span>
        </p>
      </div>
    </div>
  );
}
