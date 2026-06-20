"use client";

import { LogOut } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { cn } from "@/lib/cn";
import { visibleNavFor } from "@/components/layout/nav-items";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { CommandPalette } from "@/components/command/command-palette";
import { BottomNav } from "@/components/layout/bottom-nav";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [paletteOpen, setPaletteOpen] = useState(false);

  if (pathname === "/login") {
    return <>{children}</>;
  }

  if (!user) {
    // The AuthProvider handles redirect; render nothing while it works.
    return null;
  }

  const items = visibleNavFor(user.role);

  const sidebarContent = (
    <>
      <div className="mb-6 flex items-center gap-2">
        <div className="size-8 rounded-lg bg-(--color-accent) grid place-items-center text-(--color-accent-contrast) font-bold">
          T
        </div>
        <div>
          <p className="text-sm font-semibold leading-none">Trading</p>
          <p className="text-xs text-(--color-muted) leading-tight">Console</p>
        </div>
      </div>

      <nav className="flex flex-col gap-1">
        {items.map((item) => {
          const Icon = item.icon;
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "relative flex min-w-0 items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--color-bg)",
                active
                  ? "bg-(--color-panel) text-(--color-text) before:absolute before:left-0 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r before:bg-(--color-accent)"
                  : "text-(--color-muted) hover:bg-(--color-panel)/60 hover:text-(--color-text)"
              )}
            >
              <Icon className={cn("size-4 shrink-0", active && "text-(--color-accent)")} />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 pt-6">
        <div className="rounded-lg border border-(--color-line) bg-(--color-elevated) p-3">
          <p className="text-sm font-medium break-words" title={user.display_name}>
            {user.display_name}
          </p>
          <div className="mt-1 flex items-center justify-between gap-2">
            <p className="min-w-0 truncate text-xs text-(--color-muted)" title={user.username}>
              @{user.username}
            </p>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                aria-label="Apri palette comandi"
                title="Palette comandi (⌘K)"
                onClick={() => setPaletteOpen(true)}
                className="grid h-7 place-items-center rounded-md border border-(--color-line) bg-(--color-panel) px-1.5 text-[10px] font-mono font-semibold text-(--color-muted) transition-colors hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)"
              >
                ⌘K
              </button>
              <ThemeToggle className="size-7" />
              <Badge variant={user.role === "admin" ? "admin" : "user"}>{user.role}</Badge>
            </div>
          </div>
        </div>
        <Button variant="secondary" size="sm" className="w-full" onClick={logout}>
          <LogOut className="size-4" />
          Logout
        </Button>
      </div>
    </>
  );

  return (
    <div className="flex h-dvh min-h-dvh overflow-hidden lg:h-auto lg:min-h-screen lg:overflow-visible">
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      {/* Desktop sidebar: always visible from lg breakpoint up. */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col self-start overflow-x-hidden overflow-y-auto border-r border-(--color-line) bg-(--color-elevated) px-4 py-6 lg:flex">
        {sidebarContent}
      </aside>

      <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden lg:min-h-screen lg:overflow-visible">
        {/* Mobile top bar: brand + theme toggle + logout. Hidden on lg+. */}
        <header className="z-30 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-(--color-line) bg-(--color-bg)/95 px-4 backdrop-blur lg:hidden">
          <div className="flex min-w-0 items-center gap-2">
            <div className="size-6 rounded bg-(--color-accent) grid place-items-center text-(--color-accent-contrast) text-xs font-bold">
              T
            </div>
            <p className="truncate text-sm font-semibold">Trading Console</p>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle className="size-8" />
            <Button variant="secondary" size="sm" aria-label="Logout" onClick={logout}>
              <LogOut className="size-4" />
            </Button>
          </div>
        </header>
        <div className="mx-auto min-h-0 w-full max-w-7xl flex-1 overflow-y-auto px-4 py-6 sm:px-6 lg:flex-none lg:overflow-visible lg:px-8 lg:py-8">
          {children}
        </div>
        <BottomNav items={items} />
      </main>
    </div>
  );
}
