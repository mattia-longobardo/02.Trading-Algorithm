import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { LiveBadge } from "@/components/live/live-badge";

describe("LiveBadge", () => {
  it('shows "● Live" for live status', () => {
    render(<LiveBadge status="live" />);
    expect(screen.getByRole("status")).toHaveTextContent("● Live");
  });

  it('shows "● In ritardo" for stale status', () => {
    render(<LiveBadge status="stale" />);
    expect(screen.getByRole("status")).toHaveTextContent("● In ritardo");
  });

  it('shows "● Riconnessione…" for reconnecting status', () => {
    render(<LiveBadge status="reconnecting" />);
    expect(screen.getByRole("status")).toHaveTextContent("● Riconnessione…");
  });

  it('shows "● Connessione…" for connecting status', () => {
    render(<LiveBadge status="connecting" />);
    expect(screen.getByRole("status")).toHaveTextContent("● Connessione…");
  });

  it("has aria-live=polite for screen-reader announcements", () => {
    render(<LiveBadge status="live" />);
    const el = screen.getByRole("status");
    expect(el).toHaveAttribute("aria-live", "polite");
  });

  it("forwards extra className", () => {
    render(<LiveBadge status="live" className="extra-class" />);
    const el = screen.getByRole("status");
    expect(el.className).toContain("extra-class");
  });
});
