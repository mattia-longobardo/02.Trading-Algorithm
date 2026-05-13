"use client";

import {
  Activity,
  ClipboardList,
  FileText,
  Globe,
  LineChart,
  LogOut,
  Menu,
  Settings,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { cn } from "@/lib/cn";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  adminOnly?: boolean;
}

const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LineChart },
  { href: "/orders", label: "Ordini", icon: ClipboardList },
  { href: "/console", label: "Console", icon: Terminal },
  { href: "/universe", label: "Universe", icon: Globe },
  { href: "/reports", label: "Report", icon: FileText },
  { href: "/prompts", label: "Prompt", icon: Sparkles, adminOnly: true },
  { href: "/logs", label: "Log", icon: Activity },
  { href: "/settings", label: "Impostazioni", icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Lock body scroll while the mobile drawer is open so the user can't
  // scroll the page behind the panel.
  useEffect(() => {
    if (!mobileOpen) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = original;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [mobileOpen]);

  if (pathname === "/login") {
    return <>{children}</>;
  }

  if (!user) {
    // The AuthProvider handles redirect; render nothing while it works.
    return null;
  }

  const items = NAV.filter((item) => !item.adminOnly || user.role === "admin");

  const sidebarContent = (
    <>
      <div className="mb-6 flex items-center gap-2">
        <div className="size-8 rounded-lg bg-(--color-accent) grid place-items-center text-slate-950 font-bold">
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
                "relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--color-bg)",
                active
                  ? "bg-slate-800 text-(--color-text) before:absolute before:left-0 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r before:bg-(--color-accent)"
                  : "text-(--color-muted) hover:bg-slate-800/60 hover:text-(--color-text)"
              )}
            >
              <Icon className={cn("size-4", active && "text-(--color-accent)")} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto space-y-3 pt-6">
        <div className="rounded-lg border border-(--color-line) bg-slate-950/40 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="truncate text-sm font-medium" title={user.display_name}>
              {user.display_name}
            </p>
            <Badge variant={user.role === "admin" ? "admin" : "user"}>{user.role}</Badge>
          </div>
          <p className="mt-1 truncate text-xs text-(--color-muted)" title={user.username}>
            @{user.username}
          </p>
        </div>
        <Button variant="secondary" size="sm" className="w-full" onClick={logout}>
          <LogOut className="size-4" />
          Logout
        </Button>
      </div>
    </>
  );

  return (
    <div className="flex min-h-screen">
      {/* Desktop sidebar: always visible from lg breakpoint up. */}
      <aside className="hidden w-60 flex-col border-r border-(--color-line) bg-(--color-panel)/70 px-4 py-6 lg:flex">
        {sidebarContent}
      </aside>

      {/* Mobile drawer overlay + sliding sidebar. Mounted only when open
          so the focus trap and body-scroll lock effects don't run when not
          needed. The drawer slides in from the left and animates the
          backdrop fade. */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label="Chiudi menu"
            onClick={() => setMobileOpen(false)}
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col border-r border-(--color-line) bg-(--color-panel) px-4 py-6 shadow-2xl">
            <button
              type="button"
              aria-label="Chiudi menu"
              onClick={() => setMobileOpen(false)}
              className="absolute right-3 top-3 rounded-md p-1.5 text-(--color-muted) transition-colors hover:bg-slate-800 hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--color-panel)"
            >
              <X className="size-4" />
            </button>
            {sidebarContent}
          </aside>
        </div>
      )}

      <main className="flex-1 overflow-x-hidden">
        {/* Mobile top bar: hamburger + brand. Hidden on lg+. */}
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-(--color-line) bg-(--color-bg)/95 px-4 backdrop-blur lg:hidden">
          <button
            type="button"
            aria-label="Apri menu"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(true)}
            className="rounded-md p-1.5 text-(--color-text) transition-colors hover:bg-slate-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--color-bg)"
          >
            <Menu className="size-5" />
          </button>
          <div className="flex items-center gap-2">
            <div className="size-6 rounded bg-(--color-accent) grid place-items-center text-slate-950 text-xs font-bold">
              T
            </div>
            <p className="text-sm font-semibold">Trading Console</p>
          </div>
        </header>
        <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          {children}
        </div>
      </main>
    </div>
  );
}
