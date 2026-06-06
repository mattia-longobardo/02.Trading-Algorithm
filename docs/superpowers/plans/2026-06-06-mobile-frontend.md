# Mobile Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Next.js trading console genuinely mobile-first (one codebase): a bottom tab bar on phones, wide tables rendered as stacked cards, and touch-tuned dashboard/dialogs — desktop layout unchanged.

**Architecture:** Mobile-first Tailwind (base classes = phone; `md:`/`lg:` add desktop). New `BottomNav` shown `<lg`; positions/trades render both a card list (shown on small screens) and the existing table (shown on large screens) from the same data. No backend changes.

**Tech Stack:** Next.js 15 (App Router), React 19, Tailwind 4 (CSS-var tokens), shadcn/Radix, lucide-react, React Query, SSE. Tests: vitest + @testing-library/react.

---

## Conventions

**Working directory:** worktree root `/home/mattia/docker/projects/trading/.claude/worktrees/mobile-frontend`; the frontend lives in `frontend/`. `frontend/node_modules` is already installed.

**Commands (run on the host, from `frontend/`):**
```bash
cd frontend
npx vitest run <path>      # a single test file
npm run typecheck          # tsc --noEmit
npm run lint               # next lint
npm run build              # next build (heavier; final gate)
```

**Tailwind tokens:** colors via `bg-(--color-...)`, `text-(--color-...)`, `border-(--color-...)` (e.g. `--color-bg`, `--color-panel`, `--color-line`, `--color-text`, `--color-muted`, `--color-accent`, `--color-danger`). Breakpoints: `sm` 640, `md` 768, `lg` 1024 (desktop sidebar appears at `lg`).

**Commit cadence:** one commit per task. End every commit message with:
```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
```

**Scope note:** This plan delivers the core mobile experience (shell + nav, positions, trades, dashboard, dialogs, global touch). The **secondary pages** (`/ops`, `/universe`, `/reports`, `/admin`, `/symbol/[symbol]`) get responsive polish in a **separate Phase-2 plan** after this lands (they need per-page inspection). They remain reachable on mobile via the "Altro" sheet and the existing responsive container.

---

## File Structure
- **Modify** `frontend/src/app/layout.tsx` — add Next 15 `export const viewport` (+ themeColor).
- **Modify** `frontend/src/app/globals.css` — safe-area helpers.
- **Modify** `frontend/src/components/layout/nav-items.ts` — `MOBILE_PRIMARY` + split helpers.
- **Create** `frontend/src/components/layout/bottom-nav.tsx` — phone bottom tab bar + "Altro" sheet.
- **Modify** `frontend/src/components/app-shell.tsx` — mount `BottomNav` `<lg`, content bottom padding, retire the hamburger drawer on phone (keep slim top bar with brand + theme + logout).
- **Modify** `frontend/src/components/positions/positions-live-table.tsx` — add a card list (`md:hidden`) beside the table (`hidden md:block`).
- **Modify** `frontend/src/components/trades/trades-table.tsx` (+ new `frontend/src/components/trades/trade-card.tsx`) — card list (`lg:hidden`) beside the table (`hidden lg:block`).
- **Modify** `frontend/src/app/trades/page.tsx` (or the filter component) — filters stack full-width on phone.
- **Modify** dashboard chart components + `frontend/src/app/page.tsx` — chart heights/legends on phone.
- **Modify** `frontend/src/components/trades/*-dialog.tsx` — bottom-sheet sizing + `text-base` inputs.
- **Tests** colocated under `__tests__/`.

---

## Task 1: Viewport + safe-area

**Files:** Modify `frontend/src/app/layout.tsx`, `frontend/src/app/globals.css`.

- [ ] **Step 1: Add the `viewport` export**

In `frontend/src/app/layout.tsx`, change the `import type { Metadata }` line to also import `Viewport`, and add a `viewport` export after `metadata`:
```tsx
import type { Metadata, Viewport } from "next";
```
```tsx
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0b0e14" },
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
  ],
};
```

- [ ] **Step 2: Add safe-area utilities to globals.css**

Append to `frontend/src/app/globals.css`:
```css
/* Mobile safe-area helpers (iOS notch / home indicator). */
.pb-safe { padding-bottom: env(safe-area-inset-bottom); }
.h-bottom-nav { height: 3.5rem; }
.pb-bottom-nav { padding-bottom: calc(3.5rem + env(safe-area-inset-bottom)); }
```

- [ ] **Step 3: Typecheck + build**

Run: `cd frontend && npm run typecheck`  → Expected: no errors.
Run: `cd frontend && npm run build`  → Expected: builds successfully.

- [ ] **Step 4: Commit**
```bash
git add frontend/src/app/layout.tsx frontend/src/app/globals.css
git commit -m "feat(mobile): viewport-fit=cover + safe-area utilities

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Bottom navigation component

**Files:** Modify `frontend/src/components/layout/nav-items.ts`; Create `frontend/src/components/layout/bottom-nav.tsx`; Test `frontend/src/components/layout/__tests__/bottom-nav.test.tsx`.

- [ ] **Step 1: Add the primary-route split to nav-items.ts**

Append to `frontend/src/components/layout/nav-items.ts`:
```ts
/** Routes shown directly in the phone bottom tab bar (in this order). */
export const MOBILE_PRIMARY: readonly string[] = ["/", "/positions", "/trades"];

/** Primary nav items (bottom-bar tabs) from a role-filtered list. */
export function primaryNav(items: NavItem[]): NavItem[] {
  return MOBILE_PRIMARY.map((href) => items.find((i) => i.href === href)).filter(
    (i): i is NavItem => Boolean(i)
  );
}

/** Secondary nav items (shown under the "Altro" sheet). */
export function secondaryNav(items: NavItem[]): NavItem[] {
  return items.filter((i) => !MOBILE_PRIMARY.includes(i.href));
}
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/components/layout/__tests__/bottom-nav.test.tsx`:
```tsx
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
```

- [ ] **Step 3: Run, expect FAIL**

Run: `cd frontend && npx vitest run src/components/layout/__tests__/bottom-nav.test.tsx`
Expected: FAIL — cannot resolve `@/components/layout/bottom-nav`.

- [ ] **Step 4: Implement BottomNav**

Create `frontend/src/components/layout/bottom-nav.tsx`:
```tsx
"use client";

import { MoreHorizontal } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { primaryNav, secondaryNav, type NavItem } from "@/components/layout/nav-items";

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function BottomNav({ items }: { items: NavItem[] }) {
  const pathname = usePathname();
  const [sheetOpen, setSheetOpen] = useState(false);
  const primary = primaryNav(items);
  const secondary = secondaryNav(items);

  // Close the "Altro" sheet on navigation.
  useEffect(() => {
    setSheetOpen(false);
  }, [pathname]);

  const cell =
    "flex flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-[11px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)";

  return (
    <>
      {sheetOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label="Chiudi"
            onClick={() => setSheetOpen(false)}
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
          />
          <div className="pb-safe absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-(--color-line) bg-(--color-panel) p-3 shadow-2xl">
            <div className="mx-auto mb-2 h-1 w-10 rounded-full bg-(--color-line)" />
            <nav className="grid grid-cols-2 gap-2">
              {secondary.map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    aria-current={isActive(pathname, item.href) ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-3 rounded-lg border border-(--color-line) px-3 py-3 text-sm",
                      isActive(pathname, item.href)
                        ? "bg-(--color-elevated) text-(--color-text)"
                        : "text-(--color-muted)"
                    )}
                  >
                    <Icon className="size-4" />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </nav>
          </div>
        </div>
      )}

      <nav
        aria-label="Navigazione principale"
        className="pb-safe fixed inset-x-0 bottom-0 z-40 flex border-t border-(--color-line) bg-(--color-bg)/95 backdrop-blur lg:hidden"
      >
        {primary.map((item) => {
          const Icon = item.icon;
          const active = isActive(pathname, item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(cell, active ? "text-(--color-accent)" : "text-(--color-muted)")}
            >
              <Icon className="size-5" />
              <span>{item.label}</span>
            </Link>
          );
        })}
        <button
          type="button"
          aria-label="Altro"
          onClick={() => setSheetOpen(true)}
          className={cn(cell, "text-(--color-muted)")}
        >
          <MoreHorizontal className="size-5" />
          <span>Altro</span>
        </button>
      </nav>
    </>
  );
}
```

- [ ] **Step 5: Run, expect PASS**

Run: `cd frontend && npx vitest run src/components/layout/__tests__/bottom-nav.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**
```bash
git add frontend/src/components/layout/nav-items.ts frontend/src/components/layout/bottom-nav.tsx frontend/src/components/layout/__tests__/bottom-nav.test.tsx
git commit -m "feat(mobile): bottom tab bar with Altro sheet for secondary routes

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Wire BottomNav into the app shell

**Files:** Modify `frontend/src/components/app-shell.tsx`.

Goal: on phone (`<lg`) show the bottom nav and a slim top bar (brand + theme toggle + logout); retire the hamburger drawer (superseded). Desktop (`lg+`) unchanged. Content clears the bottom bar.

- [ ] **Step 1: Edit `app-shell.tsx`**

1. Add imports near the top:
```tsx
import { BottomNav } from "@/components/layout/bottom-nav";
```
2. Remove the hamburger drawer machinery on phone: delete the `Menu`/`X` import usage for the drawer, the `mobileOpen` state, the two `useEffect`s that depend on `mobileOpen` (route-close + scroll-lock/escape), and the `{mobileOpen && (...drawer...)}` block. Keep `CommandPalette`/`paletteOpen` as-is. (If removing `mobileOpen` leaves `Menu`/`X` unused, drop them from the lucide import.)
3. Replace the mobile top `<header>` (the hamburger header) with a slim bar containing brand + theme toggle + logout:
```tsx
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between gap-3 border-b border-(--color-line) bg-(--color-bg)/95 px-4 backdrop-blur lg:hidden">
          <div className="flex items-center gap-2">
            <div className="size-6 rounded bg-(--color-accent) grid place-items-center text-slate-950 text-xs font-bold">
              T
            </div>
            <p className="text-sm font-semibold">Trading Console</p>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle className="size-8" />
            <Button variant="secondary" size="sm" aria-label="Logout" onClick={logout}>
              <LogOut className="size-4" />
            </Button>
          </div>
        </header>
```
4. Give the content container bottom padding for the bar and render `BottomNav` at the end of `<main>`:
```tsx
        <div className="mx-auto w-full max-w-7xl px-4 py-6 pb-bottom-nav sm:px-6 lg:px-8 lg:py-8 lg:pb-8">
          {children}
        </div>
        <BottomNav items={items} />
```
(`items` is the already-computed `visibleNavFor(user.role)`.)

- [ ] **Step 2: Typecheck + lint + build**

Run: `cd frontend && npm run typecheck && npm run lint`  → Expected: no errors (no unused imports/vars left behind).
Run: `cd frontend && npm run build`  → Expected: builds.

- [ ] **Step 3: Re-run the bottom-nav test (still green)**

Run: `cd frontend && npx vitest run src/components/layout/__tests__/bottom-nav.test.tsx`  → Expected: PASS.

- [ ] **Step 4: Commit**
```bash
git add frontend/src/components/app-shell.tsx
git commit -m "feat(mobile): use bottom nav on phone; slim top bar; retire hamburger drawer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Positions — stacked cards on phone

**Files:** Modify `frontend/src/components/positions/positions-live-table.tsx`; Test `frontend/src/components/positions/__tests__/positions-live-table.test.tsx`.

The component currently renders a `min-w-[640px]` table. Add a card list shown `<md` and keep the table `md+`. `LivePosition` fields: `id, symbol, category, units, entry_price, current_price, unrealized_pnl, unrealized_pnl_pct, take_profit, stop_loss, is_buy`. Reuse the existing module-local `signedPnl`, `signedPct`, `DirectionHint` and the imported `pnlClass`, `formatNumber`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/positions/__tests__/positions-live-table.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PositionsLiveTable } from "@/components/positions/positions-live-table";
import type { LivePosition } from "@/lib/types";

const pos: LivePosition = {
  id: 1, symbol: "AAPL", category: "STOCK", units: 3, entry_price: 100,
  current_price: 110, unrealized_pnl: 30, unrealized_pnl_pct: 10,
  take_profit: 130, stop_loss: 90, position_id: "p1", instrument_id: 101, is_buy: true,
};

describe("PositionsLiveTable mobile cards", () => {
  it("renders a card list with symbol and signed PnL", () => {
    render(<PositionsLiveTable positions={[pos]} />);
    // Card list is present (md:hidden) in addition to the table.
    const cards = screen.getByTestId("positions-card-list");
    expect(cards).toHaveTextContent("AAPL");
    expect(cards).toHaveTextContent("+30");
    expect(cards).toHaveTextContent("+10");
  });

  it("symbol links to the symbol detail page in the card", () => {
    render(<PositionsLiveTable positions={[pos]} />);
    const cards = screen.getByTestId("positions-card-list");
    const link = cards.querySelector('a[href="/symbol/AAPL"]');
    expect(link).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run, expect FAIL**

Run: `cd frontend && npx vitest run src/components/positions/__tests__/positions-live-table.test.tsx`
Expected: FAIL — no `positions-card-list` testid.

- [ ] **Step 3: Add the card list + responsive toggle**

In `frontend/src/components/positions/positions-live-table.tsx`:

a) Add a `PositionCard` component (place it above `PositionsLiveTable`):
```tsx
function PositionCard({ pos }: { pos: LivePosition }) {
  const pnl = pos.unrealized_pnl;
  const pnlPct = pos.unrealized_pnl_pct;
  return (
    <div className="rounded-xl border border-(--color-line) bg-(--color-panel)/40 p-3">
      <div className="flex items-center justify-between">
        <span className="inline-flex items-center gap-1 font-medium">
          <Link href={`/symbol/${encodeURIComponent(pos.symbol)}`} className="hover:underline">
            {pos.symbol}
          </Link>
          <DirectionHint isBuy={pos.is_buy} />
        </span>
        <span className={`tnum text-right text-sm font-semibold ${pnlClass(pnl ?? 0)}`}>
          {signedPnl(pnl)} <span className="text-xs font-normal">({signedPct(pnlPct)})</span>
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-(--color-muted)">
        <div className="flex justify-between"><dt>Qtà</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.units)}</dd></div>
        <div className="flex justify-between"><dt>Ultimo</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.current_price)}</dd></div>
        <div className="flex justify-between"><dt>Entry</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.entry_price)}</dd></div>
        <div className="flex justify-between"><dt>TP</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.take_profit)}</dd></div>
        <div className="flex justify-between"><dt>SL</dt><dd className="tnum text-(--color-text)">{formatNumber(pos.stop_loss)}</dd></div>
      </dl>
    </div>
  );
}
```

b) In `PositionsLiveTable`, wrap the return so the card list shows `<md` and the table `md+`. Replace the final `return ( <div className="overflow-x-auto ...">...table...</div> )` with:
```tsx
  return (
    <>
      {/* Phone: stacked cards (no horizontal scroll) */}
      <div data-testid="positions-card-list" className="space-y-2 md:hidden">
        {positions.map((pos) => (
          <PositionCard key={pos.id} pos={pos} />
        ))}
      </div>

      {/* Tablet/desktop: full table */}
      <div className="hidden overflow-x-auto rounded-xl border border-(--color-line) md:block">
        <table className="w-full min-w-[640px] text-sm">
          {/* ...existing thead + tbody unchanged... */}
        </table>
      </div>
    </>
  );
```
(Keep the existing `<thead>`/`<tbody>` markup intact inside the table; only the wrapper changed. The `loading` and empty-state branches stay as they are — they render for both layouts.)

- [ ] **Step 4: Run, expect PASS**

Run: `cd frontend && npx vitest run src/components/positions/__tests__/positions-live-table.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Typecheck + build**

Run: `cd frontend && npm run typecheck && npm run build`  → Expected: OK.

- [ ] **Step 6: Commit**
```bash
git add frontend/src/components/positions/positions-live-table.tsx frontend/src/components/positions/__tests__/positions-live-table.test.tsx
git commit -m "feat(mobile): positions render as stacked cards on phone

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Trades — stacked cards on phone

**Files:** Create `frontend/src/components/trades/trade-card.tsx`; Modify `frontend/src/components/trades/trades-table.tsx`; Test `frontend/src/components/trades/__tests__/trade-card.test.tsx`.

The trades table is `min-w-[1200px]` (22 columns). On `<lg` render a card list; keep the table `lg+`. FIRST read `frontend/src/lib/types.ts` (`interface Trade`) for exact field names and `frontend/src/components/trades/trade-row.tsx` for the existing field rendering + the exported `pnlClass`/`statusVariant` helpers and the `formatNumber`/format helpers it uses — the card must reuse those, not re-derive formatting.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/trades/__tests__/trade-card.test.tsx`. Build a `Trade` fixture using the real field names from `types.ts` (read it first). Assert:
```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TradeCard } from "@/components/trades/trade-card";
import type { Trade } from "@/lib/types";

// Build with the real Trade shape (read src/lib/types.ts). Minimal but valid:
const trade = { /* ...fill every required Trade field; symbol:"AAPL", status:"OPEN",
  category:"STOCK", pnl: 42, entry_price: 100, ... */ } as Trade;

describe("TradeCard", () => {
  it("shows symbol, status and signed PnL collapsed", () => {
    render(<TradeCard trade={trade} onEdit={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText(/OPEN/i)).toBeInTheDocument();
    expect(screen.getByText(/\+?42/)).toBeInTheDocument();
  });

  it("expands to reveal detail fields", async () => {
    const user = userEvent.setup();
    render(<TradeCard trade={trade} onEdit={vi.fn()} onClose={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /dettagli/i }));
    expect(screen.getByText(/Entry/i)).toBeInTheDocument();
  });

  it("invokes onEdit/onClose from the actions", async () => {
    const onEdit = vi.fn(); const onClose = vi.fn();
    const user = userEvent.setup();
    render(<TradeCard trade={trade} onEdit={onEdit} onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: /modifica/i }));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `@/components/trades/trade-card` not found.
Run: `cd frontend && npx vitest run src/components/trades/__tests__/trade-card.test.tsx`

- [ ] **Step 3: Implement `TradeCard`**

Create `frontend/src/components/trades/trade-card.tsx` (`"use client"`). It mirrors `trade-row.tsx`'s formatting (import `pnlClass`, `statusVariant` from `./trade-row`; `formatNumber` from `@/lib/format`; `Badge` from `@/components/ui/badge`; `Button`). Collapsed header row: `symbol` (link to `/symbol/{symbol}`), a status `Badge` (via `statusVariant`), and signed `pnl` colored by `pnlClass`. A "Dettagli" toggle button (`useState`) reveals a `<dl>` grid with the detail fields that exist on `Trade` (entry/target/quantity/allocated capital/take profit/trailing tp distance & activation/stop loss/trailing stop/current price/open & close timestamps/close reason — use the SAME fields and `formatNumber` calls as `trade-row.tsx`). Footer: two buttons "Modifica" (`onClick={() => onEdit(trade)}`) and "Chiudi" (`onClick={() => onClose(trade)}`), shown only when the trade is editable/closable exactly as `trade-row.tsx` decides (mirror its condition). Props:
```tsx
interface TradeCardProps { trade: Trade; onEdit: (t: Trade) => void; onClose: (t: Trade) => void; }
```

- [ ] **Step 4: Render the card list in `trades-table.tsx`**

In `frontend/src/components/trades/trades-table.tsx`, import `TradeCard`, and wrap the output so cards show `<lg` and the table `lg+`. Replace the `return ( <div className="overflow-x-auto">...table...</div> )` with:
```tsx
  return (
    <>
      <div className="space-y-2 lg:hidden">
        {items.map((t) => (
          <TradeCard key={t.id} trade={t} onEdit={onEdit} onClose={onClose} />
        ))}
      </div>
      <div className="hidden overflow-x-auto lg:block">
        <table className="w-full min-w-[1200px] border-separate border-spacing-y-1 text-sm">
          {/* ...existing thead + tbody unchanged... */}
        </table>
      </div>
    </>
  );
```
(Keep the `loading` and empty-state early returns as-is — they apply to both.)

- [ ] **Step 5: Run, expect PASS**
Run: `cd frontend && npx vitest run src/components/trades/__tests__/trade-card.test.tsx`  → Expected: PASS.

- [ ] **Step 6: Stack the trade filters full-width on phone**

Read `frontend/src/app/trades/page.tsx` (or the filters component it renders). The filter container uses `md:grid-cols-3`; ensure the base is `grid-cols-1` (full-width stacked on phone). If it already is, no change. Make selects/inputs `w-full`.

- [ ] **Step 7: Typecheck + lint + build**
Run: `cd frontend && npm run typecheck && npm run lint && npm run build`  → Expected: OK.

- [ ] **Step 8: Commit**
```bash
git add frontend/src/components/trades/trade-card.tsx frontend/src/components/trades/trades-table.tsx frontend/src/components/trades/__tests__/trade-card.test.tsx frontend/src/app/trades/page.tsx
git commit -m "feat(mobile): trades render as expandable cards on phone

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Dashboard mobile polish

**Files:** Modify `frontend/src/app/page.tsx` and the chart components under `frontend/src/components/dashboard/` (`category-allocation-chart.tsx`, `pnl-by-symbol-chart.tsx`, `returns-distribution-chart.tsx`) + the equity chart in `page.tsx`.

- [ ] **Step 1: Reduce chart heights on phone**

In each chart wrapper currently using a fixed `h-72`, change to `h-56 sm:h-72` (shorter on phone, original on `sm+`). The recharts `ResponsiveContainer` already handles width; ensure each chart's parent has the responsive height class. The `lightweight-charts` price chart resizes to width — leave it.

- [ ] **Step 2: Ensure legends/grids wrap on phone**

Where a chart legend uses a fixed multi-column grid, ensure it is `grid-cols-2` (already the case for allocation) and wraps; no fixed pixel widths. The KPI strip (`kpi-strip.tsx`) already uses `grid-cols-2 md:grid-cols-4 xl:grid-cols-6` — leave the column counts; only reduce card padding to `p-3 sm:p-4` if cramped.

- [ ] **Step 3: Verify dashboard still renders**

Run the existing dashboard-related tests if any, then build:
Run: `cd frontend && npm run typecheck && npm run build`  → Expected: OK.
Run: `cd frontend && npx vitest run src/components/dashboard` (if any tests exist there) → Expected: PASS or "no tests".

- [ ] **Step 4: Commit**
```bash
git add frontend/src/app/page.tsx frontend/src/components/dashboard
git commit -m "feat(mobile): shorter charts + condensed KPIs on phone

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Dialogs & forms touch polish

**Files:** Modify `frontend/src/components/trades/*-dialog.tsx` (edit + close trade dialogs) and any settings form on `/admin`.

- [ ] **Step 1: Make dialog content mobile-friendly**

In each Radix Dialog content className, ensure on phone it is near-full-width and bottom-anchored, expanding to a centered modal on `sm+`. Apply (adapt to the existing classes; this is the target):
```
className="... w-full max-w-[100vw] rounded-t-2xl p-4 sm:max-w-lg sm:rounded-2xl ..."
```
Make form inputs `text-base` (prevents iOS zoom) and `w-full`, action buttons full-width on phone (`w-full sm:w-auto`), with `inputMode="decimal"` on numeric price/quantity fields.

- [ ] **Step 2: Verify**
Run: `cd frontend && npm run typecheck && npm run build`  → Expected: OK.
Run the existing trades dialog/row tests: `cd frontend && npx vitest run src/components/trades` → Expected: PASS (existing tests unaffected).

- [ ] **Step 3: Commit**
```bash
git add frontend/src/components/trades
git commit -m "feat(mobile): touch-friendly trade dialogs (bottom-sheet, text-base inputs)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Full gate + responsive review

- [ ] **Step 1: Full test suite**
Run: `cd frontend && npx vitest run`  → Expected: all pass (existing + new).

- [ ] **Step 2: Typecheck + lint + build**
Run: `cd frontend && npm run typecheck && npm run lint && npm run build`  → Expected: all clean.

- [ ] **Step 3: Responsive review checklist (manual)**

Build and review (or `npm run dev`) at ~390px and ~768px widths. Confirm:
- Bottom nav visible/reachable on phone; "Altro" sheet lists secondary routes; desktop (≥1024px) shows the sidebar and NO bottom nav.
- Positions and Trades show stacked cards on phone with NO horizontal scroll; the table reappears at `md`/`lg` respectively.
- Content clears the bottom nav (nothing hidden behind it); safe-area respected.
- Charts fit; dialogs are reachable and inputs don't trigger iOS zoom.

---

## Phase 2 (separate plan, after this lands)
Responsive polish for the secondary pages: `/ops`, `/universe`, `/reports`, `/admin`, `/symbol/[symbol]` — per-page inspection, stacking wide layouts, and converting any remaining wide tables to the card pattern established here.

---

## Self-Review Notes (author)
- **Spec coverage:** T1 viewport/safe-area; T2+T3 bottom-nav + shell (replaces hamburger); T4 positions cards (`md` switch); T5 trades cards (`lg` switch) + filters; T6 dashboard charts/KPI; T7 dialogs/forms touch; T8 gate + review. Secondary pages explicitly deferred to Phase 2 (noted, not silently dropped).
- **Type/name consistency:** `BottomNav({items})` consumes `visibleNavFor(role)`; `primaryNav`/`secondaryNav`/`MOBILE_PRIMARY` defined in T2 and used in T2's component. Positions card reuses the file's existing `signedPnl`/`signedPct`/`DirectionHint`/`pnlClass`/`formatNumber`. `TradeCard` mirrors `trade-row.tsx` helpers/fields (implementer reads `types.ts` + `trade-row.tsx` for exact `Trade` fields and the editable/closable condition).
- **Testing reality:** vitest/jsdom can't evaluate Tailwind breakpoints, so tests assert content/DOM (both card list and table exist; data mapping; expand/actions) and the visual breakpoint behavior is covered by the build + manual review in T8.
- **Known assumption:** T5/T6/T7 require reading the named existing files for exact field names/classes before editing (the plan names them precisely); the `Trade` fixture in T5's test must use the real field names from `types.ts`.
