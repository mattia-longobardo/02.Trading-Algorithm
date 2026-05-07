# Trading Frontend

Applicazione Next.js 15 (App Router + TypeScript + Tailwind v4 + shadcn/ui)
che fa da console operativa per il trading bot. Sostituisce la vecchia
dashboard a soli trigger manuali con una console autenticata, multi-pagina,
con grafici, modifica trade, gestione report, prompt e impostazioni.

## Pagine

| Path | Ruolo | Contenuto |
|---|---|---|
| `/login` | pubblica | login con username + password |
| `/` | utente | KPI (PnL, win-rate, profit factor, max DD, Sharpe, equity), equity curve, PnL/simbolo, allocazione aperta, distribuzione rendimenti, tabella ultimi trade |
| `/console` | utente | tabella trade editabile (PATCH `/api/trades/{id}`), legenda colonne sourced da `backend/README.md`, **job manuali admin-only** |
| `/reports` | utente | elenco report con cartelle virtuali, ricerca filename + tag + full-text JSON, anteprima PDF in iframe, viewer JSON |
| `/prompts` | **admin** | editor degli 8 prompt usati dal bot, badge "non salvato", storico versioni con rollback |
| `/logs` | utente | tail live del log file via SSE |
| `/settings` | utente (tab Ambiente solo admin) | overlay parametri trading + cambio password + gestione utenti |

## Comunicazione col backend

Il browser non parla mai direttamente col backend: la rotta dinamica
`src/app/api/proxy/[...path]/route.ts` è un proxy server-side che inoltra
ogni richiesta a `BACKEND_INTERNAL_URL` (di default
`http://backend:8000`). Vantaggi:

- una sola origine vista dal browser (niente CORS da configurare);
- backend isolato sulla rete privata `trading_internal` di Docker;
- cookie di sessione scoped a un singolo host.

`src/lib/api.ts` è il client browser che usa il proxy con percorso
`/api/proxy/...`. Server-Sent Events (`/api/logs/stream`) sono streamati
mantenendo `text/event-stream` intatto.

## Stack

- **Next.js 15** App Router, output `standalone` per Docker.
- **TanStack Query** per caching/refetch delle API.
- **Recharts** per grafici (line, bar, pie).
- **shadcn/ui pattern** (Radix primitives + Tailwind variants) con i
  componenti minimi inline in `src/components/ui/`.
- **lucide-react** per le icone.
- **Tailwind v4** con i token `--color-*` di progetto in `globals.css`.

## Sviluppo locale

```bash
cd frontend
npm install
cp .env.example .env.local
# Imposta BACKEND_INTERNAL_URL=http://localhost:8000 se il backend gira
# sulla tua macchina invece che in Docker.
npm run dev
```

Le pagine non-pubbliche reindirizzano a `/login` se la sessione manca
(controllato in `src/lib/auth.tsx`).

## Build di produzione (Docker)

Il `Dockerfile` usa il modello `output: "standalone"`. Lo stack root
costruisce il frontend e lo collega a Traefik su `trading.local`:

```bash
docker compose build frontend
docker compose up -d frontend
```

## Mappa file

```
src/
├── app/
│   ├── api/proxy/[...path]/route.ts   # proxy verso il backend
│   ├── console/page.tsx               # /console
│   ├── login/page.tsx                 # /login
│   ├── logs/page.tsx                  # /logs
│   ├── prompts/page.tsx               # /prompts
│   ├── reports/page.tsx               # /reports
│   ├── settings/page.tsx              # /settings
│   ├── layout.tsx                     # AppShell + providers
│   ├── globals.css                    # Tailwind v4 tokens
│   └── page.tsx                       # / (dashboard)
├── components/
│   ├── app-shell.tsx                  # sidebar + topbar layout
│   ├── timeframe-selector.tsx
│   └── ui/                            # button, card, dialog, tabs, …
└── lib/
    ├── api.ts                         # client browser (passa dal proxy)
    ├── auth.tsx                       # AuthProvider + useAuth hook
    ├── cn.ts                          # clsx + tailwind-merge
    ├── format.ts                      # formattatori IT
    ├── providers.tsx                  # QueryClient + AuthProvider
    └── types.ts                       # tipi condivisi col backend
```
