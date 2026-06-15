import type { LivePosition, Trade } from "@/lib/types";

function normalizeSymbol(symbol: string | null | undefined): string {
  return String(symbol || "").trim().toUpperCase();
}

function key(value: string | number | null | undefined, prefix: string): string | null {
  if (value === null || value === undefined || value === "") return null;
  return `${prefix}:${value}`;
}

function symbolKey(symbol: string | null | undefined, category: string | null | undefined): string | null {
  const normalized = normalizeSymbol(symbol);
  if (!normalized) return null;
  return `symbol:${String(category || "").trim().toUpperCase()}:${normalized}`;
}

function positionKeys(pos: LivePosition): string[] {
  return [
    key(pos.id, "id"),
    key(pos.position_id, "position"),
    key(pos.instrument_id, "instrument"),
    symbolKey(pos.symbol, pos.category),
  ].filter((value): value is string => Boolean(value));
}

function tradeKeys(trade: Trade): string[] {
  return [
    key(trade.id, "id"),
    key(trade.position_id, "position"),
    key(trade.instrument_id, "instrument"),
    symbolKey(trade.symbol, trade.category),
  ].filter((value): value is string => Boolean(value));
}

function livePositionIndex(positions: LivePosition[]): Map<string, LivePosition> {
  const index = new Map<string, LivePosition>();
  for (const pos of positions) {
    for (const lookupKey of positionKeys(pos)) {
      if (!index.has(lookupKey)) index.set(lookupKey, pos);
    }
  }
  return index;
}

function findLivePosition(trade: Trade, index: Map<string, LivePosition>): LivePosition | null {
  for (const lookupKey of tradeKeys(trade)) {
    const pos = index.get(lookupKey);
    if (pos) return pos;
  }
  return null;
}

export function mergeLiveTradeValues(trades: Trade[], positions: LivePosition[]): Trade[] {
  if (trades.length === 0 || positions.length === 0) return trades;

  const index = livePositionIndex(positions);
  return trades.map((trade) => {
    if (trade.status !== "OPEN") return trade;
    const live = findLivePosition(trade, index);
    if (!live) return trade;

    return {
      ...trade,
      entry_price: live.entry_price,
      quantity: live.units,
      current_price: live.current_price,
      unrealized_pnl: live.unrealized_pnl ?? trade.unrealized_pnl,
      unrealized_pnl_pct: live.unrealized_pnl_pct,
      take_profit: live.take_profit,
      stop_loss: live.stop_loss,
      position_id: live.position_id ?? trade.position_id,
      instrument_id: live.instrument_id ?? trade.instrument_id,
    };
  });
}
