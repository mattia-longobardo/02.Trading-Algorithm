import { LogOutIcon } from "lucide-react";

import { auth, signOut } from "@/auth";
import { Separator } from "@/components/ui/separator";

/** Identità della sessione + uscita — l'unico punto d'accesso è Authentik. */
export async function UserMenu() {
  const session = await auth();
  if (!session?.user) return null;

  const label = session.user.name ?? session.user.email ?? "Account";

  return (
    <>
      <Separator orientation="vertical" className="hidden h-4 md:block" />
      <div className="hidden items-center gap-2 md:flex">
        <span className="text-muted-foreground max-w-32 truncate font-mono text-[11px] tracking-[0.04em]">
          {label}
        </span>
        <form
          action={async () => {
            "use server";
            await signOut({ redirectTo: "/login" });
          }}
        >
          <button
            type="submit"
            aria-label="Esci"
            title="Esci"
            className="text-muted-foreground hover:text-foreground hover:bg-accent inline-flex size-8 items-center justify-center rounded-md transition-colors duration-150"
          >
            <LogOutIcon className="size-4" strokeWidth={1.5} />
          </button>
        </form>
      </div>
    </>
  );
}
