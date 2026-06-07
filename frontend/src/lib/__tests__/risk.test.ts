import { describe, it, expect } from "vitest";
import {
  RISK_ALERT_THRESHOLD, RISK_HARD_THRESHOLD, riskBand, stopInfo, buildRiskRows,
} from "@/lib/risk";
import type { LivePosition, Trade } from "@/lib/types";

describe("riskBand", () => {
  it("classifies by thresholds", () => {
    expect(RISK_ALERT_THRESHOLD).toBe(70);
    expect(RISK_HARD_THRESHOLD).toBe(85);
    expect(riskBand(50)).toBe("calm");
    expect(riskBand(70)).toBe("warning");
    expect(riskBand(84.9)).toBe("warning");
    expect(riskBand(85)).toBe("critical");
  });
});

describe("stopInfo", () => {
  it("flags unprotected when no stops set", () => {
    const s = stopInfo({ currentPrice: 100, stopLoss: null, trailingStopDistance: null, trailingStopPrice: null });
    expect(s.unprotected).toBe(true);
    expect(s.effectiveStop).toBeNull();
    expect(s.distancePct).toBeNull();
  });
  it("uses the closest stop (max for a long) and computes distance %", () => {
    const s = stopInfo({ currentPrice: 100, stopLoss: 90, trailingStopDistance: 5, trailingStopPrice: 95 });
    expect(s.hasHardStop).toBe(true);
    expect(s.hasTrailingStop).toBe(true);
    expect(s.effectiveStop).toBe(95); // closest below current
    expect(s.distancePct).toBeCloseTo(5, 5);
    expect(s.unprotected).toBe(false);
  });
});

function trade(p: Partial<Trade>): Trade {
  return { id: 1, symbol: "AAA", category: "STOCK", direction: "BUY", status: "OPEN",
    entry_price: 90, target_entry_price: null, quantity: 10, allocated_capital: 900,
    take_profit: null, trailing_take_profit_distance: null, trailing_take_profit_activation_pct: null,
    stop_loss: null, trailing_stop_distance: null, high_water_mark: null,
    trailing_take_profit_price: null, trailing_stop_price: null, open_timestamp: null,
    close_timestamp: null, close_price: null, current_price: 100, pnl: null, realized_pnl: 0,
    unrealized_pnl: 100, close_reason: null, instrument_id: null, position_id: "p1",
    order_reference_id: null, reasoning: null, confidence: null, account_currency: "USD",
    created_at: "", updated_at: "", trade_score: null, ...p };
}
function live(p: Partial<LivePosition>): LivePosition {
  return { id: 1, symbol: "AAA", category: "STOCK", units: 10, entry_price: 90,
    current_price: 100, unrealized_pnl: 100, unrealized_pnl_pct: 11, take_profit: null,
    stop_loss: null, position_id: "p1", instrument_id: null, is_buy: true, ...p };
}

describe("buildRiskRows", () => {
  it("merges live × trade by id and computes value %", () => {
    const rows = buildRiskRows(
      [live({ id: 1, current_price: 100, units: 10 }), live({ id: 2, symbol: "BBB", current_price: 50, units: 10 })],
      [trade({ id: 1 }), trade({ id: 2, symbol: "BBB" })],
    );
    expect(rows).toHaveLength(2);
    const total = 100 * 10 + 50 * 10; // 1500
    expect(rows[0].valuePct).toBeCloseTo((1000 / total) * 100, 5);
    expect(rows[0].trade.id).toBe(1);
  });
  it("skips live positions without a matching trade", () => {
    const rows = buildRiskRows([live({ id: 9 })], [trade({ id: 1 })]);
    expect(rows).toHaveLength(0);
  });
});
