"use client";

import {
  Activity,
  FileText,
  Globe,
  LineChart,
  LogOut,
  Settings,
  Sparkles,
  Terminal,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
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

  if (pathname === "/login") {
    return <>{children}</>;
  }

  if (!user) {
    // The AuthProvider handles redirect; render nothing while it works.
    return null;
  }

  const items = NAV.filter((item) => !item.adminOnly || user.role === "admin");

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 flex-col border-r border-(--color-line) bg-(--color-panel)/70 px-4 py-6">
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
                className={cn(
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                  active
                    ? "bg-slate-800 text-(--color-text)"
                    : "text-(--color-muted) hover:bg-slate-800/60 hover:text-(--color-text)"
                )}
              >
                <Icon className="size-4" />
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
      </aside>

      <main className="flex-1 overflow-x-hidden">
        <div className="mx-auto w-full max-w-7xl px-8 py-8">{children}</div>
      </main>
    </div>
  );
}
