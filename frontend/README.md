# Trading Frontend

Dashboard Next.js 15 (App Router + TypeScript + Tailwind v4) per il trading bot del monorepo.

## Pagine

- `/` — trigger manuali dei job dello scheduler (universo, nuovi ordini, report, reset).
- `/logs` — live tail del file di log via SSE (`/api/logs/stream`).

Le chiamate al backend vengono fatte via HTTP cross-origin: l'URL del backend è configurato con la variabile `NEXT_PUBLIC_API_URL`, valorizzata al build (Docker) o al dev (`.env.local`).

## Sviluppo locale

```bash
npm install
cp .env.example .env.local       # imposta NEXT_PUBLIC_API_URL (es. http://localhost:8000)
npm run dev
```

Il backend deve esporre `CORS_ALLOWED_ORIGINS=http://localhost:3000` (o l'origine usata in dev) per consentire le chiamate dal browser.

## Build di produzione (Docker)

Il `Dockerfile` usa il modello `output: "standalone"` di Next.js. Il build arg `NEXT_PUBLIC_API_URL` viene impostato dal `docker-compose.yml` di root:

```bash
docker compose build frontend
docker compose up -d frontend
```
