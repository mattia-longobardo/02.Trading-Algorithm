# Frontend Rework — Plan 2: eToro-only cleanup, IA consolidation & component extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax. Because this plan refactors several 300–530 line page files, task descriptions point the implementer at exact files + line ranges (from the Plan-2 inventory) rather than inlining full file bodies; the implementer reads the file, then applies the change. Keep the build green (`npm run typecheck` + `npm run build`) and tests passing after every task.

**Goal:** Remove all multi-provider/Alpaca scaffolding (the backend is eToro-only), consolidate the 8-page nav into the target IA with redirects, and break the monolith page files into focused, token-styled components — with no loss of functionality.

**Architecture:** First collapse the type layer to eToro-only and purge every provider selector/tab/filter/badge (one build-green task). Then restructure routing to the consolidated IA (Dashboard · Positions · Trades · Universe · Reports · Ops · Admin) with redirects from old paths. Then extract each large page into components under `src/components/<area>/`, restyling residual `slate-*` to the semantic tokens introduced in Plan 1. Behavior is preserved; only structure, provider-removal, and styling change.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript strict, Tailwind 4 (semantic tokens), React Query, Recharts, Vitest.

> All paths relative to `frontend/`. The Plan-2 inventory (in the controller's context) lists every `alpaca`/provider reference with file:line.

---

### Task 1: Collapse types to eToro-only and purge provider scaffolding (build-green)

**Files (modify):** `src/lib/types.ts`, `src/lib/use-providers.ts`, `src/app/page.tsx`, `src/app/orders/page.tsx`, `src/app/universe/page.tsx`, `src/app/prompts/page.tsx`, `src/app/settings/page.tsx`. **Test:** `src/lib/__tests__/types.test.ts` (new, light).

**Backend alignment (do FIRST):** Read the backend JSON shapes so the frontend types match reality:
- `backend/api/api_server.py` (and any serializer it calls) for the `/api/trades` item fields, `/api/settings` value keys, `/api/prompts` keys, and the `/api/providers` response.
- Confirm whether `/api/providers` still exists and what it returns now that the backend is eToro-only. If it returns a single eToro descriptor, keep a minimal typed shape; if it's gone, remove `useProviders` usage accordingly.
- Confirm the trade record fields (the backend schema dropped `alpaca_order_id` and added `instrument_id`, `position_id`, `order_reference_id`). Align the `Trade` interface to the actual serialized field names.

**Changes:**
- [ ] **Step 1 — `types.ts`:** Remove `Provider`, `ALL_PROVIDERS`, `PROVIDER_LABELS`, `ProviderDescriptor`, `ProvidersResponse`, `AllocationProvider`. In `Trade`, remove `provider` and `alpaca_order_id`; add the real eToro fields confirmed above (`instrument_id: number | null`, `position_id: string | null`, `order_reference_id: string | null` — adjust names to match the backend). Remove `provider?`/`providers?` from `Metrics`, `PnlBySymbolRow`, `AllocationSymbol`, `SettingsResponse.active_providers`. Collapse `AlpacaPromptKey`/`ALPACA_PROMPT_KEYS` into a single `PromptKey` union + `PROMPT_KEYS` array (keep the same 8 key strings; just drop the "Alpaca" naming layer).
- [ ] **Step 2 — `use-providers.ts`:** Either delete the hook (if `/api/providers` is gone) or simplify it to an eToro-only constant with no `alpaca`/`Provider` references. If deleted, remove its imports everywhere.
- [ ] **Step 3 — `src/app/page.tsx` (Dashboard):** Remove provider badges (lines ~189–192), the multi-provider allocation card (~368–389), and the `useProviders` no-broker guard's Alpaca copy (~147–175 → either drop the guard or reword generically without "Alpaca"). Remove `AllocationProvider`/`Provider`/`PROVIDER_LABELS` imports and `by_provider` handling.
- [ ] **Step 4 — `src/app/orders/page.tsx`:** Remove `PROVIDERS` const (~38), `providerFilter` state (~98), the client-side provider filter (~117–123), the Broker filter dropdown (~183–200), and the provider column/label (~333–334). Remove provider imports.
- [ ] **Step 5 — `src/app/universe/page.tsx`:** Remove provider tabs (~95–114) and render the single eToro universe directly (keep the per-category STOCK/CRYPTO sections, drop the provider dimension). Replace `PROVIDER_CATEGORIES` with a plain `CATEGORIES: Category[] = ["STOCK","CRYPTO"]`. Remove the "Alpaca" no-config copy (~64–76) and all `PROVIDER_LABELS` usages (reword headings to drop the broker name, e.g. "Aggiungi simbolo" / "Universe · {category}").
- [ ] **Step 6 — `src/app/prompts/page.tsx`:** Remove provider tabs (~94–107) and `KEYS_BY_PROVIDER`; render the single prompt section directly using `PROMPT_KEYS`. Remove `PROVIDER_LABELS`/`Provider` usages; keep `PROMPT_LABELS`.
- [ ] **Step 7 — `src/app/settings/page.tsx`:** Rename the "Alpaca" tab/section to "eToro"; replace `ALPACA_SECRET_FIELDS` with eToro secret fields (`openai_api_key`, `etoro_api_key`, `etoro_user_key` — confirm against backend `/api/settings`/secrets). Drop Alpaca-only numeric setting fields that no longer exist in `/api/settings` (verify which keys the backend still returns; keep the ones it does, reword hints to drop "Alpaca"). `BrokerTab` becomes eToro-only (no `provider` prop).
- [ ] **Step 8 — light types test** `src/lib/__tests__/types.test.ts`: assert `PROMPT_KEYS` has the expected 8 keys and contains no provider concept. Example:
```ts
import { describe, it, expect } from "vitest";
import { PROMPT_KEYS } from "@/lib/types";

describe("PROMPT_KEYS", () => {
  it("lists the eight prompt keys", () => {
    expect(PROMPT_KEYS).toHaveLength(8);
    expect(PROMPT_KEYS).toContain("new_signal");
  });
});
```
- [ ] **Step 9 — Verify:** `grep -rni "alpaca" src/` → only non-provider hits allowed (ideally none). `grep -rn "Provider" src/` → none referencing the removed types. Run `npm test`, `npm run typecheck`, `npm run build` → all green.
- [ ] **Step 10 — Commit:** `feat(frontend): remove multi-provider/Alpaca scaffolding (eToro-only)`

---

### Task 2: Consolidate IA — routes, redirects, nav

**Files:** create `src/app/positions/page.tsx` (placeholder), move/rename routes, add redirects, update `src/components/layout/nav-items.ts`.

The target nav (7 items): Dashboard `/` · Positions `/positions` · Trades `/trades` · Universe `/universe` · Reports `/reports` · Ops `/ops` · Admin `/admin`. Symbol detail (`/symbol/[id]`) and ⌘K come in Plan 4.

- [ ] **Step 1 — Trades:** Rename route `src/app/orders/` → `src/app/trades/` (git mv the folder; update the page's own internal links/labels from "Ordini" wording if needed). Add `src/app/orders/page.tsx` that redirects to `/trades` (`import { redirect } from "next/navigation"; export default function() { redirect("/trades"); }`).
- [ ] **Step 2 — Ops (merge Console + Logs):** Create `src/app/ops/page.tsx` that renders the Console job panel and the Logs stream as two sections/tabs (reuse the existing console + logs page bodies — extract them into `src/components/ops/JobsPanel.tsx` and `src/components/ops/LogStream.tsx` and compose both in `/ops`). Add redirects at `src/app/console/page.tsx` and `src/app/logs/page.tsx` → `/ops`.
- [ ] **Step 3 — Admin (merge Settings + Prompts + Users):** Create `src/app/admin/page.tsx` with tabs: Environment, eToro (broker), Prompts (admin-only), Users. Reuse the existing settings tab components + the prompts body (extracted into `src/components/admin/`). Add redirects at `src/app/settings/page.tsx` and `src/app/prompts/page.tsx` → `/admin`.
- [ ] **Step 4 — Positions placeholder:** Create `src/app/positions/page.tsx` rendering a titled empty state ("Posizioni — in arrivo") so the nav target exists; the live board is built in Plan 4.
- [ ] **Step 5 — Nav:** Update `nav-items.ts` to the 7-item structure with new hrefs/labels/icons (Dashboard=LineChart, Positions=Activity, Trades=ClipboardList, Universe=Globe, Reports=FileText, Ops=Terminal, Admin=Settings; Prompts no longer a top-level item — it lives under Admin, which is visible to all but gates the Prompts tab to admins). Update `nav-items.test.ts` expectations accordingly. Update `auth.tsx` post-login redirect target if it referenced a removed route (it targets `/`, fine).
- [ ] **Step 6 — Verify:** `npm test`, `npm run typecheck`, `npm run build`. Manually confirm each old route redirects (build output lists the routes). Commit: `feat(frontend): consolidate navigation IA with redirects`

---

### Task 3: Extract the Dashboard into components

**Files:** create under `src/components/dashboard/`; slim `src/app/page.tsx` to a composition. **Test:** one component test (e.g. `KpiStrip`).

- [ ] **Step 1:** Read `src/app/page.tsx`. Extract: `KpiStrip` (the KPI grid + the inline `Kpi`), `CategoryAllocationChart` (donut + `AllocationLegend`), `PnlBySymbolChart`, `ReturnsDistributionChart`. Keep `EquityBalanceChart` import. Each component takes typed props (its data + loading/error) — the page owns the React Query calls and passes data down, OR each component owns its own query (follow whichever keeps the page thin; prefer page-owns-queries, components are presentational). Apply `.tnum` to KPI numbers and restyle any `slate-*` to tokens.
- [ ] **Step 2:** Slim `page.tsx` to compose the components + header + timeframe selector + `useDashboardAutoRefresh`.
- [ ] **Step 3:** Add `src/components/dashboard/__tests__/kpi-strip.test.tsx` rendering `KpiStrip` with sample metrics and asserting a couple of formatted values appear.
- [ ] **Step 4:** `npm test`, `npm run typecheck`, `npm run build`. Commit: `refactor(frontend): extract dashboard into components`

---

### Task 4: Extract Trades (ex-Orders) into components

**Files:** create under `src/components/trades/`; slim `src/app/trades/page.tsx`.

- [ ] **Step 1:** Read `src/app/trades/page.tsx`. Extract `TradesFilters` (status/category/symbol — provider already removed), `TradesTable` + `TradeRow`, `EditTradeDialog`, `CloseTradeDialog`. Page owns queries/mutations and passes handlers down. Apply `.tnum` to price/PnL cells; make the table horizontally scrollable with a sticky first column for responsiveness; restyle `slate-*`.
- [ ] **Step 2:** Slim the page to compose them.
- [ ] **Step 3:** Add a component test for `TradeRow` (renders a sample trade's symbol + formatted PnL with profit/loss color).
- [ ] **Step 4:** `npm test`, `npm run typecheck`, `npm run build`. Commit: `refactor(frontend): extract trades page into components`

---

### Task 5: Extract Admin (Settings + Prompts + Users) and Ops bodies

**Files:** `src/components/admin/` (`EnvForm`, `BrokerPanel`, `PromptsEditor` + `PromptKeyList` + `PromptHistory`, `UsersPanel`), `src/components/ops/` (`JobsPanel`, `LogStream`). Slim `src/app/admin/page.tsx` and `src/app/ops/page.tsx` (created in Task 2 — here they become thin compositions of extracted components).

- [ ] **Step 1:** Read `src/app/settings/page.tsx` + `src/app/prompts/page.tsx` + `src/app/console/page.tsx` + `src/app/logs/page.tsx` bodies (pre-redirect content, now living in the new `/admin` and `/ops` pages from Task 2). Extract the inline tab functions/sections into the named components above. Preserve all mutations (settings update, prompt save/rollback, user create/update, password change, job triggers) and the SSE log stream logic.
- [ ] **Step 2:** Compose them in `/admin` (tabs) and `/ops` (two sections). Gate the Prompts tab + Users management + job triggers to `role === "admin"` exactly as before. Restyle `slate-*`.
- [ ] **Step 3:** Add a component test for one extracted unit (e.g. `EnvForm` renders fields from a sample settings payload).
- [ ] **Step 4:** `npm test`, `npm run typecheck`, `npm run build`. Commit: `refactor(frontend): extract admin and ops into components`

---

### Task 6: Extract Reports into components

**Files:** `src/components/reports/` (`ReportFolderTree`, `ReportsList`, `ReportSearch`, `ReportPreview`); slim `src/app/reports/page.tsx`.

- [ ] **Step 1:** Read `src/app/reports/page.tsx`. Extract the folder tree, the searchable list, the search/filter bar, and the preview modal. Preserve search, folder move (`PATCH`), folder create/delete, and PDF(iframe)/JSON preview. Restyle `slate-*`.
- [ ] **Step 2:** Slim the page to compose them.
- [ ] **Step 3:** `npm test`, `npm run typecheck`, `npm run build`. Commit: `refactor(frontend): extract reports page into components`

---

## Self-Review

**Spec coverage (Plan 2 slice of the design spec):** eToro-only simplification (spec §6) → Task 1. IA consolidation (spec §5) → Task 2. Component de-monolith (spec §8) → Tasks 3–6. Token restyle of pages (spec §9) → folded into each extraction task. Deferred: live data → Plan 3; new views (Positions board, Symbol detail, ⌘K) → Plan 4; trading charts → Plan 5; a11y/responsive/states/tests polish → Plan 6.

**Placeholder scan:** Task descriptions reference exact files + inventory line numbers; the implementer reads each file before editing (necessary for 300–530-line refactors). Backend field names are verified in Task 1 before the type edits. No "TBD".

**Type/name consistency:** `PromptKey`/`PROMPT_KEYS` (Task 1) consumed by the prompts extraction (Task 5). `Trade` field renames (Task 1) consumed by `TradesTable`/`TradeRow` (Task 4). New routes `/trades`,`/ops`,`/admin`,`/positions` (Task 2) referenced by `nav-items.ts` and redirects.

**Notes for the executor:**
- Keep each task build-green; if a type change in Task 1 leaves a consumer broken, fix it within Task 1 (it's the build-green task).
- Prefer git `mv` for the orders→trades route rename to preserve history.
- Do NOT introduce the live stream or new views here — those are later plans.
- Italian UI copy is preserved (reworded only to drop broker names).
