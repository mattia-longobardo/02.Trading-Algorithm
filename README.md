# Trading Monorepo

Monorepository del progetto trading. Contiene due servizi orchestrati da un unico `docker-compose.yml`:

- [`backend/`](backend/) — bot Python (Alpaca + OpenAI), scheduler APScheduler e API HTTP. Vedi [backend/README.md](backend/README.md) per i dettagli del trading bot.
- [`frontend/`](frontend/) — dashboard Next.js 15 (App Router + TypeScript + Tailwind v4) che consuma le API del backend e fornisce il live tail dei log.

## Layout

```
.
├── backend/           # codice Python, Dockerfile, .env.example, tests/, data/, logs/, run/
├── frontend/          # progetto Next.js (App Router)
├── docker-compose.yml # orchestra backend + frontend sulla rete Traefik
└── README.md
```

## Avvio rapido in Docker

1. Crea il file di ambiente del backend:
   ```bash
   cp backend/.env.example backend/.env
   # poi compila chiavi OpenAI / Alpaca e impostazioni
   ```
2. Assicurati che la rete esterna `proxy_public` esista e che Traefik instradi gli host `trading.local` e `api.trading.local` verso il container.
3. Avvia lo stack:
   ```bash
   docker compose up -d --build
   ```

Una volta avviato:

- `http://trading.local` — dashboard Next.js
- `http://api.trading.local` — API REST + SSE log stream

## Comunicazione frontend ⇄ backend

Il browser dell'utente chiama il backend via HTTP cross-origin:

- Frontend e backend stanno sulla stessa rete Docker (`proxy_public`) ma sono esposti su host diversi.
- Il frontend riceve l'URL pubblico del backend al momento della build via build arg `NEXT_PUBLIC_API_URL` (default `http://api.trading.local`).
- Il backend filtra le origini consentite via env `CORS_ALLOWED_ORIGINS`.

## Sviluppo locale fuori da Docker

Backend (Python 3.14):
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # poi compila
python main.py
```

Frontend (Node 22):
```bash
cd frontend
npm install
cp .env.example .env.local  # imposta NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```
