import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BenchmarkComparisonChart } from "@/components/benchmark/benchmark-comparison-chart";

describe("BenchmarkComparisonChart", () => {
  it("renders a skeleton (animate-pulse) when loading is true", () => {
    const { container } = render(
      <BenchmarkComparisonChart points={[]} loading={true} />
    );
    const skeleton = container.querySelector(".animate-pulse");
    expect(skeleton).toBeTruthy();
  });

  it("shows the empty state when not loading and points is empty", () => {
    render(<BenchmarkComparisonChart points={[]} loading={false} />);
    expect(
      screen.getByText(/Nessun dato nel periodo selezionato/)
    ).toBeInTheDocument();
  });

  it("shows 'Errore nel caricamento' when error is true", () => {
    render(<BenchmarkComparisonChart points={[]} error={true} />);
    expect(screen.getByText("Errore nel caricamento")).toBeInTheDocument();
  });

  it("shows the benchmark symbol in the subtitle", () => {
    render(<BenchmarkComparisonChart points={[]} benchmarkSymbol="SPX500" />);
    expect(screen.getByText(/benchmark SPX500/)).toBeInTheDocument();
  });
});
