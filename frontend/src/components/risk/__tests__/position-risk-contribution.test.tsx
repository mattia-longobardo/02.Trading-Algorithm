import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PositionRiskContribution } from "@/components/risk/position-risk-contribution";

describe("PositionRiskContribution", () => {
  it("renders symbols sorted by contribution desc", () => {
    render(<PositionRiskContribution contributions={{ AAA: 30, BBB: 70 }} />);
    const items = screen.getAllByTestId("contrib-symbol").map((n) => n.textContent);
    expect(items[0]).toContain("BBB");
    expect(items[1]).toContain("AAA");
  });

  it("shows an empty hint with no contributions", () => {
    render(<PositionRiskContribution contributions={{}} />);
    expect(screen.getByText(/nessun/i)).toBeInTheDocument();
  });
});
