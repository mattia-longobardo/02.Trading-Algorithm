"use client";

import * as ToastPrimitive from "@radix-ui/react-toast";
import { CheckCircle2, Loader2, X, XCircle } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";

type ToastStatus = "loading" | "success" | "error";

interface ToastItem {
  id: string;
  status: ToastStatus;
  title: string;
  description?: string;
}

interface TrackToastOptions<T> {
  loading: string;
  success: string | ((value: T) => string);
  error: string | ((error: unknown) => string);
  description?: string | ((value: T) => string | undefined);
}

interface ToastContextValue {
  show: (item: Omit<ToastItem, "id">) => string;
  update: (id: string, patch: Partial<Omit<ToastItem, "id">>) => void;
  dismiss: (id: string) => void;
  track: <T>(promise: Promise<T>, options: TrackToastOptions<T>) => Promise<T>;
}

const ToastContext = createContext<ToastContextValue | null>(null);
const LONG_RUNNING_TOAST_DURATION_MS = 24 * 60 * 60 * 1000;

function toastMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Operazione non riuscita";
}

export function AppToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counter = useRef(0);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  useEffect(
    () => () => {
      for (const timer of timers.current.values()) {
        clearTimeout(timer);
      }
      timers.current.clear();
    },
    [],
  );

  const dismiss = useCallback((id: string) => {
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer);
    timers.current.delete(id);
    setItems((current) => current.filter((item) => item.id !== id));
  }, []);

  const scheduleDismiss = useCallback(
    (id: string, delay: number) => {
      const existing = timers.current.get(id);
      if (existing) clearTimeout(existing);
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), delay),
      );
    },
    [dismiss],
  );

  const show = useCallback((item: Omit<ToastItem, "id">) => {
    const id = `toast-${Date.now()}-${counter.current++}`;
    setItems((current) => [...current, { id, ...item }]);
    return id;
  }, []);

  const update = useCallback((id: string, patch: Partial<Omit<ToastItem, "id">>) => {
    setItems((current) =>
      current.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    );
  }, []);

  const track = useCallback(
    async <T,>(promise: Promise<T>, options: TrackToastOptions<T>): Promise<T> => {
      const id = show({
        status: "loading",
        title: options.loading,
        description:
          typeof options.description === "string" ? options.description : undefined,
      });
      try {
        const value = await promise;
        update(id, {
          status: "success",
          title:
            typeof options.success === "function"
              ? options.success(value)
              : options.success,
          description:
            typeof options.description === "function"
              ? options.description(value)
              : options.description,
        });
        scheduleDismiss(id, 5000);
        return value;
      } catch (error) {
        update(id, {
          status: "error",
          title:
            typeof options.error === "function"
              ? options.error(error)
              : options.error,
          description: toastMessage(error),
        });
        scheduleDismiss(id, 9000);
        throw error;
      }
    },
    [scheduleDismiss, show, update],
  );

  const value = useMemo(
    () => ({ show, update, dismiss, track }),
    [dismiss, show, track, update],
  );

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right">
        {children}
        {items.map((item) => (
          <ToastPrimitive.Root
            key={item.id}
            open
            onOpenChange={(open) => {
              if (!open) dismiss(item.id);
            }}
            duration={item.status === "loading" ? LONG_RUNNING_TOAST_DURATION_MS : 5000}
            className={cn(
              "grid w-[calc(100vw-2rem)] max-w-sm grid-cols-[auto_1fr_auto] items-start gap-3 rounded-lg border bg-(--color-panel) p-4 text-(--color-text) shadow-2xl",
              "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:slide-out-to-right-full data-[state=open]:slide-in-from-right-full",
              item.status === "success" && "border-(--color-accent)",
              item.status === "error" && "border-(--color-danger)",
            )}
          >
            <ToastIcon status={item.status} />
            <div className="min-w-0">
              <ToastPrimitive.Title className="text-sm font-semibold">
                {item.title}
              </ToastPrimitive.Title>
              {item.description && (
                <ToastPrimitive.Description className="mt-1 text-xs text-(--color-muted)">
                  {item.description}
                </ToastPrimitive.Description>
              )}
            </div>
            <ToastPrimitive.Close
              aria-label="Chiudi notifica"
              className="rounded-md p-1 text-(--color-muted) transition-colors hover:bg-(--color-hover) hover:text-(--color-text)"
            >
              <X className="size-4" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        ))}
        <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[120] flex max-h-[calc(100vh-2rem)] flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

function ToastIcon({ status }: { status: ToastStatus }) {
  if (status === "loading") {
    return <Loader2 className="mt-0.5 size-5 animate-spin text-(--color-info)" />;
  }
  if (status === "success") {
    return <CheckCircle2 className="mt-0.5 size-5 text-(--color-accent)" />;
  }
  return <XCircle className="mt-0.5 size-5 text-(--color-danger)" />;
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within AppToastProvider");
  }
  return ctx;
}
