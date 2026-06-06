import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/navigation", () => ({ usePathname: () => "/positions" }));

import { BottomNav } from "@/components/layout/bottom-nav";
import { visibleNavFor, primaryNav, secondaryNav, MOBILE_PRIMARY } from "@/components/layout/nav-items";

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
    const altro = screen.getByRole("button", { name: /Altro/i });
    expect(altro).toHaveAttribute("aria-expanded", "false");
    await user.click(altro);
    expect(altro).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByRole("link", { name: /Universe/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Report/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Amministrazione/i })).toBeInTheDocument();
  });
});

describe("nav split helpers", () => {
  const items = visibleNavFor("admin");
  it("primaryNav preserves MOBILE_PRIMARY order", () => {
    expect(primaryNav(items).map((i) => i.href)).toEqual([...MOBILE_PRIMARY]);
  });
  it("secondaryNav excludes the primary hrefs and is non-empty", () => {
    const sec = secondaryNav(items).map((i) => i.href);
    for (const h of MOBILE_PRIMARY) expect(sec).not.toContain(h);
    expect(sec.length).toBeGreaterThan(0);
  });
});
