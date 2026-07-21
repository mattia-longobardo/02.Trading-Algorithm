# eToro Multi-Agent Trading Bot (v3)

Bot di **swing trading long-only** (solo stock ed ETF) su eToro. Il cuore è una
pipeline multi-agente **LangGraph**: agenti LLM (OpenAI) analizzano i candidati
e propongono operazioni; un **risk manager deterministico in codice puro**
approva o respinge; un executor idempotente invia gli ordini.

Principio fondante: nessun LLM può
autorizzare, dimensionare oltre i limiti o eseguire un ordine.

## Architettura

- `backend/` — FastAPI :8000 · pipeline LangGraph (reconcile → screener →
  4 analisti in parallelo → debate → portfolio manager → risk gate → executor →
  journal) · scheduler **sempre in UTC** (news 08:15, run 08:30, lun–ven) ·
  backtest TWR + benchmark SPY · risk score 1–10 · settings runtime con guardrail
- `frontend/` — Next.js 16 (App Router) + shadcn/ui, dark mode, 8 pagine
  (dashboard, run, portfolio, backtest, risk, knowledge, settings)
- `postgres` — PostgreSQL 18 (journal, registry posizioni bot, checkpoint LangGraph)
- `qdrant` — vector DB per RAG (news + trade memory, embeddings locali fastembed)
- `config/` — `risk_rules.yaml` (limiti), `settings.yaml` (default), `risk_score.yaml`
- `state/` — safety layer su file: `KILL_SWITCH` e `circuit_breaker.json`
  (funzionano anche a database giù)
- `knowledge_base/` — playbook e documenti ingeribili nella KB; i titoli
  impattati da un documento sono **rilevati automaticamente** dal contenuto
- `reports/` — report periodici generati a runtime, una cartella per utente

## Avvio

```bash
cp .env.example .env   # compila DB_TRADING_PASSWORD, TRADING_HOST, AUTH_*
docker compose up -d --build
```

Le migrazioni Alembic girano automaticamente all'avvio del backend.
UI su http://localhost:3000. Default sicuro: **ambiente demo**.

Le chiavi **eToro e OpenAI non stanno nel `.env`**: sono credenziali personali,
si inseriscono da *Impostazioni → Chiavi API personali* e il backend le cifra
con `AUTH_SECRET` su Postgres, legate alla tua identità Authentik.

## Sicurezza operativa

- **Kill switch**: file `state/KILL_SWITCH` o `ETORO_BOT_KILL=1` — controllato
  prima di ogni singolo ordine, mai disattivabile da un LLM.
- **Circuit breaker** persistente: blocca le aperture (mai le chiusure) per
  perdita giornaliera oltre soglia o perdite consecutive.
- **Solo trade del bot**: le posizioni aperte a mano su eToro sono ignorate
  ovunque (registry `bot_positions`).
- **Passaggio a `real`**: richiede chiavi eToro configurate, kill switch non
  attivo, circuit breaker non scattato e una conferma esplicita
  (enforced dal backend, 422 senza). Gli ordini approvati
  dal risk gate vengono sempre eseguiti per davvero, nell'ambiente scelto —
  non esiste una modalità dry-run separata.

## Fuso orario e valuta

Due impostazioni sono di **sola presentazione** e non toccano l'esecuzione:

- **Fuso orario** — l'orario della run è sempre UTC, così non si sposta con
  l'ora legale; la timezone scelta cambia solo come date e orari appaiono
  nell'app (barra in alto compresa).
- **Valuta** — eToro ragiona in dollari: il journal resta in USD e la
  conversione avviene al rendering, con i tassi di riferimento BCE
  ([Frankfurter](https://frankfurter.dev), nessuna API key). Se il tasso non è
  raggiungibile la UI mostra dollari e lo dichiara, invece di inventare un cambio.

## Sviluppo

```bash
cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[api,dev]"
.venv/bin/python -m pytest        # i test DB usano un Postgres 18 effimero via Docker
cd frontend && npm install && BACKEND_URL=http://localhost:8000 npm run dev
```

La reference dell'API eToro verificata via MCP è in `backend/docs/etoro_api.md`.
La specifica completa del progetto è in `CLAUDE.md`.
