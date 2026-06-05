"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

export function ThemeToggle({ className }: { className?: string }) {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const baseClass = cn(
    "grid size-9 place-items-center rounded-lg border border-(--color-line) bg-(--color-panel) text-(--color-muted) transition-colors hover:text-(--color-text) focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent)",
    className
  );

  // Before mount the resolved theme is unknown. Render an inert placeholder
  // so the button's aria-label never advertises the wrong action during the
  // SSR/pre-hydration window — and so the tests only pass once next-themes
  // has actually resolved the theme, not via a pre-mount default.
  if (!mounted) {
    return <span aria-hidden="true" className={baseClass} />;
  }

  const isDark = resolvedTheme !== "light";
  const label = isDark ? "Attiva tema chiaro" : "Attiva tema scuro";

  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setTheme(isDark ? "light" : "dark")}
      className={baseClass}
    >
      {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}
