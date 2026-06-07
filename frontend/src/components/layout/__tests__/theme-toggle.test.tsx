import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "@/components/layout/theme-provider";
import { ThemeToggle } from "@/components/layout/theme-toggle";

function renderToggle() {
  return render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>
  );
}

describe("ThemeToggle", () => {
  it("starts in dark mode and offers to switch to light", async () => {
    renderToggle();
    expect(
      await screen.findByRole("button", { name: /tema chiaro/i })
    ).toBeInTheDocument();
  });

  it("toggles to light mode on click", async () => {
    const user = userEvent.setup();
    renderToggle();
    await user.click(await screen.findByRole("button", { name: /tema chiaro/i }));
    expect(
      await screen.findByRole("button", { name: /tema scuro/i })
    ).toBeInTheDocument();
    expect(document.documentElement.classList.contains("light")).toBe(true);
  });
});
