# Mobile (phone) frontend — responsive, mobile-first

**Date:** 2026-06-06
**Status:** Approved design, pending implementation plan
**Area:** `frontend/` (Next.js 15 App Router, Tailwind 4, shadcn/Radix, React Query, SSE). No backend changes.

## Problem / goal

The trading console is desktop-first. On a ~390px phone it is usable but poor: the **trades table** is `min-w-[1200px]` (22 columns → constant horizontal scroll), the **positions table** is `min-w-[640px]`, navigation is a hamburger drawer, charts are fine but tall, and dialogs/forms aren't tuned for touch. We want the app to be genuinely **mobile-first** while keeping the desktop layout unchanged — one codebase, responsive.

## Decisions (from brainstorming)
- **Responsive, same codebase** (not a separate mobile UI; not a PWA — that's a possible follow-up).
- **All pages** responsive, prioritizing Dashboard, Positions, Trades (the on-the-go monitoring path).
- **Bottom tab bar** on phone for the primary sections + an "Altro" sheet for the rest; desktop sidebar unchanged.
- **Wide tables → stacked cards** on phone (no horizontal scroll).

## Architecture

Mobile-first Tailwind: base (unprefixed) classes target the phone; `md:`/`lg:` add tablet/desktop. The desktop sidebar already appears at `lg`. Breakpoints: phone `<md` (768), tablet `md`–`lg`, desktop `lg+`. Table→card switches at `<lg` for the 22-column trades table and `<md` for the 8-column positions table (those widths need real horizontal space).

The work is **componentized and phased** so each piece is independent and testable:

### 1. App shell + bottom navigation (`src/components/app-shell.tsx`, new `src/components/layout/bottom-nav.tsx`)
- Desktop (`lg+`): current sidebar + content, unchanged.
- Phone (`<lg`): keep a slim sticky top header (brand, theme toggle, account/logout); add a **fixed bottom tab bar** (`fixed bottom-0`, `lg:hidden`) with 4 items: **Dashboard, Posizioni, Trade, Altro**. "Altro" opens a Radix sheet/drawer listing the secondary routes (Universe, Report, Operazioni, Admin, Settings) + logout. Active tab highlighted from the current route.
- Content container gets bottom padding (`pb-20 lg:pb-0`) so the bar never overlaps; honor iOS safe areas via `env(safe-area-inset-bottom)` and `viewport-fit=cover`.
- Add a Next 15 `export const viewport` in `src/app/layout.tsx` (`width=device-width, initialScale=1, viewportFit="cover"`) and `themeColor` matching the dark `--color-bg`.
- The existing hamburger drawer can be removed on phone (superseded by bottom nav) or kept only for "Altro"; the plan picks one and keeps nav-items as the single source of truth.

### 2. Responsive table → card pattern (`src/components/positions/positions-live-table.tsx`, `src/components/trades/trades-table.tsx`)
- Render **both** representations in the DOM and toggle by CSS: a stacked **card list** (`lg:hidden` for trades / `md:hidden` for positions) and the existing **table** (`hidden lg:block` / `hidden md:block`). Both consume the same data + handlers (no logic duplication; only presentation differs).
- **Positions card**: symbol + category badge on the top row; current price and **P&L (color-coded)** prominent; units/entry/allocated in a compact secondary line. Live SSE updates apply to both views.
- **Trades card**: symbol + status badge + **P&L** on top; tap to **expand** a detail panel (entry/target/qty/capital/TP/trailing TP/SL/price/timestamps/reason); edit/close actions in a compact menu (the existing dialogs). Filters stack full-width (`grid-cols-1`).
- Factor the shared card chrome into a small local helper if it reduces duplication, but keep each table's mobile card colocated with its table (they change together).

### 3. Dashboard (`src/app/page.tsx`, `src/components/dashboard/*`)
- KPI strip already `grid-cols-2 md:grid-cols-4` — keep 2-up on phone, condense card padding/typography.
- Charts keep `ResponsiveContainer`; reduce height on phone (`h-56 sm:h-72`), ensure legends wrap and tooltips are touch-usable. The `lightweight-charts` price chart already resizes to container width.

### 4. Forms & dialogs (`src/components/trades/*-dialog.tsx`, settings forms)
- On phone, Radix Dialog content becomes a **bottom sheet / near-full-screen** panel (responsive width/positioning), inputs use `text-base` (prevents iOS zoom) and correct `inputMode`/`type`, buttons full-width, tap targets ≥44px.

### 5. Touch & interaction polish (global)
- Replace hover-only affordances (e.g. row `hover:bg`) with always-visible or tap states; ensure interactive elements are ≥44px; remove any fixed pixel widths that force horizontal scroll on phone.

## Data layer
Unchanged: React Query (REST via the `/api/proxy/*` route handlers) and SSE (`/api/live/stream`, pauses when tab hidden). No new endpoints.

## Phasing (drives the plan)
1. Shell: `viewport`/safe-area + bottom tab bar + "Altro" sheet.
2. Responsive tables: positions card view, then trades card view (+ filters).
3. Dashboard: KPI/charts mobile polish.
4. Remaining pages (Universe, Report, Operazioni, Admin, Settings, symbol detail) + dialogs/forms touch polish.

## Testing
Frontend has **vitest + @testing-library/react** (`npm run test` → `vitest run`), plus `npm run typecheck` (`tsc --noEmit`), `npm run lint`, `npm run build`.
- **Component tests** assert content/DOM and data mapping, not CSS breakpoints (jsdom doesn't evaluate Tailwind media queries): e.g. bottom-nav renders the 4 primary items and the active one is marked; the "Altro" sheet lists the secondary routes; the positions/trades **card list renders the same rows/fields as the table** (both present in the DOM) and P&L sign/color class is applied; a trade card expands to reveal detail fields; dialogs render with the expected inputs.
- **Gate** on every change: `typecheck` + `lint` + `build` must pass.
- **Responsive review**: manual check at ~390px (phone) and ~768px (tablet) that tables show cards (no horizontal scroll), bottom nav is reachable, and content clears the safe area. (If feasible, a Playwright mobile-viewport smoke can be added later — not required now.)

## Out of scope
- PWA / installable / offline (possible follow-up).
- Native app.
- Backend/API changes; new features or data. This is presentation/layout only.
- Redesign of the visual language (colors/tokens stay; we adapt layout to small screens).
