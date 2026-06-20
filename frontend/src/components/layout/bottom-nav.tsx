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

  useEffect(() => {
    setSheetOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!sheetOpen) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setSheetOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = original;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [sheetOpen]);

  const cell =
    "flex flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-[11px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) focus-visible:ring-offset-2 focus-visible:ring-offset-(--color-bg)";

  return (
    <>
      {sheetOpen && (
        <div id="bottom-nav-altro-sheet" className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Altro">
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
        className="pb-safe h-bottom-nav z-40 flex shrink-0 border-t border-(--color-line) bg-(--color-bg)/95 backdrop-blur lg:hidden"
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
          aria-expanded={sheetOpen}
          aria-controls="bottom-nav-altro-sheet"
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
