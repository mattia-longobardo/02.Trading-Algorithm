import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CommandPalette } from "@/components/command/command-palette";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => "/",
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "dark", setTheme: vi.fn() }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { role: "admin", display_name: "Admin", username: "admin" },
    logout: vi.fn(),
    loading: false,
    refresh: vi.fn(),
    login: vi.fn(),
  }),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Render the palette in open state */
function renderPalette(open = true) {
  const onOpenChange = vi.fn();
  const result = render(<CommandPalette open={open} onOpenChange={onOpenChange} />);
  return { ...result, onOpenChange };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("CommandPalette", () => {
  beforeEach(() => {
    mockPush.mockReset();
  });

  it("renders nothing when closed", () => {
    renderPalette(false);
    expect(screen.queryByPlaceholderText(/cerca comandi/i)).not.toBeInTheDocument();
  });

  it("renders the input when open", () => {
    renderPalette(true);
    expect(screen.getByPlaceholderText(/cerca comandi o simboli/i)).toBeInTheDocument();
  });

  it("shows navigation items when open (Dashboard visible to admin)", () => {
    renderPalette(true);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("shows all nav items for admin role", () => {
    renderPalette(true);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Posizioni")).toBeInTheDocument();
    expect(screen.getByText("Trade")).toBeInTheDocument();
  });

  it("navigates to the correct href when a nav item is clicked", async () => {
    renderPalette(true);
    const dashboardItem = screen.getByText("Dashboard");
    fireEvent.click(dashboardItem);
    expect(mockPush).toHaveBeenCalledWith("/");
  });

  it("calls onOpenChange(false) after navigating", async () => {
    const { onOpenChange } = renderPalette(true);
    const dashboardItem = screen.getByText("Dashboard");
    fireEvent.click(dashboardItem);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("shows 'Vai al simbolo' item when input is non-empty", async () => {
    renderPalette(true);
    const input = screen.getByPlaceholderText(/cerca comandi o simboli/i);
    await userEvent.type(input, "aapl");
    expect(await screen.findByText(/Vai al simbolo/i)).toBeInTheDocument();
  });

  it("shows uppercased symbol in the 'Vai al simbolo' item", async () => {
    renderPalette(true);
    const input = screen.getByPlaceholderText(/cerca comandi o simboli/i);
    await userEvent.type(input, "msft");
    expect(await screen.findByText("MSFT")).toBeInTheDocument();
  });

  it("navigates to /symbol/<UPPER> when 'Vai al simbolo' is clicked", async () => {
    renderPalette(true);
    const input = screen.getByPlaceholderText(/cerca comandi o simboli/i);
    await userEvent.type(input, "aapl");
    const symbolItem = await screen.findByText(/Vai al simbolo/i);
    // Click the parent Command.Item (the closest ancestor with role="option")
    const item = symbolItem.closest('[role="option"]') ?? symbolItem;
    fireEvent.click(item);
    expect(mockPush).toHaveBeenCalledWith("/symbol/AAPL");
  });

  it("does NOT show 'Vai al simbolo' when input is empty", () => {
    renderPalette(true);
    expect(screen.queryByText(/Vai al simbolo/i)).not.toBeInTheDocument();
  });

  it("shows the theme toggle command", () => {
    renderPalette(true);
    expect(screen.getByText(/Cambia tema/i)).toBeInTheDocument();
  });

  it("opens the palette on ⌘K keydown", async () => {
    const onOpenChange = vi.fn();
    render(<CommandPalette open={false} onOpenChange={onOpenChange} />);
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it("opens the palette on Ctrl+K keydown", async () => {
    const onOpenChange = vi.fn();
    render(<CommandPalette open={false} onOpenChange={onOpenChange} />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it("navigates to /trades when Trade item is clicked", async () => {
    renderPalette(true);
    const tradeItem = screen.getByText("Trade");
    fireEvent.click(tradeItem);
    expect(mockPush).toHaveBeenCalledWith("/trades");
  });
});
