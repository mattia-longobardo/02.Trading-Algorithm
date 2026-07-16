import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { CumulativeGainChart } from "@/components/benchmark/cumulative-gain-chart";

describe("CumulativeGainChart", () => {
  it("renders a skeleton (animate-pulse) when loading is true", () => {
    const { container } = render(
      <CumulativeGainChart points={[]} currency="EUR" loading={true} />
    );
    const skeleton = container.querySelector(".animate-pulse");
    expect(skeleton).toBeTruthy();
  });

  it("shows the empty state when not loading and points is empty", () => {
    render(<CumulativeGainChart points={[]} currency="EUR" loading={false} />);
    expect(
      screen.getByText(/Nessun dato nel periodo selezionato/)
    ).toBeInTheDocument();
  });

  it("shows 'Errore nel caricamento' when error is true", () => {
    render(<CumulativeGainChart points={[]} currency="EUR" error={true} />);
    expect(screen.getByText("Errore nel caricamento")).toBeInTheDocument();
  });

  it("shows the display currency in the subtitle", () => {
    render(<CumulativeGainChart points={[]} currency="EUR" />);
    expect(screen.getByText(/valuta EUR/)).toBeInTheDocument();
  });
});
