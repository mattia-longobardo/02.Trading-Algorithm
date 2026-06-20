"use client";

import { useQueryClient } from "@tanstack/react-query";
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
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useToast } from "@/lib/toast";

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
  const toast = useToast();

  function submit() {
    const promise = api.get<{ status: string; message: string }>(action.path);
    onClose();
    void toast
      .track(promise, {
        loading: `${action.label} in corso`,
        success: (data) => data.message || `${action.label} completato`,
        error: `${action.label} fallito`,
        description: action.description,
      })
      .then(onDone)
      .catch(() => {});
  }

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
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Annulla
        </Button>
        <Button onClick={submit}>
          Conferma
        </Button>
      </div>
    </div>
  );
}

export function JobsPanel() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [actionConfirm, setActionConfirm] = useState<JobAction | null>(null);

  return (
    <>
      {user?.role === "admin" ? (
        <Card>
          <CardHeader>
            <CardTitle>Job manuali (admin)</CardTitle>
            <span className="text-xs text-(--color-muted)">
              Ogni esecuzione condivide il lock dello scheduler.
            </span>
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
      ) : (
        <p className="text-sm text-(--color-muted)">
          Accesso riservato agli amministratori.
        </p>
      )}

      <Dialog
        open={Boolean(actionConfirm)}
        onOpenChange={(open) => !open && setActionConfirm(null)}
      >
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
    </>
  );
}
