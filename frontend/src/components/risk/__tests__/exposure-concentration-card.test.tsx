import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExposureConcentrationCard } from "@/components/risk/exposure-concentration-card";

describe("ExposureConcentrationCard", () => {
  it("renders exposure %, n_eff and avg correlation", () => {
    render(
      <ExposureConcentrationCard
        exposure={0.6} equity={10000} cash={4000} nEff={2.5} avgCorrelation={0.42} hhi={0.4}
        currency="USD"
      />,
    );
    expect(screen.getByText("60.0%")).toBeInTheDocument();
    expect(screen.getByText("2.5")).toBeInTheDocument(); // n_eff
    expect(screen.getByText("0.42")).toBeInTheDocument(); // avg corr
  });

  it("handles null cash gracefully", () => {
    render(
      <ExposureConcentrationCard
        exposure={0} equity={0} cash={null} nEff={0} avgCorrelation={0} hhi={0} currency="USD"
      />,
    );
    expect(screen.getByText("0.0%")).toBeInTheDocument();
  });
});
