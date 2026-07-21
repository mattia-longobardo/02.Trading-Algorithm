import { AuthError } from "next-auth";
import { ArrowRightIcon, LockKeyholeIcon, ShieldCheckIcon } from "lucide-react";
import { redirect } from "next/navigation";

import { auth, signIn } from "@/auth";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Stamp } from "@/components/stamp";

const SIGNIN_ERROR_URL = "/login";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ callbackUrl?: string; error?: string }>;
}) {
  const { callbackUrl, error } = await searchParams;
  const session = await auth();
  if (session) redirect(callbackUrl ?? "/");

  return (
    <main className="bg-background grid min-h-svh lg:grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)]">
      <section className="border-border relative hidden overflow-hidden border-r p-10 lg:flex lg:flex-col lg:justify-between xl:p-14">
        <div>
          <p className="font-mono text-[11px] font-medium tracking-[0.18em] uppercase">
            Trading Bot
          </p>
          <p className="text-muted-foreground mt-2 font-mono text-[10px] tracking-[0.12em] uppercase">
            Registro operativo
          </p>
        </div>

        <div className="max-w-xl">
          <h1 className="font-display text-5xl leading-[1.02] font-medium tracking-[-0.025em] xl:text-6xl">
            Il portafoglio,
            <br />senza rumore.
          </h1>
          <p className="text-muted-foreground mt-6 max-w-md text-base leading-7">
            Equity, rischio, operazioni e benchmark in un unico registro finanziario,
            preciso e leggibile.
          </p>
        </div>

        <div className="border-border grid max-w-xl grid-cols-2 border-t pt-5">
          <div>
            <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
              Accesso
            </p>
            <p className="mt-2 text-sm">Single sign-on Authentik</p>
          </div>
          <div>
            <p className="font-mono text-[10px] tracking-[0.14em] text-muted-foreground uppercase">
              Sessione
            </p>
            <p className="mt-2 text-sm">Protetta e personale</p>
          </div>
        </div>
      </section>

      <section className="flex items-center justify-center px-5 py-10 sm:px-10">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <p className="font-mono text-[11px] font-medium tracking-[0.18em] uppercase">
              Trading Bot
            </p>
            <p className="text-muted-foreground mt-1 font-mono text-[10px] tracking-[0.12em] uppercase">
              Registro operativo
            </p>
          </div>

          <Card className="shadow-xs">
            <CardHeader className="border-border border-b">
              <div className="bg-accent text-primary mb-5 flex size-10 items-center justify-center rounded-md">
                <LockKeyholeIcon aria-hidden="true" strokeWidth={1.5} />
              </div>
              <CardTitle className="font-display text-[30px] font-medium tracking-[-0.02em]">
                Accedi al tuo account
              </CardTitle>
              <CardDescription className="max-w-sm leading-6">
                Usa l’identità aziendale. Non vengono gestite password locali.
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-5">
              {error ? (
                <div className="border-negative/50 bg-negative/5 rounded-md border p-3" role="alert">
                  <Stamp tone="rejected">Accesso negato</Stamp>
                  <p className="text-muted-foreground mt-2 text-xs leading-5">
                    Authentik non ha completato l’accesso ({error}). Riprova; se il problema
                    continua, verifica che il tuo utente sia autorizzato all’applicazione Trading.
                  </p>
                </div>
              ) : null}

              <form
                action={async () => {
                  "use server";
                  try {
                    await signIn("authentik", { redirectTo: callbackUrl ?? "/" });
                  } catch (err) {
                    if (err instanceof AuthError) {
                      redirect(`${SIGNIN_ERROR_URL}?error=${err.type}`);
                    }
                    throw err;
                  }
                }}
              >
                <Button type="submit" className="w-full">
                  Continua con Authentik
                  <ArrowRightIcon data-icon="inline-end" aria-hidden="true" />
                </Button>
              </form>
            </CardContent>
            <CardFooter className="border-border text-muted-foreground gap-2 border-t text-xs">
              <ShieldCheckIcon aria-hidden="true" strokeWidth={1.5} />
              La sessione viene validata prima di ogni accesso ai dati.
            </CardFooter>
          </Card>
        </div>
      </section>
    </main>
  );
}
