"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Save, Undo2 } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import {
  PROMPT_KEYS,
  type PromptDetail,
  type PromptKey,
  type PromptVersion,
} from "@/lib/types";

const PROMPT_LABELS: Record<PromptKey, string> = {
  new_signal: "new_signal — single-symbol entry decision",
  batch_signals: "batch_signals — batch entry analysis (6×/day)",
  pending_review: "pending_review — daily review of stale PENDING",
  protection_review: "protection_review — trailing TP reassessment",
  universe_dossier: "universe_dossier — per-symbol weekly dossier",
  universe_shortlist: "universe_shortlist — weekly shortlist phase",
  universe_final: "universe_final — final consolidation (legacy)",
  universe_final_from_dossiers: "universe_final_from_dossiers — final from dossiers",
};

export function PromptsEditor() {
  const { user } = useAuth();

  if (user?.role !== "admin") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Accesso negato</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-(--color-muted)">
            Questa sezione è riservata agli amministratori.
          </p>
        </CardContent>
      </Card>
    );
  }

  return <PromptsSection />;
}

function PromptsSection() {
  const [activeKey, setActiveKey] = useState<PromptKey>(PROMPT_KEYS[0]);
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <>
      <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Prompt</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1">
            {PROMPT_KEYS.map((key) => (
              <button
                key={key}
                onClick={() => setActiveKey(key)}
                className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition-colors ${
                  activeKey === key
                    ? "bg-(--color-hover) text-(--color-text)"
                    : "text-(--color-muted) hover:bg-(--color-hover)/60"
                }`}
              >
                {PROMPT_LABELS[key]}
              </button>
            ))}
          </CardContent>
        </Card>

        <PromptEditor activeKey={activeKey} onOpenHistory={() => setHistoryOpen(true)} />
      </div>

      <Dialog open={historyOpen} onOpenChange={(o) => !o && setHistoryOpen(false)}>
        <DialogContent className="max-w-3xl">
          <PromptHistory promptKey={activeKey} onClose={() => setHistoryOpen(false)} />
        </DialogContent>
      </Dialog>
    </>
  );
}

function PromptEditor({
  activeKey,
  onOpenHistory,
}: {
  activeKey: PromptKey;
  onOpenHistory: () => void;
}) {
  const qc = useQueryClient();
  const detail = useQuery({
    queryKey: ["prompt", activeKey],
    queryFn: () => api.get<PromptDetail>(`/api/prompts/${activeKey}`),
  });

  const [draft, setDraft] = useState("");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(detail.data?.content ?? "");
    setComment("");
    setError(null);
  }, [detail.data, activeKey]);

  const dirty = (detail.data?.content ?? "") !== draft;

  const saveMutation = useMutation({
    mutationFn: () =>
      api.post(`/api/prompts/${activeKey}`, { content: draft, comment: comment || null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prompt", activeKey] });
      qc.invalidateQueries({ queryKey: ["prompt-versions", activeKey] });
      setComment("");
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{PROMPT_LABELS[activeKey]}</CardTitle>
        <div className="flex items-center gap-2">
          {dirty ? (
            <Badge variant="pending">non salvato</Badge>
          ) : (
            <Badge variant="open">sincronizzato</Badge>
          )}
          <Button size="sm" variant="secondary" onClick={onOpenHistory}>
            <History className="size-4" /> Storico
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {detail.isLoading ? (
          <p className="text-sm text-(--color-muted)">Caricamento…</p>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-(--color-muted)">
              Versione corrente: <code>#{detail.data?.version_id}</code> aggiornata{" "}
              {formatDateTime(detail.data?.updated_at)}
            </p>
            <div className="space-y-1">
              <Textarea
                rows={20}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                spellCheck={false}
                className="font-mono text-xs"
              />
              <p className="flex items-center justify-end gap-3 text-xs text-(--color-muted)">
                <span>{draft.length.toLocaleString("it-IT")} caratteri</span>
                <span aria-hidden="true">·</span>
                <span>
                  {draft.split(/\s+/).filter(Boolean).length.toLocaleString("it-IT")} parole
                </span>
              </p>
            </div>
            <div className="grid gap-3 md:grid-cols-[1fr_auto]">
              <Input
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Commento (opzionale, salvato con la nuova versione)"
              />
              <Button
                onClick={() => {
                  setError(null);
                  saveMutation.mutate();
                }}
                disabled={!dirty || saveMutation.isPending}
              >
                <Save className="size-4" /> Salva versione
              </Button>
            </div>
            {error && <StatusBanner kind="error">{error}</StatusBanner>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PromptHistory({
  promptKey,
  onClose,
}: {
  promptKey: PromptKey;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const versions = useQuery({
    queryKey: ["prompt-versions", promptKey],
    queryFn: () => api.get<{ versions: PromptVersion[] }>(`/api/prompts/${promptKey}/versions`),
  });

  const rollback = useMutation({
    mutationFn: (versionId: number) =>
      api.post(`/api/prompts/${promptKey}/rollback`, { version_id: versionId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["prompt", promptKey] });
      qc.invalidateQueries({ queryKey: ["prompt-versions", promptKey] });
      onClose();
    },
  });

  return (
    <div>
      <DialogHeader>
        <DialogTitle>Storico — {promptKey}</DialogTitle>
        <DialogDescription>
          Ogni salvataggio crea una nuova versione. Puoi tornare a qualunque versione precedente.
        </DialogDescription>
      </DialogHeader>
      <div className="max-h-[60vh] overflow-y-auto space-y-3">
        {versions.isLoading && <p className="text-sm text-(--color-muted)">Caricamento…</p>}
        {versions.data?.versions.map((v) => (
          <div
            key={v.id}
            className="rounded-lg border border-(--color-line) bg-(--color-panel)/50 p-3"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium">
                  Versione #{v.id}{" "}
                  {v.is_current ? <Badge variant="open">attiva</Badge> : null}
                </p>
                <p className="text-xs text-(--color-muted)">
                  {formatDateTime(v.saved_at)} ·{" "}
                  {v.saved_by_username ? `@${v.saved_by_username}` : "system"}
                </p>
              </div>
              {!v.is_current && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => rollback.mutate(v.id)}
                  disabled={rollback.isPending}
                >
                  <Undo2 className="size-4" /> Ripristina
                </Button>
              )}
            </div>
            {v.comment && (
              <p className="mt-2 rounded-md bg-(--color-panel)/60 px-3 py-1.5 text-xs italic text-(--color-muted)">
                {v.comment}
              </p>
            )}
            <pre className="mt-2 max-h-40 overflow-auto rounded-md bg-(--color-panel) p-2 text-xs leading-relaxed text-(--color-text)">
              {v.content}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}
