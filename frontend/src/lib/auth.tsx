"use client";

import { useRouter, usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "./api";
import type { AuthUser } from "./types";

interface AuthState {
  user: AuthUser | null;
  loading: boolean;
  refresh: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

const PUBLIC_PATHS = new Set(["/login"]);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  async function refresh() {
    try {
      const data = await api.get<{ user: AuthUser }>("/api/auth/me");
      setUser(data.user);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
      } else {
        // Network or upstream errors should not bounce a logged-in user out;
        // we keep the previous user state and let the next refresh retry.
        console.error("Auth refresh failed", err);
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Hard redirect when an authenticated route loads with no user.
  useEffect(() => {
    if (loading) return;
    if (!user && !PUBLIC_PATHS.has(pathname)) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
    if (user && pathname === "/login") {
      router.replace("/");
    }
  }, [loading, user, pathname, router]);

  async function login(username: string, password: string) {
    const data = await api.post<{ user: AuthUser }>("/api/auth/login", { username, password });
    setUser(data.user);
  }

  async function logout() {
    try {
      await api.post("/api/auth/logout");
    } finally {
      setUser(null);
      router.replace("/login");
    }
  }

  const value = useMemo<AuthState>(
    () => ({ user, loading, refresh, login, logout }),
    [user, loading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}
