import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PnlBySymbolChart } from "@/components/dashboard/pnl-by-symbol-chart";
import { CategoryAllocationChart } from "@/components/dashboard/category-allocation-chart";
import { ReturnsDistributionChart } from "@/components/dashboard/returns-distribution-chart";

// ---------------------------------------------------------------------------
// PnlBySymbolChart — loading / empty / error states
// ---------------------------------------------------------------------------
describe("PnlBySymbolChart", () => {
  it("renders a skeleton (animate-pulse) when loading is true", () => {
    const { container } = render(
      <PnlBySymbolChart items={[]} currency="EUR" loading={true} />
    );
    // The Skeleton component renders a div with animate-pulse
    const skeleton = container.querySelector(".animate-pulse");
    expect(skeleton).toBeTruthy();
  });

  it("shows 'Nessun dato' when not loading and items is empty", () => {
    render(<PnlBySymbolChart items={[]} currency="EUR" loading={false} />);
    expect(screen.getByText("Nessun dato")).toBeInTheDocument();
  });

  it("shows 'Errore nel caricamento' when error is true", () => {
    render(<PnlBySymbolChart items={[]} currency="EUR" error={true} />);
    expect(screen.getByText("Errore nel caricamento")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// CategoryAllocationChart — loading / empty / error states
// ---------------------------------------------------------------------------
describe("CategoryAllocationChart", () => {
  it("renders a skeleton (animate-pulse) when loading is true", () => {
    const { container } = render(
      <CategoryAllocationChart byCategory={[]} currency="EUR" loading={true} />
    );
    const skeleton = container.querySelector(".animate-pulse");
    expect(skeleton).toBeTruthy();
  });

  it("shows 'Nessun dato' when not loading and byCategory is empty", () => {
    render(
      <CategoryAllocationChart byCategory={[]} currency="EUR" loading={false} />
    );
    expect(screen.getByText("Nessun dato")).toBeInTheDocument();
  });

  it("shows 'Errore nel caricamento' when error is true", () => {
    render(
      <CategoryAllocationChart byCategory={[]} currency="EUR" error={true} />
    );
    expect(screen.getByText("Errore nel caricamento")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// ReturnsDistributionChart — loading / empty / error states
// ---------------------------------------------------------------------------
describe("ReturnsDistributionChart", () => {
  it("renders a skeleton (animate-pulse) when loading is true", () => {
    const { container } = render(
      <ReturnsDistributionChart bins={[]} loading={true} />
    );
    const skeleton = container.querySelector(".animate-pulse");
    expect(skeleton).toBeTruthy();
  });

  it("shows 'Nessun dato' when not loading and bins is empty", () => {
    render(<ReturnsDistributionChart bins={[]} loading={false} />);
    expect(screen.getByText("Nessun dato")).toBeInTheDocument();
  });

  it("shows 'Errore nel caricamento' when error is true", () => {
    render(<ReturnsDistributionChart bins={[]} error={true} />);
    expect(screen.getByText("Errore nel caricamento")).toBeInTheDocument();
  });
});
