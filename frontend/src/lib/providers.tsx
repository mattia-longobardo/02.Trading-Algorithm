"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { AuthProvider } from "./auth";
import { AppToastProvider } from "./toast";
import { ThemeProvider } from "@/components/layout/theme-provider";

export function AppProviders({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 1,
            refetchOnWindowFocus: false,
          },
        },
      })
  );

  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <AppToastProvider>
          <AuthProvider>{children}</AuthProvider>
        </AppToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
