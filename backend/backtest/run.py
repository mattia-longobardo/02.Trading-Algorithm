"""CLI: A/B replay of historical trades through OLD vs NEW exit/sizing/regime.

GPT entries are NOT replayed; daily granularity; intraday ambiguity resolves to
the adverse exit. Default trades DB is the backup snapshot.
"""

from __future__ import annotations

import argparse
import sqlite3

from backtest.prices import load_daily_bars
from backtest.simulator import simulate_trade


def aggregate(results: list[dict]) -> dict:
    taken = [r for r in results if r.get("taken")]
    closed = [r for r in taken if r.get("realized_r") is not None]
    rs = [float(r["realized_r"]) for r in closed]
    wins = [v for v in rs if v > 0]
    reached = [r for r in closed if r.get("reached_tp")]
    n_closed = len(closed)
    return {
        "n_taken": len(taken),
        "n_closed": n_closed,
        "win_rate": round(len(wins) / n_closed, 4) if n_closed else 0.0,
        "avg_realized_r": round(sum(rs) / n_closed, 4) if n_closed else 0.0,
        "pct_reached_tp": round(len(reached) / n_closed, 4) if n_closed else 0.0,
        "total_r": round(sum(rs), 4),
    }


def _load_trades(trades_db_path: str) -> list[dict]:
    conn = sqlite3.connect(trades_db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE status = 'CLOSED' AND open_timestamp IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def run_replay(trades_db_path, market_db_path, mode, exit_cfg, regime_cfg) -> dict:
    results = []
    for t in _load_trades(trades_db_path):
        # skip trades missing required levels (simulator requires numeric stop_loss / entry_price)
        if t.get("stop_loss") is None or t.get("entry_price") is None:
            continue
        bars = load_daily_bars(market_db_path, str(t["symbol"]))
        open_ts = str(t.get("open_timestamp") or "")[:10]
        entry_bars = [b for b in bars if b["timestamp"][:10] < open_ts]
        forward_bars = [b for b in bars if b["timestamp"][:10] >= open_ts]
        if not forward_bars:
            continue  # no price data to replay this symbol/date
        results.append(simulate_trade(t, entry_bars, forward_bars, mode=mode, exit_cfg=exit_cfg, regime_cfg=regime_cfg))
    return aggregate(results)


def _cfg_from_config():
    from core.utils import load_config
    c = load_config()
    exit_cfg = {
        "min_reward_risk": c.exit_min_reward_risk, "arm_r": c.exit_trailing_arm_r,
        "trail_r": c.exit_trailing_trail_r, "min_profit_buffer_pct": c.trailing_tp_min_profit_buffer_pct,
    }
    regime_cfg = {"enabled": c.regime_gate_enabled, "sma_period": c.regime_sma_period}
    return exit_cfg, regime_cfg


def main() -> None:
    p = argparse.ArgumentParser(description="Backtest exit/sizing replay (GPT entries not replayed).")
    p.add_argument("--trades", required=True)
    p.add_argument("--market", default="data/market_data.sqlite")
    p.add_argument("--mode", choices=["old", "new", "ab"], default="ab")
    args = p.parse_args()
    exit_cfg, regime_cfg = _cfg_from_config()
    print("NOTE: daily bars; intraday ambiguity -> adverse exit assumed; GPT entries taken as-is.")
    modes = ["old", "new"] if args.mode == "ab" else [args.mode]
    reports = {m: run_replay(args.trades, args.market, m, exit_cfg, regime_cfg) for m in modes}
    for m, rep in reports.items():
        print(f"\n[{m.upper()}] {rep}")
    if args.mode == "ab":
        d_r = reports["new"]["avg_realized_r"] - reports["old"]["avg_realized_r"]
        print(f"\nDelta avg_realized_r (new-old): {round(d_r, 4)}")
        print(f"Trades regime gate skipped (taken old - taken new): {reports['old']['n_taken'] - reports['new']['n_taken']}")


if __name__ == "__main__":
    main()
