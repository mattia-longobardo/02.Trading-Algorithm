# Frontend Rework — Plan 1: Foundation (test infra, theme system, shell) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the foundation for the frontend rework — a Vitest test harness, a dark-first design-token theme system with a light toggle, and a restyled app shell — without changing routes or behavior.

**Architecture:** Add Vitest + React Testing Library for component TDD. Replace the ad-hoc CSS variables with a semantic token palette defined for dark (default) and light themes, switched at runtime by `next-themes` via a class on `<html>`; existing `bg-(--color-*)` utilities pick up the runtime values automatically. Extract the nav definition into a pure, testable module and restyle the existing `AppShell` to the new tokens, adding a theme toggle. The 8 current routes and all behavior are preserved.

**Tech Stack:** Next.js 15 (App Router), React 19, TypeScript (strict), Tailwind 4, next-themes, Vitest, @testing-library/react, lucide-react.

> All paths below are relative to `frontend/`. Run all commands from `frontend/`.

---

### Task 1: Vitest + React Testing Library test infrastructure

**Files:**
- Modify: `package.json` (devDependencies + scripts)
- Create: `vitest.config.ts`
- Create: `vitest.setup.ts`
- Test: `src/lib/__tests__/cn.test.ts`

- [ ] **Step 1: Add dev dependencies and test scripts to `package.json`**

In the `"scripts"` object, add:

```json
    "test": "vitest run",
    "test:watch": "vitest"
```

In `"devDependencies"`, add these entries (keep the existing ones):

```json
    "@testing-library/jest-dom": "^6.6.3",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^25.0.1",
    "vitest": "^2.1.8"
```

- [ ] **Step 2: Install**

Run: `npm install`
Expected: completes without peer-dependency errors; `node_modules/.bin/vitest` exists.

- [ ] **Step 3: Create `vitest.config.ts`**

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
  },
});
```

- [ ] **Step 4: Create `vitest.setup.ts`**

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
```

- [ ] **Step 5: Write the first test — `src/lib/__tests__/cn.test.ts`**

This exercises the existing `cn` helper (`src/lib/cn.ts`, which composes `clsx` + `tailwind-merge`).

```ts
import { describe, it, expect } from "vitest";
import { cn } from "@/lib/cn";

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("a", "b")).toBe("a b");
  });

  it("resolves conflicting tailwind classes so the last wins", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });

  it("drops falsy values", () => {
    expect(cn("a", false && "b", undefined, null, "c")).toBe("a c");
  });
});
```

- [ ] **Step 6: Run the test**

Run: `npm test`
Expected: PASS — 1 file, 3 tests passing. (This confirms jsdom, the `@` alias, and the setup file all work.)

- [ ] **Step 7: Commit**

```bash
git add package.json package-lock.json vitest.config.ts vitest.setup.ts src/lib/__tests__/cn.test.ts
git commit -m "test(frontend): add Vitest + React Testing Library harness"
```

---

### Task 2: Design-token theme system (dark default + light toggle)

**Files:**
- Modify: `src/app/globals.css`
- Create: `src/components/layout/theme-provider.tsx`
- Modify: `src/lib/providers.tsx`
- Modify: `src/app/layout.tsx`
- Create: `src/components/layout/theme-toggle.tsx`
- Test: `src/components/layout/__tests__/theme-toggle.test.tsx`

- [ ] **Step 1: Add `next-themes` dependency**

In `package.json` `"dependencies"`, add:

```json
    "next-themes": "^0.4.4"
```

Run: `npm install`
Expected: installs cleanly.

- [ ] **Step 2: Rework `src/app/globals.css` with the new token palette**

Replace the **entire** file contents with:

```css
@import "tailwindcss";

/* Dark is the default theme. Tokens are declared in @theme so Tailwind
   generates the `*-(--color-*)` utilities, with dark values as the base. */
@theme {
  --color-bg: #0b0e14;
  --color-elevated: #0c1018;
  --color-panel: #121722;
  --color-line: #1f2632;
  --color-text: #dfe6ee;
  --color-muted: #6b7484;
  --color-accent: #22d37f;
  --color-danger: #f06868;
  --color-warning: #f59e0b;
  --color-info: #58a6ff;
}

/* Light theme overrides. next-themes sets `class="light"` on <html>;
   re-declaring the same CSS variables in that scope flips every
   `*-(--color-*)` utility at runtime without rebuilding. */
:root.light {
  --color-bg: #f6f7f9;
  --color-elevated: #ffffff;
  --color-panel: #ffffff;
  --color-line: #e4e7ec;
  --color-text: #1a1f29;
  --color-muted: #6b7484;
  --color-accent: #12a150;
  --color-danger: #e5484d;
  --color-warning: #d98300;
  --color-info: #2f6feb;
}

html,
body {
  background: var(--color-bg);
  color: var(--color-text);
  min-height: 100vh;
}

* {
  border-color: var(--color-line);
}

/* Tabular, monospace numerals for prices/PnL/quantities so columns align.
   Apply with the `.tnum` class on numeric cells. */
.tnum {
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

/* Hide arrows on number inputs in WebKit / Firefox so the trade editor
   stays clean — operators paste / type values, no need for spinners. */
input[type="number"]::-webkit-inner-spin-button,
input[type="number"]::-webkit-outer-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
input[type="number"] {
  -moz-appearance: textfield;
}
```

- [ ] **Step 3: Create `src/components/layout/theme-provider.tsx`**

```tsx
"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="dark"
      enableSystem={false}
      disableTransitionOnChange
    >
      {children}
    </NextThemesProvider>
  );
}
```

- [ ] **Step 4: Wrap the app with `ThemeProvider` in `src/lib/providers.tsx`**

Add the import at the top (after the existing imports):

```tsx
import { ThemeProvider } from "@/components/layout/theme-provider";
```

Change the returned JSX so `ThemeProvider` is the outermost wrapper:

```tsx
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
```

- [ ] **Step 5: Add `suppressHydrationWarning` to `<html>` in `src/app/layout.tsx`**

next-themes sets the class on `<html>` before React hydrates, so the server/client markup differ by design. Change the opening tag:

```tsx
    <html lang="it" suppressHydrationWarning>
```

- [ ] **Step 6: Write the failing test — `src/components/layout/__tests__/theme-toggle.test.tsx`**

```tsx
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
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `npx vitest run src/components/layout/__tests__/theme-toggle.test.tsx`
Expected: FAIL — cannot resolve `@/components/layout/theme-toggle` (not created yet).

- [ ] **Step 8: Create `src/components/layout/theme-toggle.tsx`**

Uses a native `<button>` (not the CVA Button) so it has no dependency on specific button variants. The mount guard avoids a hydration mismatch on the icon.

```tsx
"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const isDark = resolvedTheme !== "light";
  const label = isDark ? "Attiva tema chiaro" : "Attiva tema scuro";

  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={cn(
        "grid size-9 place-items-center rounded-lg border border-(--color-line) bg-(--color-panel) text-(--color-muted) transition-colors hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)",
        className
      )}
    >
      {mounted ? (
        isDark ? <Sun className="size-4" /> : <Moon className="size-4" />
      ) : (
        <span className="size-4" />
      )}
    </button>
  );
}
```

- [ ] **Step 9: Run the test to verify it passes**

Run: `npx vitest run src/components/layout/__tests__/theme-toggle.test.tsx`
Expected: PASS — 2 tests.

- [ ] **Step 10: Verify type-check and build still pass**

Run: `npm run typecheck`
Expected: no errors.

- [ ] **Step 11: Commit**

```bash
git add package.json package-lock.json src/app/globals.css src/lib/providers.tsx src/app/layout.tsx src/components/layout/theme-provider.tsx src/components/layout/theme-toggle.tsx src/components/layout/__tests__/theme-toggle.test.tsx
git commit -m "feat(frontend): dark-first design tokens + next-themes light toggle"
```

---

### Task 3: Extract nav definition and restyle the app shell

**Files:**
- Create: `src/components/layout/nav-items.ts`
- Test: `src/components/layout/__tests__/nav-items.test.ts`
- Modify: `src/components/app-shell.tsx`

> Routes are unchanged in this plan (8 current routes, Italian labels). Route consolidation happens in Plan 2.

- [ ] **Step 1: Write the failing test — `src/components/layout/__tests__/nav-items.test.ts`**

```ts
import { describe, it, expect } from "vitest";
import { NAV, visibleNavFor } from "@/components/layout/nav-items";

describe("nav-items", () => {
  it("admins see every nav item", () => {
    expect(visibleNavFor("admin")).toHaveLength(NAV.length);
  });

  it("users do not see admin-only items", () => {
    const userNav = visibleNavFor("user");
    expect(userNav.length).toBeLessThan(NAV.length);
    expect(userNav.every((item) => !item.adminOnly)).toBe(true);
  });

  it("every item has a unique href", () => {
    const hrefs = NAV.map((item) => item.href);
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `npx vitest run src/components/layout/__tests__/nav-items.test.ts`
Expected: FAIL — cannot resolve `@/components/layout/nav-items`.

- [ ] **Step 3: Create `src/components/layout/nav-items.ts`**

```ts
import {
  Activity,
  ClipboardList,
  FileText,
  Globe,
  LineChart,
  Settings,
  Sparkles,
  Terminal,
} from "lucide-react";
import type { UserRole } from "@/lib/types";

export interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  adminOnly?: boolean;
}

export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LineChart },
  { href: "/orders", label: "Ordini", icon: ClipboardList },
  { href: "/console", label: "Console", icon: Terminal },
  { href: "/universe", label: "Universe", icon: Globe },
  { href: "/reports", label: "Report", icon: FileText },
  { href: "/prompts", label: "Prompt", icon: Sparkles, adminOnly: true },
  { href: "/logs", label: "Log", icon: Activity },
  { href: "/settings", label: "Impostazioni", icon: Settings },
];

export function visibleNavFor(role: UserRole): NavItem[] {
  return NAV.filter((item) => !item.adminOnly || role === "admin");
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/components/layout/__tests__/nav-items.test.ts`
Expected: PASS — 3 tests.

- [ ] **Step 5: Use the extracted nav in `src/components/app-shell.tsx`**

Remove the now-duplicated `NavItem` interface and `NAV` array, and the lucide icon imports that were only used by them. Specifically:

1. Replace the lucide-react import block (top of file) with only the icons the shell still uses directly:

```tsx
import { LogOut, Menu, X } from "lucide-react";
```

2. Add these imports below the existing `cn` import:

```tsx
import { NAV, visibleNavFor } from "@/components/layout/nav-items";
import { ThemeToggle } from "@/components/layout/theme-toggle";
```

3. Delete the `interface NavItem { ... }` block and the `const NAV: NavItem[] = [ ... ];` array entirely (now provided by `nav-items.ts`).

4. Replace the line:

```tsx
  const items = NAV.filter((item) => !item.adminOnly || user.role === "admin");
```

with:

```tsx
  const items = visibleNavFor(user.role);
```

- [ ] **Step 6: Add the theme toggle to the shell**

In the sidebar footer block, change the user-card row so the theme toggle sits beside it. Replace:

```tsx
      <div className="mt-auto space-y-3 pt-6">
        <div className="rounded-lg border border-(--color-line) bg-slate-950/40 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-sm font-medium" title={user.display_name}>
              {user.display_name}
            </p>
            <Badge variant={user.role === "admin" ? "admin" : "user"}>{user.role}</Badge>
          </div>
```

with:

```tsx
      <div className="mt-auto space-y-3 pt-6">
        <div className="rounded-lg border border-(--color-line) bg-(--color-elevated) p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-sm font-medium" title={user.display_name}>
              {user.display_name}
            </p>
            <div className="flex items-center gap-2">
              <ThemeToggle className="size-7" />
              <Badge variant={user.role === "admin" ? "admin" : "user"}>{user.role}</Badge>
            </div>
          </div>
```

- [ ] **Step 7: Restyle the shell surfaces to the new tokens**

Two `bg-slate-*` literals remain from the old palette. Replace them with semantic tokens so both themes work:

- In the desktop `<aside>`, change `bg-(--color-panel)/70` to `bg-(--color-elevated)`.
- In the active nav-link class, change `bg-slate-800` to `bg-(--color-panel)`, and `hover:bg-slate-800/60` to `hover:bg-(--color-panel)/60` (both the desktop and any mobile occurrence — they share the `sidebarContent` block, so this is one edit).

- [ ] **Step 8: Run tests, type-check, and build**

Run: `npm test`
Expected: PASS — all test files (cn, theme-toggle, nav-items).

Run: `npm run typecheck`
Expected: no errors.

Run: `npm run build`
Expected: build succeeds (standalone output).

- [ ] **Step 9: Commit**

```bash
git add src/components/layout/nav-items.ts src/components/layout/__tests__/nav-items.test.ts src/components/app-shell.tsx
git commit -m "feat(frontend): extract nav module, restyle shell, add theme toggle"
```

---

## Self-Review

**Spec coverage (Plan 1 slice):**
- Visual system / dark-first tokens (spec §9, §2) → Task 2 (globals.css palette + light overrides) ✓
- Theming with next-themes (spec §4) → Task 2 ✓
- Vitest + RTL test harness (spec §4, §11) → Task 1 ✓
- Restyled layout shell foundation (spec §8 layout/, §12 Plan 1) → Task 3 ✓
- Deferred to later plans (explicitly out of Plan 1 scope): eToro-only types cleanup → Plan 2; route consolidation/redirects → Plan 2; live data → Plan 3; new views → Plan 4; trading charts → Plan 5; a11y/responsive/states polish → Plan 6.

**Placeholder scan:** No TBD/TODO; every code step contains full content. ✓

**Type/name consistency:** `ThemeProvider` (theme-provider.tsx) imported in providers.tsx and the toggle test; `ThemeToggle` accepts an optional `className` (used as `size-7` in the shell and untyped-default in tests); `NAV`/`visibleNavFor` defined in nav-items.ts and consumed in app-shell.tsx + nav-items.test.ts. Token names (`--color-bg/elevated/panel/line/text/muted/accent/danger/warning/info`) are consistent between globals.css and the shell edits. ✓

**Notes for the executor:**
- `next-themes` writes `class="light"` (or removes it for dark) on `<html>`; the light test asserts that class. If `package-lock.json` is absent (CI uses a different lockfile), adjust the `git add` lines accordingly.
- The CVA `Button` variants were intentionally avoided in `ThemeToggle` to prevent referencing variants that may not exist in `src/components/ui/button.tsx`.
