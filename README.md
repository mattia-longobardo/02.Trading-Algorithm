# Trading Monorepo

Monorepository del progetto trading. Contiene due servizi orchestrati da un unico `docker-compose.yml`:

- [`backend/`](backend/) — bot Python (Alpaca + OpenAI), scheduler APScheduler, app database SQLite e API HTTP FastAPI. Vedi [backend/README.md](backend/README.md) per i dettagli del trading bot.
- [`frontend/`](frontend/) — applicazione Next.js 15 (App Router + TypeScript + Tailwind v4 + shadcn/ui) con autenticazione, dashboard, console editabile, gestione report, prompt modifier e settings. Vedi [frontend/README.md](frontend/README.md).

## Layout

```
.
├── backend/           # Python (Alpaca, OpenAI, scheduler) + Dockerfile + .env.example + tests/ + data/
├── frontend/          # Next.js (App Router) + shadcn/ui + Recharts + TanStack Query
├── docker-compose.yml # backend ⇄ frontend su rete privata, frontend esposto via Traefik
└── README.md
```

## Avvio rapido

1. Crea il file `.env` del backend a partire dall'esempio:

   ```bash
   cp backend/.env.example backend/.env
   # Compila OpenAI / Alpaca, e impostazioni aziendali
   # ADMIN_USERNAME e ADMIN_PASSWORD sono usati SOLO al primo avvio per
   # creare l'utente admin iniziale; cambia la password subito dopo dalla UI.
   ```

2. Assicurati che la rete esterna `proxy_public` esista e che Traefik
   instradi l'host `trading.local` verso il container frontend.

3. Avvia lo stack:

   ```bash
   docker compose up -d --build
   ```

4. Apri `http://trading.local` e accedi con `ADMIN_USERNAME` /
   `ADMIN_PASSWORD`. Cambia subito la password dalla pagina Impostazioni.

## Topologia di rete

```
                     ┌──────────────────────────────┐
                     │           Internet           │
                     └──────────────┬───────────────┘
                                    │
                              proxy_public (Traefik)
                                    │
                                    ▼
                       ┌──────────────────────┐
                       │   frontend (Next.js) │  trading.local
                       │  /api/proxy/* → ⤵    │
                       └──────────┬───────────┘
                                  │
                          trading_internal (privata)
                                  │
                                  ▼
                       ┌──────────────────────┐
                       │   backend (FastAPI)  │  http://backend:8000
                       └──────────────────────┘
```

- Il backend è **solo** su `trading_internal`: non passa più da Traefik e
  non ha più un host pubblico.
- Il frontend è su entrambe le reti. Traefik lo espone a `trading.local`,
  e da lì le Route Handler `/api/proxy/[...path]/route.ts` proxyano ogni
  richiesta verso `BACKEND_INTERNAL_URL=http://backend:8000`.
- Il browser dell'utente parla **solo** col frontend: stesso origin, una
  sola cookie domain, niente CORS da configurare.
- I segreti (chiavi OpenAI/Alpaca, hash password, sessioni) vivono solo
  nel backend e non transitano mai via il browser.

## Autenticazione

- Cookie di sessione opaco `trading_session`, `httponly` + `samesite=lax`
  (Secure quando in produzione su HTTPS — vedi `SESSION_COOKIE_SECURE`).
- Sessioni tracciate in `data/app.sqlite` (`sessions`); si revocano in
  modo immediato (logout, reset password admin, disabilitazione utente)
  cancellando o segnando la riga.
- Ruoli: `admin` e `user`. Il prompt modifier e la gestione utenti sono
  riservati ad `admin`.
- Tutti gli endpoint (eccetto `/`, `/api/auth/login`) richiedono il
  cookie. Lo stream SSE dei log usa lo stesso cookie.

## Frontend pages

| Path | Auth | Contenuto |
|---|---|---|
| `/login` | pubblica | form di accesso |
| `/` | utente | dashboard: KPI, equity curve, PnL/simbolo, allocazione, distribuzione rendimenti, tabella ultimi trade |
| `/console` | utente | trade editabili (PATCH), legenda colonne, **trigger manuali admin-only** |
| `/reports` | utente | report JSON/PDF con cartelle virtuali, ricerca full-text JSON, anteprima PDF |
| `/prompts` | admin | editor degli 8 prompt GPT con storico versioni e rollback |
| `/logs` | utente | tail live SSE dei log del bot |
| `/settings` | utente (env tab admin-only) | parametri runtime + gestione utenti |

## Database e file

- `backend/data/trades.sqlite` — trade gestiti dal bot (immutato)
- `backend/data/market_data.sqlite` — OHLCV cache (immutato)
- `backend/data/app.sqlite` — **nuovo** DB applicativo:
  `users`, `sessions`, `app_settings`, `prompts`, `prompt_versions`,
  `report_folders`, `reports` (indice metadati), `audit_log`
- `backend/data/reports/` — report JSON e PDF su disco. Il bot scrive qui
  esattamente come prima; l'indice in `app.sqlite` viene riallineato a
  ogni `GET /api/reports`.

## Sviluppo locale fuori da Docker

Backend (Python 3.14):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # poi compila OpenAI/Alpaca + ADMIN_*
python main.py
```

Frontend (Node 22):

```bash
cd frontend
npm install
cp .env.example .env.local
# Imposta BACKEND_INTERNAL_URL=http://localhost:8000 quando il backend
# gira sulla tua macchina e non in Docker.
npm run dev
```

## Logica di trading

La logica del bot (universe selection, scheduler, GPT calls, lifecycle
trade, gestione TP/SL/TTP/TSL, report) **non è cambiata**. Vedi
[backend/README.md](backend/README.md) per il dettaglio. Le uniche
differenze osservabili dal bot:

- I prompt GPT vengono letti dall'`app.sqlite` (con fallback alle
  costanti `INSTRUCTIONS_*` di `clients/gpt_client.py`).
- I parametri operativi (`MAX_OPEN_TRADES_*`, `RISK_TOLERANCE`, ecc.)
  possono essere sovrascritti da overlay in `app_settings` senza
  riavvio (eccezione: `LOG_LEVEL`/`LOG_PROFILE`, marcati "restart
  required" dalla UI).
- L'API ora richiede autenticazione e i job manuali sono admin-only.
