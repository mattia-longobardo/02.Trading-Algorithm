"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function ConsolePage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [actionConfirm, setActionConfirm] = useState<JobAction | null>(null);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Console</h1>
          <p className="text-sm text-(--color-muted)">
            Lancia i job manuali dello scheduler. Tutte le esecuzioni sono registrate
            nell&apos;audit log.
          </p>
        </div>
      </header>

      {user?.role === "admin" && (
        <Card>
          <CardHeader>
            <CardTitle>Job manuali (admin)</CardTitle>
            <span className="text-xs text-(--color-muted)">Ogni esecuzione condivide il lock dello scheduler.</span>
          </CardHeader>
          <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {JOB_ACTIONS.map((action) => (
              <Card key={action.path} className="p-4">
                <h4 className="text-sm font-semibold text-(--color-text)">{action.label}</h4>
                <p className="mt-1 text-xs text-(--color-muted)">{action.description}</p>
                <Button
                  size="sm"
                  variant="secondary"
                  className="mt-3"
                  onClick={() => setActionConfirm(action)}
                >
                  Esegui
                </Button>
              </Card>
            ))}
          </CardContent>
        </Card>
      )}

      <Dialog open={Boolean(actionConfirm)} onOpenChange={(open) => !open && setActionConfirm(null)}>
        <DialogContent>
          {actionConfirm && (
            <RunActionForm
              action={actionConfirm}
              onClose={() => setActionConfirm(null)}
              onDone={() => {
                setActionConfirm(null);
                qc.invalidateQueries();
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}

interface JobAction {
  label: string;
  description: string;
  path: string;
}

const JOB_ACTIONS: JobAction[] = [
  {
    label: "Rigenera universo",
    description: "Aggiorna l'universo stock/crypto monitorato.",
    path: "/api/universe/generate",
  },
  {
    label: "Genera nuovi ordini",
    description: "Esegue il ciclo GPT batch e apre eventuali nuovi trade.",
    path: "/api/orders/generate",
  },
  {
    label: "Report settimanale",
    description: "Genera il report PnL della settimana.",
    path: "/api/report/generate",
  },
  {
    label: "Report trimestrale",
    description: "Report del trimestre concluso.",
    path: "/api/report/quarterly",
  },
  {
    label: "Report semestrale",
    description: "Report del semestre concluso.",
    path: "/api/report/biannual",
  },
  {
    label: "Report annuale",
    description: "Report dell'anno solare concluso.",
    path: "/api/report/annual",
  },
  {
    label: "Reset scheduler",
    description: "Sblocca lo scheduler in stallo.",
    path: "/api/scheduler/reset",
  },
];

function RunActionForm({
  action,
  onClose,
  onDone,
}: {
  action: JobAction;
  onClose: () => void;
  onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.get<{ status: string; message: string }>(action.path),
    onSuccess: (data) => {
      setResult(data.message);
      setTimeout(onDone, 1500);
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.message : (err as Error).message);
    },
  });

  return (
    <div>
      <DialogHeader>
        <DialogTitle>{action.label}</DialogTitle>
        <DialogDescription>{action.description}</DialogDescription>
      </DialogHeader>
      <p className="text-sm text-(--color-muted)">
        Confermi l&apos;esecuzione manuale di questo job? L&apos;azione condivide il lock dello
        scheduler: se un altro job è in corso riceverai un 409 Conflict.
      </p>
      {error && (
        <StatusBanner kind="error" className="mt-3">
          {error}
        </StatusBanner>
      )}
      {result && (
        <StatusBanner kind="success" className="mt-3">
          {result}
        </StatusBanner>
      )}
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Annulla
        </Button>
        <Button onClick={() => mutation.mutate()} disabled={mutation.isPending}>
          {mutation.isPending ? "Esecuzione…" : "Conferma"}
        </Button>
      </div>
    </div>
  );
}
