import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskScoreGauge } from "@/components/risk/risk-score-gauge";

describe("RiskScoreGauge", () => {
  it("renders the score and the calm band label", () => {
    render(<RiskScoreGauge score={42} budgetVol={0.3} hardThreshold={85} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/sotto controllo/i)).toBeInTheDocument();
  });
  it("shows the critical band when over hard threshold", () => {
    render(<RiskScoreGauge score={90} budgetVol={0.3} hardThreshold={85} />);
    expect(screen.getByText(/critico/i)).toBeInTheDocument();
  });
  it("rounds the score for display", () => {
    render(<RiskScoreGauge score={71.6} budgetVol={0.3} hardThreshold={85} />);
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText(/attenzione/i)).toBeInTheDocument();
  });
});
