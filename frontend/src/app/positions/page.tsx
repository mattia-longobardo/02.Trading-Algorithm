import { Activity } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";

export default function PositionsPage() {
  return (
    <section className="space-y-6">
      <header>
        <h1 className="text-3xl font-semibold">Posizioni</h1>
        <p className="text-sm text-(--color-muted)">Posizioni aperte in tempo reale.</p>
      </header>
      <EmptyState
        icon={Activity}
        title="In arrivo"
        description="La board delle posizioni live arriverà a breve."
      />
    </section>
  );
}
