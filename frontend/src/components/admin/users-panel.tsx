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
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import type { UserRow } from "@/lib/types";

export function UsersPanel() {
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
      <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
          <StatusBanner kind="error" className="md:col-span-3">
            {error}
          </StatusBanner>
        )}
        {success && (
          <StatusBanner kind="success" className="md:col-span-3">
            {success}
          </StatusBanner>
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
      <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
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
          <StatusBanner kind="error" className="md:col-span-3">
            {error}
          </StatusBanner>
        )}
        {success && (
          <StatusBanner kind="success" className="md:col-span-3">
            {success}
          </StatusBanner>
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

function UserCard({
  row,
  currentUserId,
  onRoleChange,
  onReset,
  onToggleDisabled,
  onDelete,
}: {
  row: UserRow;
  currentUserId: number | undefined;
  onRoleChange: (id: number, role: "admin" | "user") => void;
  onReset: (row: UserRow) => void;
  onToggleDisabled: (id: number, disabled: boolean) => void;
  onDelete: (row: UserRow) => void;
}) {
  const isSelf = row.id === currentUserId;
  return (
    <div className="rounded-lg border border-(--color-line) bg-(--color-panel)/40 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="break-words font-medium">{row.display_name}</p>
          <p className="break-words text-xs text-(--color-muted)">@{row.username}</p>
        </div>
        <Badge variant={row.disabled ? "cancelled" : "open"}>
          {row.disabled ? "disabilitato" : "attivo"}
        </Badge>
      </div>

      <div className="mt-3 grid gap-2 text-sm">
        <label className="space-y-1">
          <span className="text-xs uppercase text-(--color-muted)">Ruolo</span>
          <select
            className="h-10 w-full rounded border border-(--color-line) bg-(--color-panel) px-2 text-base sm:h-7 sm:text-xs"
            value={row.role}
            onChange={(e) => onRoleChange(row.id, e.target.value as "admin" | "user")}
            disabled={isSelf}
          >
            <option value="admin">admin</option>
            <option value="user">user</option>
          </select>
        </label>
        <div className="flex items-center justify-between gap-3">
          <span className="text-(--color-muted)">Creato</span>
          <span className="text-right">{formatDateTime(row.created_at)}</span>
        </div>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <Button size="sm" variant="secondary" onClick={() => onReset(row)}>
          Reset password
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onToggleDisabled(row.id, !row.disabled)}
          disabled={isSelf}
        >
          {row.disabled ? "Riabilita" : "Disabilita"}
        </Button>
        <Button
          size="sm"
          variant="danger"
          onClick={() => onDelete(row)}
          disabled={isSelf}
        >
          Elimina
        </Button>
      </div>
    </div>
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
          <>
          <div className="space-y-2 md:hidden">
            {users.data.users.map((u) => (
              <UserCard
                key={u.id}
                row={u}
                currentUserId={user?.id}
                onRoleChange={(id, role) => changeRole.mutate({ id, role })}
                onReset={setResetting}
                onToggleDisabled={(id, disabled) => toggleDisabled.mutate({ id, disabled })}
                onDelete={(row) => {
                  if (confirm(`Eliminare l'utente @${row.username}?`)) deleteUser.mutate(row.id);
                }}
              />
            ))}
          </div>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[760px] border-separate border-spacing-y-1 text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-(--color-muted)">
                  <th scope="col" className="px-2 py-2">Utente</th>
                  <th scope="col" className="px-2 py-2">Ruolo</th>
                  <th scope="col" className="px-2 py-2">Stato</th>
                  <th scope="col" className="px-2 py-2">Creato</th>
                  <th scope="col" className="px-2 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {users.data.users.map((u) => (
                  <tr
                    key={u.id}
                    className="bg-(--color-panel)/40 transition-colors hover:bg-(--color-hover)/60 [&>td]:border-y [&>td]:border-(--color-line)"
                  >
                    <td className="px-2 py-2 first:rounded-l-lg">
                      <p className="font-medium">{u.display_name}</p>
                      <p className="text-xs text-(--color-muted)">@{u.username}</p>
                    </td>
                    <td className="px-2 py-2">
                      <select
                        className="h-7 rounded border border-(--color-line) bg-(--color-panel) px-2 text-xs"
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
          </>
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
              className="h-9 w-full rounded-lg border border-(--color-line) bg-(--color-panel)/50 px-3 text-sm text-(--color-text)"
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "user")}
            >
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
          </div>
          {error && <StatusBanner kind="error">{error}</StatusBanner>}
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
          {error && <StatusBanner kind="error">{error}</StatusBanner>}
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
