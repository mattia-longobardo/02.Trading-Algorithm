# Trading Algorithm

Sistema di trading algoritmico in Python per paper trading su Alpaca, con analisi GPT via OpenAI `gpt-5.4`, persistenza SQLite, scheduler UTC e report settimanali.

## Componenti

- `main.py`: entry point che inizializza DB, client e scheduler
- `scheduler.py`: job APScheduler con lock file per evitare esecuzioni parallele
- `gpt_client.py`: integrazione OpenAI Responses API con web search obbligatoria
- `alpaca_client.py`: wrapper Alpaca per account, ordini, posizioni e market data
- `data_manager.py`: download incrementale daily OHLCV su SQLite
- `trade_manager.py`: sincronizzazione Alpaca, decisioni GPT in entrata e lifecycle script-managed dei trade
- `universe_manager.py`: selezione dell'universo attivo stock/crypto
- `report.py`: report JSON e PDF settimanale
- `db.py`: schema e helper SQLite
- `logger.py`: log console + file con rotazione
- `utils.py`: config, retry, serializzazione e utility condivise

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Compila `.env` con le tue chiavi OpenAI e Alpaca. Per default il sistema usa Alpaca Paper Trading.
La valuta di riferimento del bot e` configurabile con `CURRENCY` ed e` usata in modo coerente sia per stock sia per crypto. Per Alpaca crypto in pratica conviene usare `USD`.
Il profilo di rischio utente e` configurabile con `RISK_TOLERANCE` da `1` a `10`: valori bassi rendono la selezione e i trade piu` conservativi, valori alti permettono setup piu` aggressivi.
L'orizzonte strategico e` configurabile con `STRATEGY_HORIZON_DAYS_MIN` e `STRATEGY_HORIZON_DAYS_MAX`. Di default il bot ragiona come position trader su circa 90-120 giorni, quindi non e` ottimizzato per il daily trading.
Il logging supporta due profili: `LOG_PROFILE=PRODUCTION` per log sintetici e orientati agli eventi principali, oppure `LOG_PROFILE=DEBUG` per mantenere il dettaglio completo durante troubleshooting.
I report vengono salvati in `REPORT_DIR`, che di default punta a `data/reports` cosi` resta scrivibile e persistente anche in Docker. Ogni generazione produce un file `.json` e un file `.pdf` formattato in modo professionale.

## Avvio

```bash
python main.py
```

Oltre allo scheduler, l'app espone una piccola API HTTP configurabile con `API_HOST` e `API_PORT` (default `0.0.0.0:8000`).

Il path `GET /` mostra una vera pagina HTML minimale che visualizza le ultime `10000` righe del bot e riceve in streaming le nuove righe quando vengono aggiunte al file `LOG_FILE`, con aggiornamento live ogni secondo.

## API manuali

- `GET /api/universe/generate`: rigenera l'universo e aggiorna lo storico dei simboli monitorati; risponde solo con esito sintetico
- `GET /api/orders/generate`: fa partire manualmente lo stesso identico processo schedulato ogni giorno alle `00:10 UTC` e `12:10 UTC`; risponde solo con esito sintetico
- `GET /api/report/generate`: genera il report settimanale; risponde solo con esito sintetico
- `GET /api/logs`: restituisce il tail del file di log in JSON; di default usa `10000` righe e supporta `?lines=...`
- `GET /api/logs/stream`: stream SSE con le nuove righe del log in tempo reale

Le API usano lo stesso lock dello scheduler, quindi se un job e` gia` in esecuzione rispondono con `409 Conflict`.

## Job schedulati

- Ogni minuto: sync stato ordini/posizioni Alpaca e gestione script-managed di TP, SL e TSL
- Ogni giorno `12:00 UTC`: revisione GPT dei trade `PENDING` piu` vecchi di 7 giorni; se il setup non vale piu` la pena viene annullato e chiuso
- Ogni giorno `00:10 UTC` e `12:10 UTC`: analisi batch dell'universo corrente + apertura eventuali nuovi ordini ordinati per `trade_score`
- Ogni domenica `22:00 UTC`: refresh settimanale dell'universo stock/crypto
- Ogni domenica `23:00 UTC`: report performance

## Note operative

- Solo operazioni `LONG`
- Strategia di medio-lungo periodo: il modello cerca setup da position trading, non da daily trading
- Universe separato tra `STOCK` e `CRYPTO`, ricreato una volta a settimana
- Un solo trade attivo (`PENDING` o `OPEN`) per simbolo/coppia
- TP, SL e trailing stop sono gestiti internamente dal bot e salvati nel DB trade
- ETF esclusi nella selezione dell'universo
- Retry automatico su OpenAI e Alpaca con backoff esponenziale
- Tutte le decisioni GPT richiedono web search
- La selezione settimanale dell'universo usa tutti i candidati Alpaca: vengono analizzati in batch sequenziali e poi consolidati in una selezione finale
- L'analisi GPT dei segnali e` eseguita in batch per categoria, riducendo il numero di chiamate rispetto all'analisi simbolo per simbolo

## Logica ordini

- Alpaca viene usato solo per inviare l'ordine di ingresso e per chiudere la posizione a mercato
- Lo stato del trade (`PENDING`, `OPEN`, `CLOSED`, `CANCELLED`) viene mantenuto nello SQLite `trades`
- `CANCELLED` indica un ordine di ingresso mai eseguito e poi annullato/scaduto/rifiutato o cancellato dopo review GPT
- `CLOSED` indica invece un trade realmente aperto che e` poi stato chiuso
- Il bot salva e aggiorna `target_entry_price`, `entry_price`, `quantity`, `take_profit`, `stop_loss`, `trailing_stop_distance`, `high_water_mark`, `trailing_stop_price`, `exit_order_id` e timestamp rilevanti
- Quando un ordine di ingresso viene fillato, il trade passa a `OPEN`
- Ogni minuto il bot controlla prezzo corrente, take profit, stop loss e trailing stop; se una regola scatta invia una chiusura a mercato via Alpaca e chiude il trade appena il fill viene confermato
