import { NextResponse } from "next/server";

import { auth } from "@/auth";

/**
 * Gate unico dell'applicazione: nessuna pagina o rotta /api (proxata al
 * backend) è raggiungibile senza sessione Authentik valida. Le pagine non
 * autenticate vengono rimandate al login; le chiamate API non autenticate
 * ricevono 401 JSON (le gestisce il fetcher lato client).
 */
export const proxy = auth((req) => {
  const { pathname } = req.nextUrl;
  if (pathname === "/login") return;

  if (!req.auth) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ detail: "Non autenticato" }, { status: 401 });
    }
    const loginUrl = new URL("/login", req.nextUrl.origin);
    loginUrl.searchParams.set("callbackUrl", pathname);
    return NextResponse.redirect(loginUrl);
  }
});

export const config = {
  // La favicon deve caricarsi anche sulla pagina di login: senza escluderla
  // il gate la reindirizza e la scheda del browser resta senza icona.
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
