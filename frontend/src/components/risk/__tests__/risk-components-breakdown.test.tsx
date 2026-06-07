import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskComponentsBreakdown } from "@/components/risk/risk-components-breakdown";

describe("RiskComponentsBreakdown", () => {
  const components = { vol: 30, concentration: 50, correlation: 40, exposure: 60 };

  it("renders all four Italian labels and values", () => {
    render(<RiskComponentsBreakdown components={components} />);
    expect(screen.getByText("Volatilità")).toBeInTheDocument();
    expect(screen.getByText("Concentrazione")).toBeInTheDocument();
    expect(screen.getByText("Correlazione")).toBeInTheDocument();
    expect(screen.getByText("Esposizione")).toBeInTheDocument();
    expect(screen.getByText("60")).toBeInTheDocument();
  });

  it("clamps bar width to 0-100", () => {
    render(<RiskComponentsBreakdown components={{ ...components, vol: 150 }} />);
    const bar = screen.getByTestId("risk-bar-vol");
    expect(bar.style.width).toBe("100%");
  });
});
