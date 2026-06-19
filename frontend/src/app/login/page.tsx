"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { StatusBanner } from "@/components/ui/status-banner";
import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/api";

function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      const next = searchParams.get("next") || "/";
      router.replace(next.startsWith("/") ? next : "/");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Errore sconosciuto");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="w-full max-w-sm">
      <div className="mb-6 text-center">
        <div className="mx-auto mb-3 size-10 rounded-xl bg-(--color-accent) grid place-items-center text-(--color-accent-contrast) text-lg font-bold">
          T
        </div>
        <h1 className="text-xl font-semibold">Trading Console</h1>
        <p className="mt-1 text-sm text-(--color-muted)">Accedi per continuare</p>
      </div>
      <form onSubmit={onSubmit} className="space-y-4">
        <div className="space-y-1">
          <label htmlFor="username" className="text-xs font-medium text-(--color-muted) uppercase">
            Username
          </label>
          <Input
            id="username"
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoFocus
          />
        </div>
        <div className="space-y-1">
          <label htmlFor="password" className="text-xs font-medium text-(--color-muted) uppercase">
            Password
          </label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        {error && <StatusBanner kind="error">{error}</StatusBanner>}
        <Button type="submit" className="w-full" disabled={submitting}>
          {submitting ? "Accesso in corso…" : "Accedi"}
        </Button>
      </form>
    </Card>
  );
}

// useSearchParams() forces the page out of static prerender; wrapping the
// inner form in a Suspense boundary is what Next.js 15 requires when this
// hook is used in a Client Component on a route that may be statically
// optimized.
export default function LoginPage() {
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </div>
  );
}
