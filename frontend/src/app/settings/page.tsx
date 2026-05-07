"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import type { SettingsResponse, UserRow } from "@/lib/types";

const SETTING_FIELDS: Array<{
  key: string;
  label: string;
  hint: string;
  kind: "number" | "string" | "select";
  options?: string[];
  restartRequired?: boolean;
}> = [
  { key: "max_open_trades_stock", label: "Max open trade stock", hint: "Slot massimi attivi su azioni.", kind: "number" },
  { key: "max_open_trades_crypto", label: "Max open trade crypto", hint: "Slot massimi attivi su crypto.", kind: "number" },
  { key: "weekly_universe_stocks", label: "Universe stock", hint: "Numero di simboli stock nell'universe settimanale.", kind: "number" },
  { key: "weekly_universe_crypto", label: "Universe crypto", hint: "Numero di simboli crypto nell'universe settimanale.", kind: "number" },
  { key: "currency", label: "Currency", hint: "Valuta di riferimento (per crypto Alpaca usa USD).", kind: "string" },
  { key: "risk_tolerance", label: "Risk tolerance", hint: "1 = conservativo, 10 = aggressivo.", kind: "number" },
  { key: "strategy_horizon_days_min", label: "Horizon min (giorni)", hint: "Minimo orizzonte di holding suggerito al modello.", kind: "number" },
  { key: "strategy_horizon_days_max", label: "Horizon max (giorni)", hint: "Massimo orizzonte di holding suggerito al modello.", kind: "number" },
  { key: "crypto_entry_limit_collar_bps", label: "Crypto entry collar (bps)", hint: "Tolleranza limit IOC marketable.", kind: "number" },
  { key: "crypto_entry_max_chase_bps", label: "Crypto max chase (bps)", hint: "Quanto inseguire la best ask.", kind: "number" },
  { key: "crypto_pending_reprice_minutes", label: "Crypto reprice (min)", hint: "Minuti prima di rinviare il limit pending.", kind: "number" },
  { key: "crypto_pending_cancel_minutes", label: "Crypto cancel (min)", hint: "Minuti prima di cancellare il pending lontano dal target.", kind: "number" },
  { key: "log_level", label: "Log level", hint: "Livello log applicativo.", kind: "select", options: ["DEBUG", "INFO", "WARNING", "ERROR"], restartRequired: true },
  { key: "log_profile", label: "Log profile", hint: "Verbosity preset.", kind: "select", options: ["DEBUG", "PRODUCTION"], restartRequired: true },
];

const SECRET_FIELDS = [
  { key: "openai_api_key", label: "OpenAI API key" },
  { key: "alpaca_api_key", label: "Alpaca API key" },
  { key: "alpaca_secret_key", label: "Alpaca secret key" },
];

export default function SettingsPage() {
  const { user } = useAuth();
  if (!user) return null;
  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Impostazioni</h1>
        <p className="text-sm text-(--color-muted)">Configurazione runtime e gestione utenze.</p>
      </header>
      <Tabs defaultValue="env">
        <TabsList>
          <TabsTrigger value="env">Ambiente</TabsTrigger>
          <TabsTrigger value="users">Account &amp; utenti</TabsTrigger>
        </TabsList>
        <TabsContent value="env">
          <EnvTab adminOnly={user.role === "admin"} />
        </TabsContent>
        <TabsContent value="users">
          <UsersTab />
        </TabsContent>
      </Tabs>
    </section>
  );
}

function EnvTab({ adminOnly }: { adminOnly: boolean }) {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsResponse>("/api/settings"),
  });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!settings.data) return;
    const seed: Record<string, string> = {};
    for (const f of SETTING_FIELDS) {
      const v = settings.data.values[f.key];
      seed[f.key] = v === null || v === undefined ? "" : String(v);
    }
    setDraft(seed);
  }, [settings.data]);

  const mutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {};
      for (const f of SETTING_FIELDS) {
        const raw = draft[f.key];
        if (f.kind === "number") {
          if (raw === "") continue;
          const num = Number(raw);
          if (Number.isNaN(num)) throw new Error(`${f.label} non valido`);
          payload[f.key] = num;
        } else {
          payload[f.key] = raw;
        }
      }
      return api.patch<SettingsResponse>("/api/settings", payload);
    },
    onSuccess: (res) => {
      setSuccess(
        res.restart_required
          ? "Impostazioni salvate. Alcuni valori richiedono un riavvio del backend."
          : "Impostazioni salvate."
      );
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (err) =>
      setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>Parametri trading</CardTitle>
          {settings.data?.restart_required && (
            <Badge variant="pending">Riavvio richiesto</Badge>
          )}
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {SETTING_FIELDS.map((f) => (
            <div key={f.key} className="space-y-1">
              <label className="flex items-center justify-between text-xs uppercase text-(--color-muted)">
                <span>{f.label}</span>
                {f.restartRequired && <Badge variant="muted">restart</Badge>}
              </label>
              {f.kind === "select" ? (
                <select
                  className="h-9 w-full rounded-lg border border-(--color-line) bg-slate-950/50 px-3 text-sm text-(--color-text) focus:outline-none focus:ring-2 focus:ring-(--color-accent)"
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft((p) => ({ ...p, [f.key]: e.target.value }))}
                  disabled={!adminOnly}
                >
                  {(f.options ?? []).map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              ) : (
                <Input
                  value={draft[f.key] ?? ""}
                  onChange={(e) => setDraft((p) => ({ ...p, [f.key]: e.target.value }))}
                  disabled={!adminOnly}
                  inputMode={f.kind === "number" ? "decimal" : "text"}
                />
              )}
              <p className="text-xs text-(--color-muted)">{f.hint}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Segreti (sola lettura)</CardTitle>
          <span className="text-xs text-(--color-muted)">
            Modificali solo via .env per sicurezza.
          </span>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-3">
          {SECRET_FIELDS.map((s) => (
            <div key={s.key} className="space-y-1">
              <label className="text-xs uppercase text-(--color-muted)">{s.label}</label>
              <Input value={(settings.data?.values[s.key] as string) ?? ""} readOnly />
            </div>
          ))}
        </CardContent>
      </Card>

      {error && (
        <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
          {success}
        </div>
      )}

      {adminOnly && (
        <div className="flex justify-end">
          <Button
            onClick={() => {
              setError(null);
              setSuccess(null);
              mutation.mutate();
            }}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Salvataggio…" : "Salva"}
          </Button>
        </div>
      )}
      {!adminOnly && (
        <p className="text-xs text-(--color-muted)">
          Solo gli amministratori possono modificare queste impostazioni.
        </p>
      )}
    </div>
  );
}

function UsersTab() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  return (
    <div className="space-y-4">
      <OwnProfileCard />
      <ChangeOwnPasswordCard />
      {isAdmin && <ManageUsersCard />}
    </div>
  );
}

function OwnProfileCard() {
  const { user, refresh } = useAuth();
  const [username, setUsername] = useState(user?.username ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [currentPassword, setCurrentPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    setUsername(user?.username ?? "");
    setDisplayName(user?.display_name ?? "");
  }, [user]);

  const mutation = useMutation({
    mutationFn: () =>
      api.post(`/api/auth/profile`, {
        current_password: currentPassword,
        username: username !== user?.username ? username : undefined,
        display_name: displayName !== user?.display_name ? displayName : undefined,
      }),
    onSuccess: async () => {
      setSuccess("Profilo aggiornato.");
      setCurrentPassword("");
      await refresh();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  const dirty =
    username !== (user?.username ?? "") || displayName !== (user?.display_name ?? "");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Profilo personale</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Username</label>
          <Input value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Nome visualizzato</label>
          <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Password attuale</label>
          <Input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            placeholder="richiesta per confermare le modifiche"
          />
        </div>
        {error && (
          <div className="md:col-span-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        )}
        {success && (
          <div className="md:col-span-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            {success}
          </div>
        )}
        <div className="md:col-span-3 flex justify-end">
          <Button
            onClick={() => {
              setError(null);
              setSuccess(null);
              mutation.mutate();
            }}
            disabled={!dirty || !currentPassword || mutation.isPending}
          >
            {mutation.isPending ? "Salvataggio…" : "Aggiorna profilo"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ChangeOwnPasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      if (next !== confirm) throw new Error("Le password non coincidono");
      return api.post(`/api/auth/change-password`, {
        current_password: current,
        new_password: next,
      });
    },
    onSuccess: () => {
      setSuccess("Password aggiornata.");
      setCurrent("");
      setNext("");
      setConfirm("");
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cambia la tua password</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Password attuale</label>
          <Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Nuova password</label>
          <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} />
        </div>
        <div className="space-y-1">
          <label className="text-xs uppercase text-(--color-muted)">Conferma</label>
          <Input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>
        {error && (
          <div className="md:col-span-3 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {error}
          </div>
        )}
        {success && (
          <div className="md:col-span-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
            {success}
          </div>
        )}
        <div className="md:col-span-3 flex justify-end">
          <Button
            onClick={() => {
              setError(null);
              setSuccess(null);
              mutation.mutate();
            }}
            disabled={!current || !next || !confirm || mutation.isPending}
          >
            {mutation.isPending ? "Aggiornamento…" : "Aggiorna password"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ManageUsersCard() {
  const qc = useQueryClient();
  const { user } = useAuth();
  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => api.get<{ users: UserRow[] }>("/api/users"),
  });
  const [creating, setCreating] = useState(false);
  const [resetting, setResetting] = useState<UserRow | null>(null);

  const toggleDisabled = useMutation({
    mutationFn: ({ id, disabled }: { id: number; disabled: boolean }) =>
      api.patch(`/api/users/${id}`, { disabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: number; role: "admin" | "user" }) =>
      api.patch(`/api/users/${id}`, { role }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  const deleteUser = useMutation({
    mutationFn: (id: number) => api.delete(`/api/users/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Gestione utenze</CardTitle>
        <Button size="sm" variant="secondary" onClick={() => setCreating(true)}>
          Nuovo utente
        </Button>
      </CardHeader>
      <CardContent>
        {users.isLoading && <p className="text-sm text-(--color-muted)">Caricamento…</p>}
        {users.data && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-separate border-spacing-y-1 text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-(--color-muted)">
                  <th className="px-2 py-2">Utente</th>
                  <th className="px-2 py-2">Ruolo</th>
                  <th className="px-2 py-2">Stato</th>
                  <th className="px-2 py-2">Creato</th>
                  <th className="px-2 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {users.data.users.map((u) => (
                  <tr key={u.id} className="bg-slate-950/40 [&>td]:border-y [&>td]:border-(--color-line)">
                    <td className="px-2 py-2 first:rounded-l-lg">
                      <p className="font-medium">{u.display_name}</p>
                      <p className="text-xs text-(--color-muted)">@{u.username}</p>
                    </td>
                    <td className="px-2 py-2">
                      <select
                        className="h-7 rounded border border-(--color-line) bg-slate-950 px-2 text-xs"
                        value={u.role}
                        onChange={(e) =>
                          changeRole.mutate({ id: u.id, role: e.target.value as "admin" | "user" })
                        }
                        disabled={u.id === user?.id}
                      >
                        <option value="admin">admin</option>
                        <option value="user">user</option>
                      </select>
                    </td>
                    <td className="px-2 py-2">
                      <Badge variant={u.disabled ? "cancelled" : "open"}>
                        {u.disabled ? "disabilitato" : "attivo"}
                      </Badge>
                    </td>
                    <td className="px-2 py-2 text-(--color-muted)">{formatDateTime(u.created_at)}</td>
                    <td className="px-2 py-2 last:rounded-r-lg">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setResetting(u)}
                        >
                          Reset password
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() =>
                            toggleDisabled.mutate({ id: u.id, disabled: !u.disabled })
                          }
                          disabled={u.id === user?.id}
                        >
                          {u.disabled ? "Riabilita" : "Disabilita"}
                        </Button>
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => {
                            if (confirm(`Eliminare l'utente @${u.username}?`)) deleteUser.mutate(u.id);
                          }}
                          disabled={u.id === user?.id}
                        >
                          Elimina
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>

      <CreateUserDialog open={creating} onClose={() => setCreating(false)} />
      <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} />
    </Card>
  );
}

function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "user">("user");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.post(`/api/users`, {
        username,
        display_name: displayName,
        password,
        role,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      setUsername("");
      setDisplayName("");
      setPassword("");
      setRole("user");
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuovo utente</DialogTitle>
          <DialogDescription>
            La password viene memorizzata con bcrypt. L&apos;utente potrà cambiarla al primo accesso.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <label className="text-xs uppercase text-(--color-muted)">Username</label>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>
          <div>
            <label className="text-xs uppercase text-(--color-muted)">Display name</label>
            <Input value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
          </div>
          <div>
            <label className="text-xs uppercase text-(--color-muted)">Password iniziale</label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs uppercase text-(--color-muted)">Ruolo</label>
            <select
              className="h-9 w-full rounded-lg border border-(--color-line) bg-slate-950/50 px-3 text-sm text-(--color-text)"
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "user")}
            >
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
          </div>
          {error && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              {error}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Annulla
            </Button>
            <Button
              onClick={() => {
                setError(null);
                mutation.mutate();
              }}
              disabled={mutation.isPending}
            >
              Crea
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({
  user,
  onClose,
}: {
  user: UserRow | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [pw, setPw] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      setPw("");
      setError(null);
    }
  }, [user]);

  const mutation = useMutation({
    mutationFn: () =>
      api.post(`/api/users/${user!.id}/reset-password`, { new_password: pw }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      onClose();
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <Dialog open={Boolean(user)} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reset password — @{user?.username}</DialogTitle>
          <DialogDescription>
            Tutte le sessioni attive di questo utente verranno revocate immediatamente.
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <Input
            type="password"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            placeholder="Nuova password"
          />
          {error && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
              {error}
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Annulla
            </Button>
            <Button onClick={() => mutation.mutate()} disabled={!pw || mutation.isPending}>
              Conferma
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
