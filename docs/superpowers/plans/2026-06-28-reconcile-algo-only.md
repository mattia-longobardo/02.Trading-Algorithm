# Riconciliazione limitata ai trade dell'algoritmo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Far sì che la riconciliazione contro lo storico eToro corregga solo i trade gestiti dall'algoritmo (mai backfill di posizioni sconosciute), limiti la finestra al primo avvio reale dell'algoritmo, e pulisca all'avvio le righe già backfillate in passato.

**Architecture:** Tre modifiche al backend Python + una migrazione DB. (1) `reconcile_closed_trades` smette di inserire posizioni non presenti nel DB e le conteggia come `ignored_unmanaged`; `_backfill_closed_trade` viene rimossa. (2) Quando `min_date` è `None`, il cutoff è derivato da `MIN(open_timestamp)` dei trade dell'algoritmo; se non ce ne sono, la riconciliazione è no-op. (3) L'endpoint/scheduler manuale perde il parametro `lookback_days`. (4) Una migrazione idempotente in `initialize_databases` elimina le righe con `reasoning = 'Backfilled from eToro trade history'`.

**Tech Stack:** Python 3, SQLite (modulo `sqlite3`), unittest, FastAPI (endpoint admin), APScheduler.

## Global Constraints

- DB unico dei trade: `trades.sqlite`, tabella `trades` (`backend/core/db.py:34-75`).
- Marcatore **univoco** di riga backfillata: `reasoning = 'Backfilled from eToro trade history'`. `close_reason='EXTERNAL_CLOSE'` **non** è un marcatore (usato anche per trade legittimi dell'algoritmo chiusi esternamente).
- Helper DB esistenti: `fetch_one(db_path, query, params)` e `fetch_all(...)` ritornano righe dict-like; entrambi già importati in `trade_manager.py:17`.
- Test runner: `python -m unittest` dalla cartella `backend/`.
- Convenzione commit: messaggio in inglese, footer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: La riconciliazione non fa più backfill di posizioni sconosciute

**Files:**
- Modify: `backend/services/trade_manager.py` (`reconcile_closed_trades` 1404-1457; rimozione `_backfill_closed_trade` 1494-1534; import `get_instrument_by_id` riga 17)
- Test: `backend/tests/test_trade_reconciliation.py`
- Test: `backend/tests/test_reconcile_integration.py:77-79`

**Interfaces:**
- Consumes: `reconcile_closed_trades(*, min_date=..., provider=...)` esistente.
- Produces: `reconcile_closed_trades` ritorna un summary con chiavi `{"corrected", "ignored_unmanaged", "unchanged", "skipped_open"}` (rimossa `"backfilled"`). `_backfill_closed_trade` non esiste più.

- [ ] **Step 1: Aggiorna i test al nuovo comportamento (atteso fallire)**

In `backend/tests/test_trade_reconciliation.py` sostituisci il test `test_backfills_missing_closed_position` (righe 107-121) con:

```python
    def test_does_not_backfill_unknown_position(self):
        self.broker.list_trade_history.return_value = [
            hist("800", net_profit=271.49, close_rate=587.93, instrument_id=100000)
        ]
        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["ignored_unmanaged"], 1)
        self.assertNotIn("backfilled", summary)
        self.assertEqual(self._rows(position_id="800"), [])
```

Sostituisci `test_idempotent_no_duplicate_on_rerun` (righe 123-135) con:

```python
    def test_idempotent_no_duplicate_on_rerun(self):
        self._insert(position_id="900", pnl=20.89, close_price=63558.66)
        self.broker.list_trade_history.return_value = [
            hist("900", net_profit=537.80, close_rate=66393.87),
            hist("800", net_profit=271.49, close_rate=587.93),
        ]
        first = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        second = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(first["corrected"], 1)
        self.assertEqual(first["ignored_unmanaged"], 1)
        self.assertEqual(second["corrected"], 0)
        self.assertEqual(second["ignored_unmanaged"], 1)
        self.assertEqual(len(self._rows()), 1)
```

Sostituisci `test_unmapped_instrument_is_not_backfilled` (righe 148-154) con:

```python
    def test_unknown_instrument_position_is_ignored(self):
        self.broker.list_trade_history.return_value = [
            hist("801", net_profit=10.0, close_rate=5.0, instrument_id=999999)
        ]
        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["ignored_unmanaged"], 1)
        self.assertEqual(self._rows(position_id="801"), [])
```

In `test_no_broker_history_support_returns_empty_summary` (righe 156-161) sostituisci la riga
`self.assertEqual(summary["backfilled"], 0)` con
`self.assertEqual(summary["ignored_unmanaged"], 0)`.

In `backend/tests/test_reconcile_integration.py` sostituisci `test_metrics_realized_matches_broker_after_reconcile` (righe 72-84) con:

```python
    def test_metrics_realized_matches_broker_after_reconcile(self):
        before = self.metrics.compute_metrics(None, None)
        self.assertAlmostEqual(before["realized_pnl_abs"], 20.89, places=2)
        self.assertEqual(before["n_trades"], 1)

        summary = self.manager.reconcile_closed_trades(min_date="2026-06-01")
        self.assertEqual(summary["corrected"], 1)
        self.assertEqual(summary["ignored_unmanaged"], 1)

        after = self.metrics.compute_metrics(None, None)
        # Only the algorithm's own trade (900) is corrected to the broker value;
        # the unmanaged position (800) is ignored, never imported.
        self.assertAlmostEqual(after["realized_pnl_abs"], 537.80, places=2)
        self.assertEqual(after["n_trades"], 1)
```

(setUp di quel file semina già solo la posizione 900 nel DB e mette 900+800 nello storico broker; con il nuovo comportamento 800 non viene importata.)

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `cd backend && python -m unittest tests.test_trade_reconciliation -v`
Expected: FAIL (il codice attuale ancora fa backfill e ritorna la chiave `backfilled`).

- [ ] **Step 3: Implementa — niente più backfill in `reconcile_closed_trades`**

In `backend/services/trade_manager.py`:

Riga 1423, cambia:
```python
        summary = {"corrected": 0, "backfilled": 0, "unchanged": 0, "skipped_open": 0}
```
in:
```python
        summary = {"corrected": 0, "ignored_unmanaged": 0, "unchanged": 0, "skipped_open": 0}
```

Righe 1443-1446, cambia:
```python
            if row is None:
                if self._backfill_closed_trade(record, provider):
                    summary["backfilled"] += 1
                continue
```
in:
```python
            if row is None:
                # Position eToro non tracciata dall'algoritmo (storico precedente
                # all'avvio o trade aperto manualmente): mai importarla.
                summary["ignored_unmanaged"] += 1
                continue
```

Riga 1455, cambia:
```python
        if summary["corrected"] or summary["backfilled"]:
```
in:
```python
        if summary["corrected"]:
```

Aggiorna il docstring di `reconcile_closed_trades` (righe ~1410-1421): rimuovi le frasi su "backfill positions the bot never tracked at all" e "backfilled rows carry the position_id"; sostituisci con una nota che le posizioni non tracciate vengono ignorate. Testo proposto per il corpo del docstring:

```python
        """Make local closed trades match the broker's realized history.

        The local DB stores *estimated* close prices/PnL (the bot guesses the
        fill on external/manual closes). The broker's ``trade/history`` is the
        authoritative realized result, so for every closed position the bot
        already tracks we overwrite ``pnl``/``close_price``/``close_timestamp``
        when they drift.

        Positions present in the broker history but absent from the local DB are
        **ignored** (counted as ``ignored_unmanaged``): they belong to manual
        trades or to history predating the algorithm, and must never enter the
        dashboard. Returns a per-run counters summary.
        """
```

- [ ] **Step 4: Rimuovi `_backfill_closed_trade` e l'import inutilizzato**

Elimina interamente il metodo `_backfill_closed_trade` (righe 1494-1534).

Verifica che `get_instrument_by_id` non sia più usato:
Run: `cd backend && grep -n "get_instrument_by_id" services/trade_manager.py`
Se l'unico risultato è l'import a riga 17, modifica riga 17 da:
```python
from core.db import db_cursor, fetch_all, fetch_one, get_instrument_by_id
```
a:
```python
from core.db import db_cursor, fetch_all, fetch_one
```

- [ ] **Step 5: Esegui i test e verifica che passino**

Run: `cd backend && python -m unittest tests.test_trade_reconciliation tests.test_reconcile_integration -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_reconciliation.py backend/tests/test_reconcile_integration.py
git commit -m "fix(reconcile): never backfill unmanaged positions from eToro history

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Cutoff di riconciliazione derivato dai trade dell'algoritmo

**Files:**
- Modify: `backend/services/trade_manager.py` (`reconcile_closed_trades` 1428-1429; costante `RECONCILE_DEFAULT_LOOKBACK_DAYS` 1402; nuovo helper `_algorithm_start_cutoff`)
- Test: `backend/tests/test_trade_reconciliation.py`

**Interfaces:**
- Consumes: `fetch_one(db_path, query, params)` (già importato).
- Produces: nuovo metodo `TradeManager._algorithm_start_cutoff(self, provider: str) -> str | None` che ritorna l'ISO `open_timestamp` minimo dei trade del provider, o `None` se non esistono trade aperti. Quando `min_date is None`, `reconcile_closed_trades` usa questo cutoff e diventa no-op se è `None`.

- [ ] **Step 1: Scrivi i test (atteso fallire)**

Aggiungi a `backend/tests/test_trade_reconciliation.py` (classe `ReconciliationTests`):

```python
    def test_derived_cutoff_is_earliest_open_timestamp(self):
        self._insert(position_id="900", open_timestamp="2026-06-27T14:00:00Z")
        self._insert(position_id="901", open_timestamp="2026-06-10T09:00:00Z")
        self.broker.list_trade_history.return_value = []
        self.manager.reconcile_closed_trades()  # min_date=None -> derived
        self.broker.list_trade_history.assert_called_once_with("2026-06-10T09:00:00Z")

    def test_reconcile_is_noop_without_algorithm_trades(self):
        self.broker.list_trade_history.return_value = []
        summary = self.manager.reconcile_closed_trades()  # nessun trade in DB
        self.broker.list_trade_history.assert_not_called()
        self.assertEqual(summary["corrected"], 0)
        self.assertEqual(summary["ignored_unmanaged"], 0)
```

Nota: `_insert` (helper esistente, righe 61-74) crea righe `CLOSED` con `open_timestamp` di default `NULL` se non passato — passa `open_timestamp` esplicito nei test sopra.

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `cd backend && python -m unittest tests.test_trade_reconciliation.ReconciliationTests.test_derived_cutoff_is_earliest_open_timestamp tests.test_trade_reconciliation.ReconciliationTests.test_reconcile_is_noop_without_algorithm_trades -v`
Expected: FAIL (oggi `min_date=None` usa il lookback di 30 giorni e chiama sempre il broker).

- [ ] **Step 3: Implementa il cutoff derivato**

In `backend/services/trade_manager.py`, dentro `reconcile_closed_trades`, sostituisci righe 1428-1429:
```python
        if min_date is None:
            min_date = (utc_now() - timedelta(days=self.RECONCILE_DEFAULT_LOOKBACK_DAYS)).date()
```
con:
```python
        if min_date is None:
            min_date = self._algorithm_start_cutoff(provider)
            if min_date is None:
                # Nessun trade aperto dall'algoritmo: niente da riconciliare.
                return summary
```

Aggiungi il nuovo metodo subito dopo `reconcile_closed_trades` (prima di `_closed_trades_by_position_id`):
```python
    def _algorithm_start_cutoff(self, provider: str) -> str | None:
        """Earliest open_timestamp among the algorithm's own trades for a
        provider — the moment trading actually started. ``None`` if the
        algorithm has not opened any position yet."""
        row = fetch_one(
            self.config.db_trades,
            "SELECT MIN(open_timestamp) AS cutoff FROM trades "
            "WHERE provider = ? AND open_timestamp IS NOT NULL",
            (provider,),
        )
        return row["cutoff"] if row and row["cutoff"] else None
```

Rimuovi la costante ora inutilizzata `RECONCILE_DEFAULT_LOOKBACK_DAYS = 30` (riga 1402).

Verifica che `timedelta` sia ancora usato altrove in `trade_manager.py`:
Run: `cd backend && grep -n "timedelta" services/trade_manager.py`
Se non compaiono altri usi oltre all'import, rimuovi `timedelta` dall'import `from datetime import ...`. (Se compaiono altri usi, lascia l'import invariato.)

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `cd backend && python -m unittest tests.test_trade_reconciliation -v`
Expected: PASS (inclusi i test esistenti che passano `min_date` esplicito).

- [ ] **Step 5: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_reconciliation.py
git commit -m "feat(reconcile): derive cutoff from algorithm's first trade; no-op when none

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Rimuovi `lookback_days` dalla riconciliazione manuale

**Files:**
- Modify: `backend/services/scheduler.py` (`run_manual_reconcile_closed_trades` 284-300; import `timedelta` riga 10)
- Test: `backend/tests/test_scheduler_api.py:220-231`

**Interfaces:**
- Consumes: `trade_manager.reconcile_closed_trades(min_date=None, provider=...)` (cutoff derivato dal Task 2).
- Produces: `run_manual_reconcile_closed_trades(self) -> dict[str, Any]` senza parametri; ritorna `{"reconciled": {provider: summary, ...}}` (senza la chiave `lookback_days`).

- [ ] **Step 1: Aggiorna il test (atteso fallire)**

In `backend/tests/test_scheduler_api.py`, sostituisci `test_run_manual_reconcile_reconciles_each_provider` (righe 220-231) con:

```python
    def test_run_manual_reconcile_reconciles_each_provider(self) -> None:
        self.trade_manager.brokers = {"etoro": Mock()}
        self.trade_manager.reconcile_closed_trades.return_value = {"corrected": 2, "ignored_unmanaged": 3}

        result = self.scheduler.run_manual_reconcile_closed_trades()

        self.trade_manager.reconcile_closed_trades.assert_called_once()
        _, kwargs = self.trade_manager.reconcile_closed_trades.call_args
        self.assertEqual(kwargs["provider"], "etoro")
        self.assertIsNone(kwargs["min_date"])
        self.assertEqual(result["reconciled"]["etoro"], {"corrected": 2, "ignored_unmanaged": 3})
        self.assertNotIn("lookback_days", result)
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `cd backend && python -m unittest tests.test_scheduler_api.SchedulerTests.test_run_manual_reconcile_reconciles_each_provider -v`
(Se il nome della classe differisce, individua la classe con `grep -n "class .*Test" tests/test_scheduler_api.py` e usala.)
Expected: FAIL (oggi passa `min_date=<data lookback>` e include `lookback_days`).

- [ ] **Step 3: Implementa — rimuovi `lookback_days`**

In `backend/services/scheduler.py`, sostituisci `run_manual_reconcile_closed_trades` (righe 284-300) con:

```python
    def run_manual_reconcile_closed_trades(self) -> dict[str, Any]:
        """One-shot reconciliation across all brokers.

        Uses the algorithm's own start cutoff (earliest open trade) as the
        history window — never imports trades the algorithm did not open.
        """

        def execute() -> dict[str, Any]:
            results = {
                provider: self.trade_manager.reconcile_closed_trades(min_date=None, provider=provider)
                for provider in self.trade_manager.brokers
            }
            return {"reconciled": results}

        return self.run_with_lock("manual_reconcile_closed_trades", execute)
```

Verifica che `timedelta` sia ancora usato altrove in `scheduler.py`:
Run: `cd backend && grep -n "timedelta" services/scheduler.py`
Se l'unico risultato è l'import a riga 10, rimuovi quella riga (`from datetime import timedelta`).

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `cd backend && python -m unittest tests.test_scheduler_api -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/scheduler.py backend/tests/test_scheduler_api.py
git commit -m "refactor(reconcile): drop lookback_days from manual reconciliation

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Migrazione di pulizia — elimina all'avvio le righe già backfillate

**Files:**
- Modify: `backend/core/db.py` (`initialize_databases` 223-241; nuovo `_purge_backfilled_trades`)
- Test: `backend/tests/test_db_purge_backfilled.py` (nuovo)

**Interfaces:**
- Consumes: `initialize_databases(market_db_path, trades_db_path)` esistente (chiamato all'avvio del backend).
- Produces: nuova funzione modulo `_purge_backfilled_trades(connection: sqlite3.Connection) -> None`, invocata dentro `initialize_databases` dopo `_ensure_optional_trade_columns`. Idempotente.

- [ ] **Step 1: Scrivi il test (atteso fallire)**

Crea `backend/tests/test_db_purge_backfilled.py`:

```python
import sqlite3
import tempfile
import unittest
from pathlib import Path

from core.db import initialize_databases


def _insert(db, **over):
    cols = {
        "symbol": "BTC", "category": "CRYPTO", "status": "CLOSED",
        "entry_price": 1.0, "quantity": 1.0, "allocated_capital": 1.0,
        "position_id": "1", "provider": "etoro",
    }
    cols.update(over)
    keys = ",".join(cols)
    marks = ",".join("?" for _ in cols)
    conn = sqlite3.connect(db)
    conn.execute(f"INSERT INTO trades ({keys}) VALUES ({marks})", tuple(cols.values()))
    conn.commit()
    conn.close()


def _position_ids(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    rows = [r["position_id"] for r in conn.execute("SELECT position_id FROM trades")]
    conn.close()
    return set(rows)


class PurgeBackfilledTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.market_db = str(Path(self.tmp.name) / "m.sqlite")
        self.trades_db = str(Path(self.tmp.name) / "t.sqlite")
        initialize_databases(self.market_db, self.trades_db)

    def tearDown(self):
        self.tmp.cleanup()

    def test_purges_only_backfilled_rows_on_init(self):
        _insert(self.trades_db, position_id="algo", reasoning="LLM signal")
        _insert(self.trades_db, position_id="algo_ext", reasoning=None,
                close_reason="EXTERNAL_CLOSE")
        _insert(self.trades_db, position_id="bf",
                reasoning="Backfilled from eToro trade history")

        # Re-run init (idempotent migration) — should purge the backfilled row only.
        initialize_databases(self.market_db, self.trades_db)

        self.assertEqual(_position_ids(self.trades_db), {"algo", "algo_ext"})

    def test_purge_is_idempotent(self):
        _insert(self.trades_db, position_id="bf",
                reasoning="Backfilled from eToro trade history")
        initialize_databases(self.market_db, self.trades_db)
        initialize_databases(self.market_db, self.trades_db)
        self.assertEqual(_position_ids(self.trades_db), set())
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `cd backend && python -m unittest tests.test_db_purge_backfilled -v`
Expected: FAIL (la riga `bf` sopravvive: la migrazione non esiste ancora).

- [ ] **Step 3: Implementa la migrazione**

In `backend/core/db.py`, aggiungi la funzione subito dopo `_ensure_optional_trade_columns` (dopo riga 220):

```python
def _purge_backfilled_trades(connection: sqlite3.Connection) -> None:
    """One-time cleanup: drop rows that earlier runs imported from the broker's
    trade history. Identified by the unique backfill marker in ``reasoning``;
    legitimate algorithm trades (including externally-closed ones) are untouched.
    Idempotent."""
    cursor = connection.execute(
        "DELETE FROM trades WHERE reasoning = 'Backfilled from eToro trade history'"
    )
    cursor.close()
```

In `initialize_databases`, dentro il blocco `trade_conn` (righe 235-241), aggiungi la chiamata dopo `_ensure_optional_trade_columns(trade_conn)`:

```python
    trade_conn = _connect(trades_db_path)
    try:
        trade_conn.executescript(TRADES_SCHEMA)
        _ensure_optional_trade_columns(trade_conn)
        _purge_backfilled_trades(trade_conn)
        trade_conn.commit()
    finally:
        trade_conn.close()
```

- [ ] **Step 4: Esegui il test e verifica che passi**

Run: `cd backend && python -m unittest tests.test_db_purge_backfilled -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/core/db.py backend/tests/test_db_purge_backfilled.py
git commit -m "feat(db): purge previously backfilled trades on startup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Verifica finale dell'intera suite

**Files:** nessuna modifica (solo verifica).

- [ ] **Step 1: Esegui l'intera suite backend**

Run: `cd backend && python -m unittest discover -s tests -v`
Expected: PASS, nessun riferimento residuo a `backfilled`/`_backfill_closed_trade`.

- [ ] **Step 2: Grep di sicurezza per residui**

Run: `cd backend && grep -rn "backfilled\|_backfill_closed_trade\|lookback_days\|RECONCILE_DEFAULT_LOOKBACK_DAYS" --include="*.py" .`
Expected: nessun risultato in `services/`, `api/`, `core/`; eventuali occorrenze solo in commenti/test intenzionali. Se compare un residuo, correggilo e ri-committa nel task pertinente.
```
