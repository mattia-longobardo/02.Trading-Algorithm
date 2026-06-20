"use client";

import { BrokerPanel } from "@/components/admin/broker-panel";
import { EnvForm } from "@/components/admin/env-form";
import { PromptsEditor } from "@/components/admin/prompts-editor";
import { UsersPanel } from "@/components/admin/users-panel";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/lib/auth";

export default function AdminPage() {
  const { user } = useAuth();
  if (!user) return null;

  const isAdmin = user.role === "admin";

  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold sm:text-3xl">Amministrazione</h1>
        <p className="text-sm text-(--color-muted)">Configurazione runtime, broker e gestione utenze.</p>
      </header>
      <Tabs defaultValue="env">
        <TabsList>
          <TabsTrigger value="env">Ambiente</TabsTrigger>
          <TabsTrigger value="etoro">eToro</TabsTrigger>
          {isAdmin && <TabsTrigger value="prompts">Prompt</TabsTrigger>}
          <TabsTrigger value="users">Utenti</TabsTrigger>
        </TabsList>
        <TabsContent value="env">
          <EnvForm isAdmin={isAdmin} />
        </TabsContent>
        <TabsContent value="etoro">
          <BrokerPanel />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="prompts">
            <PromptsEditor />
          </TabsContent>
        )}
        <TabsContent value="users">
          <UsersPanel />
        </TabsContent>
      </Tabs>
    </section>
  );
}
