"use client";

import { Command } from "cmdk";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import { useAuth } from "@/lib/auth";
import { visibleNavFor } from "@/components/layout/nav-items";

interface CommandPaletteProps {
  /** Controlled open state lifted from the parent shell. */
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const router = useRouter();
  const { user } = useAuth();
  const { resolvedTheme, setTheme } = useTheme();
  const [input, setInput] = useState("");

  // Global ⌘K / Ctrl-K listener.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(true);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onOpenChange]);

  // Reset input on close.
  useEffect(() => {
    if (!open) setInput("");
  }, [open]);

  function navigate(href: string) {
    router.push(href);
    onOpenChange(false);
  }

  function toggleTheme() {
    setTheme(resolvedTheme === "light" ? "dark" : "light");
    onOpenChange(false);
  }

  const navItems = user ? visibleNavFor(user.role) : [];

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        {/* Overlay */}
        <DialogPrimitive.Overlay className="fixed inset-0 z-[99] bg-black/60 backdrop-blur-sm data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />

        {/* Panel */}
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed left-1/2 top-[15vh] z-[100] w-full max-w-xl -translate-x-1/2 overflow-hidden rounded-2xl border border-(--color-line) bg-(--color-panel) shadow-2xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
        >
          {/* Accessible title — visually hidden */}
          <VisuallyHidden.Root asChild>
            <DialogPrimitive.Title>Palette dei comandi</DialogPrimitive.Title>
          </VisuallyHidden.Root>

          <Command>
            <Command.Input
              value={input}
              onValueChange={setInput}
              placeholder="Cerca comandi o simboli…"
              aria-label="Cerca comandi"
              autoFocus
              className="w-full border-b border-(--color-line) bg-transparent px-4 py-3 text-sm text-(--color-text) placeholder:text-(--color-muted) focus:outline-none"
            />

            <Command.List className="max-h-80 overflow-y-auto p-2">
              <Command.Empty className="py-6 text-center text-sm text-(--color-muted)">
                Nessun risultato trovato.
              </Command.Empty>

              {/* Navigation commands */}
              <Command.Group
                heading="Navigazione"
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-(--color-muted)"
              >
                {navItems.map((item) => {
                  const Icon = item.icon;
                  return (
                    <Command.Item
                      key={item.href}
                      value={item.label}
                      onSelect={() => navigate(item.href)}
                      className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-(--color-text) aria-selected:bg-(--color-hover) data-[selected=true]:bg-(--color-hover)"
                    >
                      <Icon className="size-4 shrink-0 text-(--color-muted)" />
                      {item.label}
                    </Command.Item>
                  );
                })}
              </Command.Group>

              {/* Dynamic symbol navigation — shown only when there is input */}
              {input.trim().length > 0 && (
                <Command.Group
                  heading="Simboli"
                  className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-(--color-muted)"
                >
                  <Command.Item
                    value={`vai al simbolo ${input.trim()}`}
                    onSelect={() =>
                      navigate(`/symbol/${encodeURIComponent(input.trim().toUpperCase())}`)
                    }
                    className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-(--color-text) aria-selected:bg-(--color-hover) data-[selected=true]:bg-(--color-hover)"
                  >
                    <span className="font-mono font-bold text-(--color-accent)">→</span>
                    Vai al simbolo:{" "}
                    <span className="font-semibold">{input.trim().toUpperCase()}</span>
                  </Command.Item>
                </Command.Group>
              )}

              {/* Theme toggle */}
              <Command.Group
                heading="Impostazioni"
                className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wide [&_[cmdk-group-heading]]:text-(--color-muted)"
              >
                <Command.Item
                  value="cambia tema chiaro scuro"
                  onSelect={toggleTheme}
                  className="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-(--color-text) aria-selected:bg-(--color-hover) data-[selected=true]:bg-(--color-hover)"
                >
                  <span className="size-4 shrink-0 text-center leading-none text-(--color-muted)">
                    ◑
                  </span>
                  Cambia tema (chiaro/scuro)
                </Command.Item>
              </Command.Group>
            </Command.List>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
