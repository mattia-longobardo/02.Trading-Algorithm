# Trading Algorithm

Sistema di trading algoritmico in Python per trading su eToro (Demo o Real), con analisi GPT via OpenAI `gpt-5.4`, persistenza SQLite, scheduler UTC e report settimanali.

## Componenti

- `main.py`: entry point che inizializza DB, client e scheduler
- `api/api_server.py`: API HTTP manuali e streaming dei log
- `clients/etoro_client.py`: wrapper eToro per account, ordini, posizioni e market data
- `clients/gpt_client.py`: integrazione OpenAI Responses API con web search obbligatoria
- `core/utils.py`: config, retry, serializzazione e utility condivise
- `core/logger.py`: log console + file con rotazione
- `core/db.py`: schema e helper SQLite
- `services/scheduler.py`: job APScheduler con lock file per evitare esecuzioni parallele
- `services/trade_manager.py`: sincronizzazione eToro, decisioni GPT in entrata e lifecycle script-managed dei trade
- `services/universe_manager.py`: selezione dell'universo attivo stock/crypto
- `services/data_manager.py`: download incrementale daily OHLCV su SQLite
- `services/report.py`: report JSON e PDF settimanale

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Compila `.env` con le tue chiavi OpenAI ed eToro. Per default il sistema usa l'account Demo eToro (ETORO_ACCOUNT_TYPE=demo).
La valuta di riferimento del bot e` configurabile con `CURRENCY` ed e` usata in modo coerente sia per stock sia per crypto. eToro riporta i saldi in USD; le crypto usano ticker nativi (es. BTC).
Il profilo di rischio utente e` configurabile con `RISK_TOLERANCE` da `1` a `10`: valori bassi rendono la selezione e i trade piu` conservativi, valori alti permettono setup piu` aggressivi.
L'orizzonte strategico e` configurabile con `STRATEGY_HORIZON_DAYS_MIN` e `STRATEGY_HORIZON_DAYS_MAX`. Di default il bot ragiona come position trader su circa 90-120 giorni, quindi non e` ottimizzato per il daily trading.
Gli ingressi sono limit emulati lato bot: `CRYPTO_ENTRY_MAX_CHASE_BPS` definisce la tolleranza sopra il target entro cui scatta il market open quando l'ask lo tocca, e `CRYPTO_PENDING_CANCEL_MINUTES` il tempo massimo di attesa prima di annullare un pending non riempito.
Il logging supporta due profili: `LOG_PROFILE=PRODUCTION` per log sintetici e orientati agli eventi principali, oppure `LOG_PROFILE=DEBUG` per mantenere il dettaglio completo durante troubleshooting.
I report vengono salvati in `REPORT_DIR`, che di default punta a `data/reports` cosi` resta scrivibile e persistente anche in Docker. Ogni generazione produce un file `.json` e un file `.pdf` formattato in modo professionale.

## Avvio

```bash
python main.py
```

Oltre allo scheduler, l'app espone una piccola API HTTP configurabile con `API_HOST` e `API_PORT` (default `0.0.0.0:8000`).

Il path `GET /` risponde con un JSON di health check (`{"status":"ok","service":"trading-backend"}`). La dashboard interattiva e il tail live dei log sono ora forniti dal frontend Next.js nella cartella `../frontend`, che consuma le API HTTP qui esposte.

Le origini consentite dal browser per le chiamate cross-origin sono configurabili con `CORS_ALLOWED_ORIGINS` (lista separata da virgole, `*` per disabilitare la lista bianca).

## API HTTP

Il server è ora basato su **FastAPI** (uvicorn). Tutti gli endpoint
richiedono autenticazione (cookie di sessione `trading_session`), con la
sola eccezione di `/` (health) e `POST /api/auth/login`. Gli endpoint
admin-only sono indicati di seguito.

### Auth

- `POST /api/auth/login` — body `{ username, password }`, imposta il cookie
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/auth/change-password` — body `{ current_password, new_password }`

### Utenti (admin)

- `GET /api/users`
- `POST /api/users` — `{ username, password, display_name, role }`
- `PATCH /api/users/{id}` — `{ display_name?, role?, disabled? }`
- `POST /api/users/{id}/reset-password`
- `DELETE /api/users/{id}`

### Trade

- `GET /api/trades?status=&category=&symbol=&from=&to=&page=&page_size=&sort=`
- `GET /api/trades/{id}`
- `PATCH /api/trades/{id}` — modifica solo i campi editabili
  (`target_entry_price`, `quantity`, `take_profit`,
  `trailing_take_profit_distance`, `trailing_take_profit_activation_pct`,
  `stop_loss`, `trailing_stop_distance`). La regola coppia per il
  trailing TP è validata server-side; ogni modifica viene scritta
  nell'audit log.

### Metriche e grafici

- `GET /api/metrics?window=...` (1D / 1W / 1M / 3M / 6M / YTD / 1Y / All
  o `from`/`to` ISO)
- `GET /api/equity-curve?window=...&granularity=daily|hourly`
- `GET /api/pnl-by-symbol?window=...`
- `GET /api/allocation`
- `GET /api/returns-distribution?window=...&bins=12`

### Report

- `GET /api/reports?folder_id=&type=&q=&from=&to=&full_text=`
- `GET /api/reports/{id}`
- `GET /api/reports/{id}/file` — binario PDF/JSON
- `GET /api/reports/{id}/json`
- `PATCH /api/reports/{id}` — `{ folder_id?, tags?, clear_folder? }`
- `GET /api/report-folders`
- `POST /api/report-folders` — `{ name, parent_id? }`
- `PATCH /api/report-folders/{id}` — `{ name?, parent_id? }`
- `DELETE /api/report-folders/{id}`

### Prompt (admin)

- `GET /api/prompts`
- `GET /api/prompts/{key}`
- `GET /api/prompts/{key}/versions`
- `POST /api/prompts/{key}` — `{ content, comment }` salva nuova versione e la attiva
- `POST /api/prompts/{key}/rollback` — `{ version_id }`

Chiavi valide: `new_signal`, `batch_signals`, `pending_review`,
`protection_review`, `universe_dossier`, `universe_shortlist`,
`universe_final`, `universe_final_from_dossiers`.

### Settings

- `GET /api/settings` — restituisce overlay attuale + flag `restart_required`
- `PATCH /api/settings` (admin) — body `{ key: value, ... }`

I segreti (`OPENAI_API_KEY`, `ETORO_API_KEY`, `ETORO_USER_KEY`) non
sono mai esposti via API: si modificano solo via `.env`.

### Audit log (admin)

- `GET /api/audit?actor=&entity=&from=&to=&page=&page_size=`

### Job manuali (admin)

- `GET /api/universe/generate`
- `GET /api/orders/generate`
- `GET /api/report/generate` (settimanale)
- `GET /api/report/quarterly`
- `GET /api/report/biannual`
- `GET /api/report/annual`
- `GET /api/scheduler/reset`

Tutti condividono lo stesso lock dello scheduler: rispondono con `409
Conflict` se un altro job è in esecuzione.

### Log

- `GET /api/logs?lines=...`
- `GET /api/logs/stream` (SSE)

## Application database (`data/app.sqlite`)

Distinto da `trades.sqlite` e `market_data.sqlite`. Tabelle:

| Tabella | Scopo |
|---|---|
| `users` | utenti con `password_hash` bcrypt e `role` admin/user |
| `sessions` | token cookie opachi con `expires_at` e `revoked_at` |
| `app_settings` | overlay JSON sui parametri di `AppConfig` |
| `prompts` + `prompt_versions` | storico versioni dei prompt GPT |
| `report_folders` | cartelle virtuali per i file in `REPORT_DIR` |
| `reports` | indice (filename, type, format, size, generated_at) |
| `audit_log` | log di tutte le mutazioni (login, edit trade, ...) |

Migrazioni automatiche all'avvio: `core.app_db.initialize_app_database`
crea le tabelle mancanti, `seed_admin_user_if_missing` crea l'admin
iniziale da `ADMIN_USERNAME`/`ADMIN_PASSWORD`,
`seed_initial_prompt_versions` semina la prima versione dei prompt
dalle costanti `INSTRUCTIONS_*` di `clients/gpt_client.py`.

## Variabili d'ambiente nuove

Oltre alle storiche (chiavi OpenAI/eToro, parametri trading), `.env`
ora supporta:

- `DB_APP` — path al DB applicativo (default `data/app.sqlite`)
- `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_DISPLAY_NAME` — usati solo
  alla **prima** inizializzazione del DB
- `SESSION_COOKIE_SECURE` — `true` quando il sito è servito su HTTPS
- `SESSION_COOKIE_SAMESITE` — default `lax`
- `CORS_ALLOWED_ORIGINS` — lasciare vuoto col proxy via Next.js Route
  Handler (raccomandato); valorizzare solo se si vuole esporre
  `api.trading.local` direttamente al browser

## Job schedulati

- Ogni minuto: sync stato ordini/posizioni eToro, valutazione dei pending (limit emulato lato bot) e gestione script-managed di TP, TTP, SL e TSL
- Ogni giorno `12:00 UTC`: revisione GPT dei trade `PENDING` piu` vecchi di 7 giorni; se il setup non vale piu` la pena viene annullato e chiuso
- 6 volte al giorno (3 per Milano, 3 per New York): analisi batch dell'universo corrente + apertura eventuali nuovi ordini ordinati per `trade_score`
  - **Milano** (orari CET=UTC+1): `07:30 UTC` (30 min prima apertura 08:00 UTC), `12:15 UTC` (meta` giornata), `16:00 UTC` (30 min prima chiusura 16:30 UTC)
  - **New York** (orari EST=UTC-5): `14:00 UTC` (30 min prima apertura 14:30 UTC), `17:45 UTC` (meta` giornata), `20:30 UTC` (30 min prima chiusura 21:00 UTC)
- Ogni domenica `22:00 UTC`: refresh settimanale dell'universo stock/crypto
- Ogni domenica `23:00 UTC`: report settimanale (PnL cumulativo di tutti i trade)
- Ogni `1° gen/apr/lug/ott 00:00 UTC`: report trimestrale del quarter appena concluso
- Ogni `1° gen/lug 00:30 UTC`: report semestrale del semestre appena concluso
- Ogni `1° gen 01:00 UTC`: report annuale dell'anno solare appena concluso

## Note operative

- Solo operazioni `LONG`
- Strategia di medio-lungo periodo: il modello cerca setup da position trading, non da daily trading
- Universe separato tra `STOCK` e `CRYPTO`, ricreato una volta a settimana
- Un solo trade attivo (`PENDING` o `OPEN`) per simbolo/coppia
- TP, trailing TP, SL e trailing stop sono gestiti internamente dal bot e salvati nel DB trade
- ETF esclusi nella selezione dell'universo
- Retry automatico su OpenAI ed eToro con backoff esponenziale
- Tutte le decisioni GPT richiedono web search
- La selezione settimanale dell'universo usa tutti i candidati eToro, applica un prefilter deterministico con metriche locali di mercato, genera dossier JSON paralleli per i candidati migliori con web search obbligatoria e poi consolida il risultato in una selezione finale
- L'analisi GPT dei segnali e` eseguita in batch per categoria, riducendo il numero di chiamate rispetto all'analisi simbolo per simbolo

## Logica ordini

- eToro viene usato solo per inviare l'ordine di ingresso e per chiudere la posizione a mercato
- Lo stato del trade (`PENDING`, `OPEN`, `CLOSED`, `CANCELLED`) viene mantenuto nello SQLite `trades`
- `CANCELLED` indica un ordine di ingresso mai eseguito e poi annullato/scaduto/rifiutato o cancellato dopo review GPT
- `CLOSED` indica invece un trade realmente aperto che e` poi stato chiuso
- Il bot salva e aggiorna `target_entry_price`, `entry_price`, `quantity`, `take_profit`, `trailing_take_profit_distance`, `trailing_take_profit_activation_pct`, `stop_loss`, `trailing_stop_distance`, `high_water_mark`, `trailing_take_profit_price`, `trailing_stop_price`, `exit_order_id` e timestamp rilevanti
- Gli ingressi sono limit emulati lato bot: alla creazione il trade resta `PENDING` con `target_entry_price` (livello GPT) e nessun ordine sul broker; a ogni tick il bot legge la quote live e, quando l'ask tocca il target entro la tolleranza `ENTRY_MAX_CHASE_BPS`, invia un market open su eToro (per importo USD, leva 1) con stop-loss e take-profit fissi come rete di sicurezza; i pending non riempiti entro `CRYPTO_PENDING_CANCEL_MINUTES` vengono annullati (solo stato DB)
- Quando un ordine di ingresso viene fillato, il trade passa a `OPEN`
- Ogni minuto il bot controlla prezzo corrente, trailing take profit, take profit, stop loss e trailing stop; se una regola scatta invia una chiusura a mercato via eToro e chiude il trade appena il fill viene confermato
- Il trailing take profit si arma quando il prezzo supera `entry_price * (1 + trailing_take_profit_activation_pct / 100)` (entrambi i campi `trailing_take_profit_distance` e `trailing_take_profit_activation_pct` sono scelti da GPT e devono essere entrambi positivi oppure entrambi `null`); una volta armato, segue il `high_water_mark` alla distanza specificata, indipendentemente dal raggiungimento del `take_profit`
- Due volte al giorno, durante i cicli GPT di valutazione segnali, il bot rivaluta `trailing_take_profit_distance` e `trailing_take_profit_activation_pct` dei trade aperti e li aggiorna se necessario, tipicamente abbassando la soglia di attivazione e/o stringendo la distanza man mano che il profitto cresce
