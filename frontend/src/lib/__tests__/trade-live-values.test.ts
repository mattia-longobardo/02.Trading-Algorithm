import { describe, expect, it } from "vitest";
import { mergeLiveTradeValues } from "@/lib/trade-live-values";
import type { LivePosition, Trade } from "@/lib/types";

const TRADE: Trade = {
  id: 7,
  symbol: "AAPL",
  category: "STOCK",
  direction: "LONG",
  status: "OPEN",
  entry_price: 100,
  target_entry_price: null,
  quantity: 10,
  allocated_capital: 1000,
  take_profit: 130,
  trailing_take_profit_distance: null,
  trailing_take_profit_activation_pct: null,
  stop_loss: 90,
  trailing_stop_distance: null,
  high_water_mark: null,
  trailing_take_profit_price: null,
  trailing_stop_price: null,
  open_timestamp: "2026-01-01T00:00:00Z",
  close_timestamp: null,
  close_price: null,
  current_price: 105,
  pnl: null,
  realized_pnl: 0,
  unrealized_pnl: 50,
  close_reason: null,
  instrument_id: 101,
  position_id: "pos-old",
  order_reference_id: null,
  reasoning: null,
  confidence: null,
  account_currency: "USD",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  trade_score: null,
};

const LIVE_POSITION: LivePosition = {
  id: 7,
  symbol: "AAPL",
  category: "STOCK",
  units: 9.75,
  entry_price: 101,
  current_price: 112,
  unrealized_pnl: 107.25,
  unrealized_pnl_pct: 10.89,
  take_profit: 132,
  stop_loss: 94,
  position_id: "pos-live",
  instrument_id: 101,
  is_buy: true,
};

describe("mergeLiveTradeValues", () => {
  it("overrides open trade market values from the matching live position", () => {
    const [merged] = mergeLiveTradeValues([TRADE], [LIVE_POSITION]);

    expect(merged.current_price).toBe(112);
    expect(merged.quantity).toBe(9.75);
    expect(merged.entry_price).toBe(101);
    expect(merged.unrealized_pnl).toBe(107.25);
    expect(merged.unrealized_pnl_pct).toBe(10.89);
    expect(merged.take_profit).toBe(132);
    expect(merged.stop_loss).toBe(94);
    expect(merged.position_id).toBe("pos-live");
  });

  it("does not change closed trades", () => {
    const closed: Trade = {
      ...TRADE,
      status: "CLOSED",
      close_timestamp: "2026-01-02T00:00:00Z",
      current_price: 105,
    };

    const [merged] = mergeLiveTradeValues([closed], [LIVE_POSITION]);

    expect(merged).toBe(closed);
    expect(merged.current_price).toBe(105);
  });

  it("can match by symbol and category when broker identifiers are missing", () => {
    const withoutIds: Trade = {
      ...TRADE,
      id: 99,
      position_id: null,
      instrument_id: null,
    };

    const [merged] = mergeLiveTradeValues([withoutIds], [LIVE_POSITION]);

    expect(merged.current_price).toBe(112);
    expect(merged.unrealized_pnl_pct).toBe(10.89);
  });
});
