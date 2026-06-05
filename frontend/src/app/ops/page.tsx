"use client";

import { JobsPanel } from "@/components/ops/jobs-panel";
import { LogStream } from "@/components/ops/log-stream";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function OpsPage() {
  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Operazioni</h1>
          <p className="text-sm text-(--color-muted)">
            Gestione operativa: job manuali e log live del bot.
          </p>
        </div>
      </header>

      <Tabs defaultValue="jobs">
        <TabsList>
          <TabsTrigger value="jobs">Job</TabsTrigger>
          <TabsTrigger value="logs">Log</TabsTrigger>
        </TabsList>

        <TabsContent value="jobs">
          <JobsPanel />
        </TabsContent>

        <TabsContent value="logs">
          <LogStream />
        </TabsContent>
      </Tabs>
    </section>
  );
}
