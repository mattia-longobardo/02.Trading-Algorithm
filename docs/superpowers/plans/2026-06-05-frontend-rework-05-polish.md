# Frontend Rework — Plan 5: Polish (theme-aware charts, states, a11y/responsive) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Frontend Vitest. Keep `npm test`/`typecheck`/`build` green after each task.

**Goal:** Final polish — make all charts theme-aware (work in light mode), give every data surface consistent loading/empty/error states (wiring the dashboard's already-passed `loading` props to skeletons), and complete an accessibility + responsive pass. This closes the spec's §9–§11 items and absorbs the remaining "trading-grade charts" work (the candlestick itself shipped in Plan 4).

**Architecture:** A `useChartTheme()` hook returns a token-aligned color palette keyed off `next-themes`' resolved theme; all Recharts charts + `PriceChart` consume it instead of hardcoded hexes. A small `Skeleton` primitive standardizes loading placeholders. A focused audit finds and fixes concrete a11y/responsive gaps.

**Tech Stack:** Next.js 15, Tailwind 4 tokens, next-themes, Recharts, lightweight-charts, Vitest.

> All paths under `frontend/`.

---

### Task 1: Theme-aware charts (`useChartTheme` + apply)

**Files:** create `src/components/charts/use-chart-theme.ts`; modify the Recharts chart components (`src/components/dashboard/category-allocation-chart.tsx`, `pnl-by-symbol-chart.tsx`, `returns-distribution-chart.tsx`, `src/components/equity-balance-chart.tsx`, and the inline equity curve in `src/app/page.tsx`) + `src/components/charts/price-chart.tsx`. Test: `use-chart-theme.test.ts`.

- [ ] **Step 1 — Hook test** `src/components/charts/__tests__/use-chart-theme.test.ts`: with `next-themes` mocked (or wrapped in `ThemeProvider`), assert `useChartTheme()` returns an object with the expected keys (`grid, axis, text, up, down, info, positive, negative, pie: string[]`) and that the dark vs light variants differ (mock `useTheme` to return each `resolvedTheme`).
- [ ] **Step 2 — Implement `useChartTheme()`**: uses `useTheme()` from `next-themes`; returns a palette object. Dark: `{ grid:"#1f2632", axis:"#6b7484", text:"#dfe6ee", up:"#22d37f", down:"#f06868", info:"#58a6ff", positive:"#22d37f", negative:"#f06868", tooltipBg:"#121722", tooltipBorder:"#1f2632", pie:["#22d37f","#58a6ff","#a78bfa","#f59e0b","#f06868","#2dd4bf"] }`. Light: darker-on-white equivalents (`grid:"#e4e7ec", axis:"#525c6e", text:"#1a1f29", up:"#12a150", down:"#e5484d", info:"#2f6feb", tooltipBg:"#ffffff", tooltipBorder:"#e4e7ec", pie:[...slightly darker]`). Guard `resolvedTheme` undefined → default dark.
- [ ] **Step 3 — Apply** to each Recharts chart: replace hardcoded `stroke`/`fill`/grid/axis/tooltip hexes with the hook's values (positive bars `theme.positive`, negative `theme.negative`, `CartesianGrid stroke={theme.grid}`, axis `tick={{ fill: theme.axis }}`, tooltip `contentStyle={{ background: theme.tooltipBg, border: '1px solid '+theme.tooltipBorder, color: theme.text }}`, pie cells cycle `theme.pie`). Keep chart structure/data unchanged.
- [ ] **Step 4 — Apply** to `PriceChart`: replace the hardcoded dark hexes with `useChartTheme()` values (layout background/text/grid, up/down candle colors). Default entry/TP/SL line colors: entry `theme.info`, TP `theme.up`, SL `theme.down` (still overridable by the `priceLines[].color` prop). The chart already recreates on data change, so reading the theme at effect time is fine; also depend on the theme palette so it restyles on toggle.
- [ ] **Step 5 — Verify** `npm test`/`typecheck`/`build`. Manually reason that charts now read correctly in both themes. Commit: `feat(frontend): theme-aware charts via useChartTheme`.

---

### Task 2: Consistent loading / empty / error states

**Files:** create `src/components/ui/skeleton.tsx`; modify dashboard chart components + `src/components/dashboard/kpi-strip.tsx` to consume their `loading` prop; ensure `positions`/`trades`/`reports` surfaces have loading + empty + error states. Test: `skeleton`/a chart loading test.

- [ ] **Step 1 — `Skeleton`**: a simple `export function Skeleton({ className })` → `<div className={cn("animate-pulse rounded-md bg-(--color-hover)", className)} />`.
- [ ] **Step 2 — Wire dashboard `loading`**: the dashboard chart components (`KpiStrip`, `CategoryAllocationChart`, `PnlBySymbolChart`, `ReturnsDistributionChart`) already accept `loading?: boolean` (currently unused). When `loading` is true, render a `Skeleton` placeholder sized like the chart/cards instead of an empty chart. When not loading and data is empty, render a small "Nessun dato" empty state.
- [ ] **Step 3 — Error states**: where a dashboard query can error (metrics/equity/allocation/etc.), surface a compact inline error (reuse `StatusBanner` kind="error" or a muted "Errore nel caricamento" line) rather than silently showing nothing. Keep it light — one consistent pattern.
- [ ] **Step 4 — Verify** the live positions table + trades table + reports already have empty states (they do); add loading skeletons where a query is in flight if missing. Confirm `useLiveStream`'s `connecting` state shows the `LiveBadge` (already wired).
- [ ] **Step 5 — Test**: a small test asserting a dashboard chart component renders a skeleton when `loading` and the empty state when given no data. Commit: `feat(frontend): consistent loading/empty/error states`.

---

### Task 3: Accessibility & responsive sweep

**Files:** various (targeted fixes only).

- [ ] **Step 1 — Audit** (the implementer should grep + read): find icon-only `<button>`/`<Link>` without `aria-label`; dialogs without an accessible title; tables missing `<caption>`/scope or proper `<th scope>`; any focus-trap/restore gaps in dialogs (Radix handles most); horizontal-scroll tables that need the sticky-first-column treatment (trades + positions already have it; check reports/universe/admin tables); color-only signals (PnL already pairs sign+color). List concrete findings.
- [ ] **Step 2 — Fix** the concrete findings: add `aria-label`s, `scope="col"` on table headers, `role="status"` where appropriate, ensure every dialog has a (possibly visually-hidden) title, and verify `:focus-visible` rings exist on interactive controls (the shell already uses them — extend the pattern to new components: command palette items, symbol links, theme toggle already done). Don't over-engineer; fix real gaps.
- [ ] **Step 3 — Responsive**: verify the dense desktop layouts collapse acceptably — sidebar→drawer (done), wide tables scroll (trades/positions done; apply `overflow-x-auto` to any new wide table lacking it), the dashboard grid stacks on small screens, the symbol page chart + tables fit. Fix any obvious overflow.
- [ ] **Step 4 — Verify** `npm test`/`typecheck`/`build` green. Commit: `feat(frontend): accessibility and responsive polish`.

---

## Self-Review

**Spec coverage:** Visual system completeness incl. light theme for charts (spec §9) → Task 1. Loading/empty/error states (spec §10) → Task 2. Accessibility + responsive (spec §10) → Task 3. Trading-grade charts polish (spec §4/§5; candlestick already in Plan 4) → Task 1 (Step 4). Testing (spec §11) → tests in each task.

**Placeholder scan:** Palette values, skeleton, and the audit→fix loop are concrete. The a11y task is inherently a find-then-fix sweep — the implementer lists findings before fixing, which is the correct shape for a polish pass (not a vague "improve a11y").

**Type/name consistency:** `useChartTheme()` palette keys (Task 1) consumed by every chart. `Skeleton` (Task 2) reused across dashboard. No new external deps.

**Notes for the executor:**
- Don't restructure working components — this is polish, not rework.
- Charts must read correctly in BOTH themes after Task 1; the toggle already exists in the shell.
- Keep commits scoped per task; keep the suite green.
- After Task 3, the branch should be merge-ready; the controller will run a final whole-branch review.
