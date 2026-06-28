# Riconciliazione limitata ai trade dell'algoritmo

**Data:** 2026-06-28
**Stato:** approvato in brainstorming, in attesa di review della spec

## Problema

La dashboard deve riflettere **solo** i risultati del trading algorithm. Oggi la
riconciliazione contro lo storico eToro tratta `trade/history` come fonte
autorevole e **re-inserisce** (backfill) qualunque posizione chiusa che non trova
nel DB locale. Conseguenze indesiderate:

1. Trade aperti **manualmente** su eToro compaiono in dashboard.
2. Trade **precedenti** al primo avvio dell'algoritmo compaiono in dashboard.
3. Se l'operatore cancella righe dal DB, al ciclo di riconciliazione successivo
   (ogni 30 min) vengono **re-inserite** — la cancellazione viene annullata.

Obiettivo: la riconciliazione deve continuare a **correggere i numeri** dei trade
gestiti dall'algoritmo usando i dati reali di eToro, ma **non** deve importare né
considerare trade non gestiti dall'algoritmo o precedenti al suo avvio.

## Contesto del codice (stato attuale)

- Tabella unica `trades` in `trades.sqlite` (`backend/core/db.py:34-75`).
- Solo **due** punti creano righe in `trades`:
  - `_save_new_trade` (`backend/services/trade_manager.py:534`) — l'algoritmo.
  - `_backfill_closed_trade` (`backend/services/trade_manager.py:1494-1534`) — il backfill.
- Le posizioni aperte manualmente **non** creano mai righe: `sync_open_trade`
  (`trade_manager.py:1312`) opera solo su trade già esistenti; `live_snapshot`
  usa il portfolio solo per la cassa. → l'unica porta d'ingresso per trade
  non-algoritmo è `_backfill_closed_trade`.
- `reconcile_closed_trades` (`trade_manager.py:1404-1457`): per ogni record dello
  storico eToro, se `position_id` non è nel DB → backfill; se c'è → corregge
  PnL/prezzo (`_apply_history_correction`).
- Default `min_date`: 30 giorni (job automatico) / 365 giorni (endpoint manuale).
- Job automatico: `scheduler.py:240-244`, schedulato ai minuti `5,35` di ogni ora
  (`scheduler.py:442-446`). Endpoint manuale admin: `/api/trades/reconcile`.
- `EXTERNAL_CLOSE` come `close_reason` **non** identifica i backfill: è usato anche
  per trade legittimi dell'algoritmo chiusi esternamente (`trade_manager.py:1167`).
  Il marcatore **univoco** di una riga backfillata è
  `reasoning = 'Backfilled from eToro trade history'`.
- Pattern migrazioni: `initialize_databases` (`core/db.py:223`) →
  `_ensure_optional_trade_columns` (`core/db.py:210`), eseguito all'avvio.

## Decisioni di design (confermate)

1. **Cutoff** = derivato dai trade dell'algoritmo (no env var, no config).
2. **Backfill** = mai. La riconciliazione corregge solo righe esistenti.
3. **Pulizia** delle righe già backfillate = migrazione automatica all'avvio.

## Design

### 1. Rimozione del backfill (requisito: niente trade manuali)

In `reconcile_closed_trades`, il ramo `if row is None:` non chiama più
`_backfill_closed_trade`: incrementa un contatore `ignored_unmanaged` e prosegue.

```python
row = existing.get(str(position_id))
if row is None:
    summary["ignored_unmanaged"] += 1
    continue
```

- `summary` diventa `{"corrected", "ignored_unmanaged", "unchanged", "skipped_open"}`
  (rimosso `backfilled`).
- `_backfill_closed_trade` viene **rimossa** (era l'unico chiamante).
- Comportamento risultante: la riconciliazione tocca solo trade che l'algoritmo ha
  aperto (hanno una riga locale), anche se poi chiusi manualmente/esternamente —
  che è il comportamento desiderato. Nessuna posizione sconosciuta entra nel DB.

### 2. Cutoff derivato (requisito: niente eventi pre-avvio)

Nuovo helper in `TradeManager`:

```python
def _algorithm_start_cutoff(self, provider: str) -> str | None:
    row = fetch_one(
        self.config.db_trades,
        "SELECT MIN(open_timestamp) AS cutoff FROM trades "
        "WHERE provider = ? AND open_timestamp IS NOT NULL",
        (provider,),
    )
    return row["cutoff"] if row and row["cutoff"] else None
```

In `reconcile_closed_trades`, quando `min_date is None`:

```python
if min_date is None:
    min_date = self._algorithm_start_cutoff(provider)
    if min_date is None:
        return summary  # nessun trade dell'algoritmo: niente da riconciliare
```

- Rimosso il fallback a `RECONCILE_DEFAULT_LOOKBACK_DAYS` (e la costante, se non
  più usata altrove).
- Entrambi i chiamanti passano `min_date=None` così usano il cutoff derivato:
  - Job automatico `job_reconcile_closed_trades` (già chiama senza argomenti).
  - `run_manual_reconcile_closed_trades` (`scheduler.py:284-300`): rimosso il
    calcolo `min_date = now - lookback_days`; passa `min_date=None`. Il parametro
    `lookback_days` viene eliminato (o reso ignorato per retro-compatibilità
    dell'endpoint — vedi Open Questions).
- Poiché ogni riga è un trade dell'algoritmo, `MIN(open_timestamp)` coincide con
  l'inizio reale dell'operatività e limita anche la finestra di fetch verso eToro.
- Nota: con il backfill rimosso, `min_date` influisce **solo** sulla dimensione
  della fetch dello storico, non sulla correttezza (i record non corrispondenti a
  righe locali vengono comunque ignorati). Il cutoff resta utile per non scaricare
  storico inutile.

### 3. Migrazione di pulizia una-tantum

Nuovo step in `initialize_databases` (`core/db.py`), eseguito all'avvio dopo
`_ensure_optional_trade_columns`:

```python
def _purge_backfilled_trades(connection: sqlite3.Connection) -> None:
    cur = connection.execute(
        "DELETE FROM trades WHERE reasoning = 'Backfilled from eToro trade history'"
    )
    cur.close()
```

- Idempotente: dopo la prima esecuzione non resta nulla da cancellare.
- Usa il marcatore **univoco** `reasoning = 'Backfilled from eToro trade history'`;
  non tocca le righe dell'algoritmo, comprese quelle con
  `close_reason='EXTERNAL_CLOSE'` legittime.
- Effetto immediato: al primo riavvio la dashboard smette di mostrare i "vecchi
  ordini ricomparsi" e i trade manuali importati in passato.

### 4. Test

- `backend/tests/test_trade_reconciliation.py`: i casi che oggi asseriscono il
  backfill (`summary["backfilled"]`) diventano casi che asseriscono lo skip
  (`summary["ignored_unmanaged"]`) e verificano che **nessuna** riga venga
  inserita per posizioni sconosciute.
- `backend/tests/test_reconcile_integration.py`: idem.
- Nuovo test: cutoff derivato — con righe a date diverse, `min_date` passato al
  client = `MIN(open_timestamp)`; con zero righe, la riconciliazione è no-op
  (nessuna chiamata a `list_trade_history`).
- Nuovo test: `_purge_backfilled_trades` elimina solo le righe con il `reasoning`
  marcatore e lascia intatte quelle dell'algoritmo (incluse `EXTERNAL_CLOSE`).
- `backend/tests/test_scheduler_api.py`: aggiornare l'asserzione su `min_date`
  nell'endpoint manuale per riflettere `min_date=None` / cutoff derivato.

## Conseguenza collaterale (positiva)

Il problema originale sparisce: cancellando un trade dal DB non verrà più
re-inserito, perché non esiste più alcun percorso di backfill.

## Out of scope (YAGNI)

- Nessuna env var / config per il cutoff (scelta: derivato).
- Nessuna whitelist/blacklist di `position_id`.
- Nessuna modifica al calcolo delle metriche/dashboard oltre all'effetto della
  pulizia dei dati.

## Decisioni risolte

- Endpoint manuale `/api/trades/reconcile`: il parametro `lookback_days` viene
  **rimosso** del tutto (endpoint interno/admin). `run_manual_reconcile_closed_trades`
  non accetta più `lookback_days` e chiama `reconcile_closed_trades(min_date=None)`.
