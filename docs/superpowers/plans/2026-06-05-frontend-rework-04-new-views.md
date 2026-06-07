# Frontend Rework — Plan 4: New views (Symbol detail, command palette) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Backend Python (`unittest`, run in Docker). Frontend Vitest. Keep both green. `lightweight-charts` is a canvas library — it must run client-only (guard in effects / dynamic import, never during SSR).

**Goal:** Add the trading-focused views from the spec: a Symbol/position detail page with a candlestick chart (entry/TP/SL overlays) + that symbol's trade history, and a global ⌘K command palette. Requires one new backend candles endpoint and two frontend deps (`lightweight-charts`, `cmdk`).

**Architecture:** A new auth-gated `GET /api/candles` returns OHLC bars from the eToro client (one GET per request). A client-only `PriceChart` wraps `lightweight-charts`. The Symbol detail route `/symbol/[symbol]` composes the chart (with horizontal price lines for entry/TP/SL of any open position) + a trade-history table filtered to that symbol; positions/trades rows link to it. A `CommandPalette` (cmdk) mounts globally in the app shell, opening on ⌘K/Ctrl-K for page nav, symbol search, theme toggle, and (admin) job triggers.

**Tech Stack:** FastAPI (Python), eToro client `get_bars`, Next.js 15, `lightweight-charts` ^4, `cmdk` ^1, React Query, Vitest.

---

### Task 1: Backend — `GET /api/candles` endpoint

**Files:** Modify `backend/api/api_server.py`. Test: add to an existing api test module (Docker).

- [ ] **Step 1 — Read** `backend/clients/etoro_client.py` `get_bars(symbol, category, start, end)` and `get_candles_by_instrument(...)` to learn the returned bar shape (timestamp/open/high/low/close/volume keys). Read how `/api/trades` resolves the broker in `create_app` (the `brokers`/`_resolve_brokers` pattern).
- [ ] **Step 2 — Add the endpoint** (auth-gated via `Depends(get_current_user)`):
  - `GET /api/candles?symbol=BTC&category=CRYPTO&granularity=OneDay&count=120`.
  - Resolve the eToro broker; call `broker.get_bars(symbol, category, ...)` (or `get_candles_by_instrument` if that's the cleaner path for a count of recent candles). Map each bar to `{"t": <iso utc>, "o": float, "h": float, "l": float, "c": float, "v": float|None}`.
  - Return `{"symbol": symbol, "category": category, "granularity": granularity, "candles": [...]}`.
  - Validate `count` (e.g. `Query(default=120, ge=1, le=1000)`); on broker error return a clean 502/error via the file's existing `_error(...)` helper. Reuse the existing time/iso helpers.
- [ ] **Step 3 — Test** (Docker): if the suite has a FastAPI `TestClient` harness (see `tests/test_scheduler_api.py`), assert `/api/candles` requires auth (401 without cookie) and, with a stubbed broker returning two bars, returns the mapped shape. Otherwise unit-test the bar→dict mapping helper if you factor one out. Match the suite's style.
- [ ] **Step 4 — Run** backend tests in Docker; expect PASS. Commit: `feat(etoro): /api/candles OHLC endpoint`.

---

### Task 2: Frontend — deps + client-only `PriceChart` (candlestick)

**Files:** `frontend/package.json` (+ `lightweight-charts`, `cmdk`), create `src/components/charts/price-chart.tsx`, `src/lib/types.ts` (add `Candle`). Test: a light render/guard test.

- [ ] **Step 1 — Add deps:** `npm install lightweight-charts@^4 cmdk@^1`. Confirm clean install.
- [ ] **Step 2 — Types:** add `export interface Candle { t: string; o: number; h: number; l: number; c: number; v: number | null }`.
- [ ] **Step 3 — `PriceChart`** (`"use client"`): props `{ candles: Candle[]; priceLines?: { price: number; color?: string; title?: string }[]; height?: number }`. In a `useEffect`, create the chart with `createChart(el, {...})` from `lightweight-charts`, add a candlestick series, `setData` from candles (map `t`→`time` as a UTC timestamp/seconds or `yyyy-mm-dd`), add `series.createPriceLine(...)` for each `priceLines` entry (entry/TP/SL). Style to the dark theme (read CSS token values via `getComputedStyle(document.documentElement)` for bg/text/grid, or pass sensible dark defaults; up/down candle colors = accent green / danger red). Handle resize (ResizeObserver) and dispose the chart on cleanup. Guard everything in the effect (client-only). Render a sized container `<div ref=...>`.
- [ ] **Step 4 — Test:** render `<PriceChart candles={[]} />` in jsdom and assert it mounts without throwing (lightweight-charts needs a DOM; if it can't run in jsdom, mock the module with `vi.mock("lightweight-charts", ...)` returning a stub `createChart` and assert the component calls it with the candles). Keep it minimal — the goal is a smoke/guard test, not pixel assertions.
- [ ] **Step 5 — Verify** `npm test`/`typecheck`/`build`. Commit: `feat(frontend): lightweight-charts PriceChart + cmdk dep`.

---

### Task 3: Frontend — Symbol/position detail route

**Files:** create `src/app/symbol/[symbol]/page.tsx`, `src/components/symbol/symbol-header.tsx`, `src/components/symbol/symbol-trade-history.tsx`; link rows in `positions-live-table.tsx` and `trades-table.tsx`.

- [ ] **Step 1 — Page** `src/app/symbol/[symbol]/page.tsx` (`"use client"`): read the `symbol` route param. Fetch candles via React Query (`/api/candles?symbol=...&category=...&count=120` — derive category from the symbol's trades, default CRYPTO/STOCK heuristically or query both; simplest: fetch the symbol's trades first, take the category from the most recent, default "CRYPTO"). Fetch that symbol's trades (`/api/trades?...` — use the existing trades endpoint; filter by symbol client-side if the API lacks a symbol param). Optionally read `useLiveStream()` to show the live position for this symbol.
- [ ] **Step 2 — `SymbolHeader`:** symbol, category, current/live price, open-position PnL (if any), with `.tnum`.
- [ ] **Step 3 — Compose:** `SymbolHeader` + `<PriceChart candles={...} priceLines={[entry, TP, SL from the open trade]} />` + `<SymbolTradeHistory trades={...} />` (a compact table of this symbol's trades — reuse `TradeRow`/formatting where reasonable, or a slim dedicated table). Loading/empty/error states.
- [ ] **Step 4 — Linking:** make the symbol cell in `positions-live-table.tsx` and `trades-table.tsx` a `next/link` to `/symbol/<symbol>` (keep row action buttons working — the link is on the symbol text only).
- [ ] **Step 5 — Verify** `npm test`/`typecheck`/`build`. Commit: `feat(frontend): symbol/position detail view with candlestick`.

---

### Task 4: Frontend — ⌘K command palette

**Files:** create `src/components/command/command-palette.tsx` (+ a thin `ui/command.tsx` shadcn wrapper around `cmdk` if you want the styled primitives), mount it in `src/components/app-shell.tsx`. Test: palette open/filter test.

- [ ] **Step 1 — `CommandPalette`** (`"use client"`): a dialog (reuse the existing `Dialog` primitive or cmdk's own) listing commands: navigate to each nav route (Dashboard, Posizioni, Trade, Universe, Report, Operazioni, Amministrazione), "Vai al simbolo…" (free-text → `/symbol/<input>`), toggle theme (via `next-themes`), and — for admins — quick job triggers (optional; can navigate to `/ops`). Open on ⌘K / Ctrl-K (global `keydown` listener) and via a button; close on select/Esc. Use semantic tokens.
- [ ] **Step 2 — Mount** in `app-shell.tsx` (so it's available on every authenticated page). Add a small "⌘K" hint button in the shell (desktop topbar or sidebar footer near the theme toggle).
- [ ] **Step 3 — Test:** render `CommandPalette` (forced open), type to filter, assert a command item appears; assert selecting a nav item triggers navigation (mock `next/navigation`'s `useRouter().push`).
- [ ] **Step 4 — Verify** `npm test`/`typecheck`/`build`. Commit: `feat(frontend): ⌘K command palette`.

---

## Self-Review

**Spec coverage:** New views (spec §5 Symbol detail + §3/§5 command palette) → Tasks 3–4. Trading-grade candlestick (spec §4 lightweight-charts) → Tasks 1–3. Backend candles endpoint (implied by §5 detail) → Task 1.

**Placeholder scan:** Endpoint shape, `Candle` type, `PriceChart` props, route param, and palette commands are concretely specified. The candlestick test uses a module mock if jsdom can't host the canvas lib. No "TBD".

**Type/name consistency:** `Candle` (Task 2) consumed by `PriceChart` (Task 2) + the symbol page (Task 3) + the `/api/candles` response (Task 1). Symbol route `/symbol/<symbol>` referenced by Task 3 links + Task 4 palette. `useLiveStream`/`LivePosition` (Plan 3) reused in Task 3.

**Notes for the executor:**
- `lightweight-charts` MUST be client-only — never call `createChart` during SSR; do it in `useEffect`. If Next tree-shaking/SSR complains, dynamically import it inside the effect.
- One GET per `/api/candles` request — fine for the 60/min budget (not streamed).
- Don't over-style the candlestick; correct data + entry/TP/SL lines + dark theme is the goal. Deeper chart theming is Plan 5.
- Keep row action buttons functional when adding the symbol link (link only the symbol text).
