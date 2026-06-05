"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import type { SettingsResponse } from "@/lib/types";

const ETORO_SECRET_FIELDS = [
  { key: "openai_api_key", label: "OpenAI API key" },
  { key: "etoro_api_key", label: "eToro API key" },
  { key: "etoro_user_key", label: "eToro user key" },
];

export function BrokerPanel() {
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsResponse>("/api/settings"),
  });
  const data = settings.data;
  const active = (data?.active_providers ?? []).includes("etoro");

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>eToro</CardTitle>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={active ? "open" : "muted"}>
              {active ? "modulo attivo" : "modulo disattivato"}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-(--color-muted)">
            {active
              ? "Le credenziali eToro sono configurate. Il bot opera su questo broker e la dashboard ne aggrega i valori."
              : "Le credenziali eToro non sono presenti in .env. Il modulo è spento."}
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            {ETORO_SECRET_FIELDS.map((s) => (
              <div key={s.key} className="space-y-1">
                <label className="text-xs uppercase text-(--color-muted)">{s.label}</label>
                <Input value={(data?.values[s.key] as string) ?? ""} readOnly />
              </div>
            ))}
          </div>
          <p className="text-xs text-(--color-muted)">
            Per motivi di sicurezza i segreti si modificano solo via <code>.env</code> del backend, mai
            tramite la UI.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
