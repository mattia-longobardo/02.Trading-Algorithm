# Frontend Trading Rework — Design Spec

**Date:** 2026-06-05
**Status:** Approved (brainstorming complete)
**Topic:** Complete rework of the Next.js frontend into an optimized, real-time, eToro-only trading dashboard.

## 1. Summary

Rework the trading bot's web frontend end-to-end: a new visual identity, a restructured codebase, eToro-only simplification (the backend dropped Alpaca), real-time data, trading-grade charts, and three new trading-focused views. The proven stack is kept and extended rather than replaced.

**Visual direction:** "Hybrid Pro" structure (dark, rounded cards, clear hierarchy, subtle borders, eToro-green accent) rendered at **terminal density** (monospace tabular numbers, tight grids, more data per screen). Desktop-first, gracefully responsive. Dark theme default with an optional light theme.

## 2. Goals & Non-Goals

### Goals
- New look & feel: dark-first, dense, professional trading aesthetic with consistent design tokens.
- Restructure oversized page files into focused, independently testable components.
- Remove all multi-provider scaffolding; the app is eToro-only.
- Real-time data: live prices, open-position PnL, and account equity pushed from the backend.
- Trading-grade charting (candlesticks with entry/TP/SL overlays) alongside the existing analytics charts.
- Consolidated navigation (8 pages → 7 top-level + a detail route).
- New views: live Positions board, Symbol/Position detail, and a ⌘K command palette.
- Accessibility (ARIA, focus management, keyboard nav) and consistent loading/empty/error states.
- Component tests where none exist today.

### Non-Goals
- No second broker. Multi-provider abstraction is removed, not preserved.
- No change to the cookie-based auth model or the same-origin proxy architecture.
- No backend trading-logic changes beyond a single read-only live-data endpoint.
- No migration of historical data; the backend/DB is a clean eToro slate already.

## 3. Current State (baseline)

- **Stack:** Next.js 15 (App Router), React 19, TypeScript (strict), Tailwind 4, shadcn/Radix UI, TanStack React Query, Recharts, Zod (light use). Italian-locale `Intl` formatting.
- **Pages (8):** `/` Dashboard, `/orders`, `/universe`, `/reports`, `/prompts` (admin), `/settings`, `/console` (admin), `/logs`.
- **Backend integration:** all browser calls tunnel through a Next.js route handler `app/api/proxy/[...path]/route.ts` to `BACKEND_INTERNAL_URL` (default `http://backend:8000`); supports SSE streaming (used by `/logs`). Cookie auth, 401 → `/login`.
- **Problems carried in:** hardcoded `Provider = "alpaca"` across types, settings, prompt keys, secret fields, and `alpaca_order_id`; monolithic pages (dashboard 531, settings 686, orders 611, reports 463 LOC); weak responsiveness on wide tables; minimal ARIA; no component tests.

## 4. Stack Decisions

The base stack is kept. Targeted additions/changes:

| Area | Decision | Rationale |
|------|----------|-----------|
| Analytics charts | Keep **Recharts** | Equity curve, allocation donut, returns histogram, PnL-by-symbol are well served already. |
| Price charts | Add **lightweight-charts** (TradingView) | True candlestick/financial charts with line/area series and price-line overlays for entry/TP/SL. Used on Symbol detail + Positions. |
| Live data | Add backend **SSE** endpoint + frontend `useLiveStream()` | The bot already polls eToro quotes each monitor tick; tee that out instead of fast-polling REST. Ticks update the React Query cache. |
| Theming | Add **next-themes** + Tailwind CSS-variable tokens | Dark default, light optional, single source of design tokens. |
| Command palette | Add **cmdk** (shadcn Command) | ⌘K nav, symbol search, job triggers. |
| State | Keep **React Query + Auth Context** | No Redux/Zustand. Live ticks flow into the existing query cache. |
| Tests | Add **Vitest + React Testing Library** | No component tests exist today; add them for the live hook, formatters, and key components. |

## 5. Information Architecture

Consolidated navigation (top-level, 7 items) plus a non-nav detail route and a global palette:

- **Dashboard** (`/`) — KPI strip, equity curve, allocation, returns distribution, PnL-by-symbol, recent trades.
- **Positions** (`/positions`) — NEW. Dense, always-live board of open positions (the "cockpit"). Live LAST/PnL, sortable, click-through to detail.
- **Trades** (`/trades`) — the former `/orders`: historical/filterable trade table with inline edit. Route renamed; `/orders` redirects.
- **Universe** (`/universe`) — eToro universe management (STOCK/CRYPTO), add/remove symbols, live quote/error.
- **Reports** (`/reports`) — folder tree, search, PDF/JSON preview, download.
- **Ops** (`/ops`) — NEW merge of Console (manual jobs, admin) + Logs (live SSE stream) as two panels/tabs.
- **Admin** (`/admin`) — NEW grouping of Settings (Environment/Strategy + eToro broker), Prompts (admin), and Users as tabs. Replaces `/settings` and `/prompts`; old routes redirect.

**Symbol/Position detail** (`/symbol/[id]`) — non-nav, reached by clicking a position or symbol. Candlestick price chart with entry/TP/SL price-line overlays, live PnL header, and that symbol's trade history.

**Command palette** (⌘K) — global: jump to any page, search a symbol → its detail, trigger a manual job (admin), toggle theme.

## 6. eToro-Only Simplification

- Delete the `Provider` union, `ALL_PROVIDERS`, `PROVIDER_LABELS`, provider filters, provider columns, and the provider selector UI on Trades/Universe/Prompts.
- Replace `AlpacaPromptKey`/`ALPACA_PROMPT_KEYS` with a single eToro prompt-key set sourced from the backend `/api/prompts` response.
- Rename trade fields to match the new backend schema: `alpaca_order_id` → `position_id` / `order_reference_id`; surface `instrument_id` where useful.
- Settings broker section becomes **eToro** only: account type (demo/real, read-only — set via `.env`), keys shown read-only. Drop Alpaca-specific numeric caps that no longer exist; keep eToro-relevant strategy params surfaced by `/api/settings`.
- `useProviders()` and `/api/providers` usage collapses to an eToro constant (or is removed if the backend no longer needs it).

> Note: field/endpoint names above are reconciled against the actual backend during the planning phase; the implementation plan will confirm exact `/api/settings`, `/api/prompts`, and `/api/trades` shapes before edits.

## 7. Real-Time Data Layer

### Backend (single addition)
- New endpoint **`GET /api/live/stream`** (Server-Sent Events). Emits periodic events containing: open positions (instrument_id, symbol, units, entry, current bid/ask/last, unrealized PnL, PnL%), account equity/cash, and a server timestamp. Cadence aligns to the monitor loop (or a short fixed interval), reusing quotes the bot already fetches — no extra eToro rate-limit pressure beyond existing polling.
- Authenticated like other endpoints (same cookie/session). A unit test asserts the event payload shape.
- Degradation: if no live source is available, the endpoint may emit periodic snapshots from the latest cached quotes.

### Frontend
- `useLiveStream()` hook opens an `EventSource` to `/api/proxy/api/live/stream` (the proxy already streams). On each event it writes into the React Query cache keyed by position/symbol so all consumers (Dashboard positions table, Positions board, Symbol detail) update without prop drilling.
- A `LiveBadge` reflects connection state: `live` / `stale` / `reconnecting`. On stream failure the hook falls back to interval polling of existing REST endpoints and the badge shows `stale`.
- Reconnect with backoff; pause when the tab is hidden to save resources.

## 8. Component Architecture (de-monolith)

Target structure under `src/`:

```
components/
  layout/        AppShell, Sidebar, Topbar, CommandPalette, ThemeToggle
  dashboard/     KpiStrip, EquityChart, AllocationDonut, ReturnsHistogram, PnlBySymbol, RecentTrades
  positions/     PositionsTable, PositionRow, LiveBadge
  trades/        TradesTable, TradeRow, TradeFilters, TradeEditDialog
  symbol/        PriceChart (lightweight-charts), SymbolHeader, SymbolTradeHistory
  reports/       ReportTree, ReportList, ReportPreview, ReportSearch
  admin/         EnvForm, BrokerPanel, PromptsEditor, UsersPanel
  ops/           JobsPanel, LogStream
  ui/            existing shadcn primitives (+ Command, Skeleton, Tooltip as needed)
hooks/
  useLiveStream, useMetrics, useTrades, usePositions, useReports, useTheme
lib/
  api.ts, auth.tsx, format.ts (tabular/monospace + FX currency), types.ts (eToro-only), query-keys.ts
```

Principles: each component has one clear purpose, a typed props interface, and is testable in isolation. Pages become thin compositions of these components. Files that grow large get split.

## 9. Visual System

- **Tokens:** dark-first palette — near-black surfaces (`#0b0e14` bg, `#121722` cards), `#1f2632` borders, `#dfe6ee` text, `#6b7484` muted; semantic `profit` (eToro green `#22d37f`), `loss` (`#f06868`), `info` (`#58a6ff`). Light theme mirrors the same token names.
- **Density:** compact spacing scale; **monospace tabular numerals** for all prices/PnL/quantities (consistent column alignment); sans-serif for labels/UI.
- **Cards:** rounded (`~10px`), 1px subtle border, no heavy shadows. Clear section headers with a small muted label + value hierarchy.
- **Motion:** minimal — subtle value-flash on live tick (green/red), skeleton shimmer on load.

## 10. States, Resilience, Accessibility

- Every data surface has explicit **loading (skeleton)**, **empty**, and **error (with retry)** states.
- FX-unavailable badge preserved (display currency conversion may be stale/unavailable).
- Auth: unchanged — cookie via same-origin proxy; 401 → `/login?next=`.
- **A11y:** ARIA labels on icon-only buttons, dialog focus trap + restore, keyboard-navigable command palette and tables, visible focus rings, color choices checked for contrast (don't rely on color alone for profit/loss — also sign/arrow).
- **Responsive:** desktop-first dense grid; sidebar collapses to a drawer; wide tables scroll horizontally with a sticky first column; charts reflow.

## 11. Testing Strategy

- **Vitest + React Testing Library** (new): unit/component tests for `useLiveStream` (event → cache, reconnect, fallback), `format.ts`, `KpiStrip`, `PositionsTable`, `TradeEditDialog`, `CommandPalette`.
- **Type-check + lint** gate (`tsc --noEmit`, eslint).
- **Backend:** one unit test for `/api/live/stream` payload shape (in the Python test suite).
- Manual smoke against a running backend (demo account) before merge.

## 12. Build Sequence (each plan shippable)

1. **Foundation** — design tokens + theme (next-themes), eToro-only `types.ts`/provider cleanup, new layout shell (Sidebar/Topbar) and consolidated routing with redirects. No feature loss.
2. **Component extraction** — split Dashboard, Trades (ex-Orders), Reports, Admin (ex-Settings/Prompts), Ops (ex-Console/Logs) into the component tree above; behavior preserved, visuals updated to the new system.
3. **Live-data layer** — backend `/api/live/stream` + `useLiveStream` + `LiveBadge`; wire Dashboard positions to live ticks.
4. **New views** — Positions board, Symbol/Position detail (with lightweight-charts), ⌘K command palette.
5. **Trading-grade charts** — candlestick + entry/TP/SL overlays on detail; polish analytics charts (Recharts) to the new tokens.
6. **Polish** — accessibility pass, responsive pass, loading/empty/error states everywhere, Vitest tests, README/env docs.

## 13. Risks & Open Questions

- **Live source fidelity:** the cleanest backend tap-point for live quotes/PnL is confirmed during Plan 3 (reuse monitor-loop data vs. a dedicated poller). Fallback snapshot path keeps the UI functional regardless.
- **Backend API shapes:** exact `/api/settings`, `/api/prompts`, `/api/trades` field names are verified against code before edits (Section 6 note).
- **Italian locale:** current UI is IT-localized; the rework keeps IT formatting unless told otherwise (no i18n framework introduced).
- **Scope:** ~6 plans including one small backend addition; large but decomposed and individually shippable.
