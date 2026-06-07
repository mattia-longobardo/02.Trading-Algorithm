import type { LivePosition, Trade } from "@/lib/types";

/** Frontend mirror delle soglie backend (solo per fasce-colore; gli alert reali
 * arrivano dai flag over_alert/over_hard di /api/risk). */
export const RISK_ALERT_THRESHOLD = 70;
export const RISK_HARD_THRESHOLD = 85;

export type RiskBand = "calm" | "warning" | "critical";

export function riskBand(score: number): RiskBand {
  if (score >= RISK_HARD_THRESHOLD) return "critical";
  if (score >= RISK_ALERT_THRESHOLD) return "warning";
  return "calm";
}

export interface StopInfo {
  effectiveStop: number | null;
  distancePct: number | null;
  hasHardStop: boolean;
  hasTrailingStop: boolean;
  unprotected: boolean;
}

/** Calcola lo stop effettivo (il più vicino al prezzo) e la distanza %.
 * Il bot è long-only: per un long lo stop più vicino sotto il prezzo è il MAX
 * tra hard stop e trailing-stop price. */
export function stopInfo(args: {
  currentPrice: number | null;
  stopLoss: number | null;
  trailingStopDistance: number | null;
  trailingStopPrice: number | null;
}): StopInfo {
  const hasHardStop = args.stopLoss != null;
  const hasTrailingStop = args.trailingStopDistance != null;
  const candidates = [args.stopLoss, args.trailingStopPrice].filter(
    (v): v is number => v != null && !Number.isNaN(v) && v > 0,
  );
  const effectiveStop = candidates.length ? Math.max(...candidates) : null;
  const cp = args.currentPrice;
  const distancePct =
    cp != null && cp > 0 && effectiveStop != null ? ((cp - effectiveStop) / cp) * 100 : null;
  return {
    effectiveStop,
    distancePct,
    hasHardStop,
    hasTrailingStop,
    unprotected: !hasHardStop && !hasTrailingStop,
  };
}

export interface RiskPositionRow {
  trade: Trade;
  live: LivePosition;
  value: number;
  valuePct: number;
  stop: StopInfo;
}

/** Incrocia lo snapshot live (prezzo/valore freschi) con i trade aperti
 * (campi trailing) tramite l'id del trade. Salta le live senza trade. */
export function buildRiskRows(positions: LivePosition[], trades: Trade[]): RiskPositionRow[] {
  const byId = new Map(trades.map((t) => [t.id, t]));
  const rows: Array<Omit<RiskPositionRow, "valuePct"> & { value: number }> = [];
  for (const live of positions) {
    const trade = byId.get(live.id);
    if (!trade) continue;
    const price = live.current_price ?? trade.current_price ?? 0;
    const value = (live.units ?? 0) * price;
    rows.push({
      trade,
      live,
      value,
      stop: stopInfo({
        currentPrice: live.current_price,
        stopLoss: live.stop_loss ?? trade.stop_loss,
        trailingStopDistance: trade.trailing_stop_distance,
        trailingStopPrice: trade.trailing_stop_price,
      }),
    });
  }
  const total = rows.reduce((s, r) => s + r.value, 0);
  return rows.map((r) => ({ ...r, valuePct: total > 0 ? (r.value / total) * 100 : 0 }));
}
