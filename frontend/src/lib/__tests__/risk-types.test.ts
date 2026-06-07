import { describe, it, expect } from "vitest";
import type { RiskSnapshot, RiskProjection } from "@/lib/types";

describe("risk types", () => {
  it("RiskSnapshot/RiskProjection compile and accept a sample payload", () => {
    const snap: RiskSnapshot = {
      score: 42, portfolio_vol: 0.2, budget_vol: 0.3,
      components: { vol: 30, concentration: 50, correlation: 40, exposure: 60 },
      hhi: 0.5, n_eff: 2, avg_correlation: 0.4, exposure: 0.6,
      per_position_risk_contribution: { AAA: 60, BBB: 40 },
      equity: 10000, positions: 2,
      low_confidence: false, over_alert: false, over_hard: false,
    };
    const proj: RiskProjection = {
      current: snap, projected: snap, suggested_size: 500,
      delta: { score: 1, exposure: 0.01, portfolio_vol: 0.001, n_eff: -0.2 },
    };
    expect(proj.current.score).toBe(42);
    expect(snap.components.vol).toBe(30);
  });
});
