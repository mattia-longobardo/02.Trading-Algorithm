import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({ usePathname: () => "/positions" }));

import { BottomNav } from "@/components/layout/bottom-nav";
import { visibleNavFor } from "@/components/layout/nav-items";

function renderNav() {
  return render(<BottomNav items={visibleNavFor("admin")} />);
}

describe("BottomNav", () => {
  it("renders the three primary tabs + Altro", () => {
    renderNav();
    expect(screen.getByRole("link", { name: /Dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Posizioni/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Trade/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Altro/i })).toBeInTheDocument();
  });

  it("marks the active route", () => {
    renderNav();
    expect(screen.getByRole("link", { name: /Posizioni/i })).toHaveAttribute("aria-current", "page");
  });

  it("opens the Altro sheet listing secondary routes", async () => {
    const user = userEvent.setup();
    renderNav();
    await user.click(screen.getByRole("button", { name: /Altro/i }));
    expect(await screen.findByRole("link", { name: /Universe/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Report/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Amministrazione/i })).toBeInTheDocument();
  });
});
