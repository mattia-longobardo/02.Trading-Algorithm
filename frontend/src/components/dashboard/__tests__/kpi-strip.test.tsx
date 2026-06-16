import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { KpiStrip } from "@/components/dashboard/kpi-strip";
import type { Metrics } from "@/lib/types";

const SAMPLE_METRICS: Metrics = {
  total_pnl_abs: 1234.56,
  total_pnl_pct: 12.34,
  win_rate: 0.65,
  avg_win: 320.0,
  avg_loss: -180.5,
  profit_factor: 2.1,
  max_drawdown: -450.0,
  sharpe: 1.42,
  n_trades: 42,
  n_open: 5,
  n_pending: 2,
  account_equity: 12000.0,
  realized_pnl_abs: 1234.56,
  unrealized_pnl_abs: 567.89,
  account_return_abs: 2000.0,
  account_return_pct: 8.5,
  account_equity_base: 10000.0,
  currency: "EUR",
  account_currency: "EUR",
};

describe("KpiStrip", () => {
  it("renders all KPI tile labels", () => {
    render(<KpiStrip metrics={SAMPLE_METRICS} />);
    expect(screen.getByText(/PnL realizzato/i)).toBeInTheDocument();
    expect(screen.getByText(/Win rate/i)).toBeInTheDocument();
    expect(screen.getByText(/Profit factor/i)).toBeInTheDocument();
    expect(screen.getByText(/Max drawdown/i)).toBeInTheDocument();
    expect(screen.getByText(/Sharpe/i)).toBeInTheDocument();
    expect(screen.getByText(/Equity account/i)).toBeInTheDocument();
    expect(screen.getByText(/PnL non realizzato/i)).toBeInTheDocument();
    expect(screen.getByText(/Avg win/i)).toBeInTheDocument();
    expect(screen.getByText(/Avg loss/i)).toBeInTheDocument();
    expect(screen.getByText(/# Trade/i)).toBeInTheDocument();
    expect(screen.getByText(/# Aperti/i)).toBeInTheDocument();
    expect(screen.getByText(/# Pending/i)).toBeInTheDocument();
  });

  it("formats win rate as a percentage using format helpers", () => {
    render(<KpiStrip metrics={SAMPLE_METRICS} />);
    // win_rate=0.65 → formatPercent(0.65*100) = "65.00%"
    expect(screen.getByText("65.00%")).toBeInTheDocument();
  });

  it("formats profit factor with 2 decimal places", () => {
    render(<KpiStrip metrics={SAMPLE_METRICS} />);
    // profit_factor=2.1 → formatNumber(2.1, {maximumFractionDigits:2}) in it-IT locale = "2,1"
    expect(screen.getByText("2,1")).toBeInTheDocument();
  });

  it("renders subtitles for total PnL percentage", () => {
    render(<KpiStrip metrics={SAMPLE_METRICS} />);
    // total_pnl_pct=12.34 → formatSignedPercent(12.34) = "+12.34%" (signed, prominent)
    expect(screen.getByText("+12.34%")).toBeInTheDocument();
  });

  it("shows real account performance % on the equity tile", () => {
    render(<KpiStrip metrics={SAMPLE_METRICS} />);
    // account_return_pct=8.5 → formatSignedPercent(8.5) = "+8.50%"
    expect(screen.getByText("+8.50%")).toBeInTheDocument();
  });

  it("shows dashes for all values when metrics is undefined", () => {
    render(<KpiStrip metrics={undefined} />);
    // When no metrics: formatCurrency(undefined) = "—", formatPercent(undefined) = "—"
    const dashes = screen.getAllByText("—");
    // At minimum we expect several — values across the KPI grid
    expect(dashes.length).toBeGreaterThan(5);
  });
});
