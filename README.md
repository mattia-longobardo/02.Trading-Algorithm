# Trading Algorithm

Sistema di trading algoritmico in Python per paper trading su Alpaca, con analisi GPT via OpenAI `gpt-4.1`, persistenza SQLite, scheduler UTC e report settimanali.

## Componenti

- `main.py`: entry point che inizializza DB, client e scheduler
- `scheduler.py`: job APScheduler con lock file per evitare esecuzioni parallele
- `gpt_client.py`: integrazione OpenAI Responses API con web search obbligatoria
- `alpaca_client.py`: wrapper Alpaca per account, ordini, posizioni e market data
- `data_manager.py`: download incrementale daily OHLCV su SQLite
- `trade_manager.py`: sincronizzazione Alpaca, decisioni GPT e lifecycle dei trade
- `universe_manager.py`: selezione settimanale dei simboli stock/crypto
- `report.py`: report JSON e testuale settimanale
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

## Avvio

```bash
python main.py
```

## Job schedulati

- Ogni giorno `00:01 UTC` e `12:01 UTC`: aggiornamento dati OHLCV
- Ogni giorno `00:10 UTC` e `12:10 UTC`: sync stato ordini Alpaca + analisi GPT
- Ogni lunedi `00:00 UTC`: refresh universe settimanale
- Ogni domenica `23:00 UTC`: report performance

## Note operative

- Solo operazioni `LONG`
- Universe separato tra `STOCK` e `CRYPTO`
- ETF esclusi nella selezione settimanale
- Retry automatico su OpenAI e Alpaca con backoff esponenziale
- Tutte le decisioni GPT richiedono web search

## Limite importante Alpaca

Alpaca supporta ordini bracket con `take_profit` e `stop_loss`, ma non supporta un trailing stop come gamba nativa dello stesso bracket. In questo progetto il valore `trailing_stop_distance` viene mantenuto nel DB e nella logica GPT, mentre gli ordini inviati a Alpaca usano il bracket supportato nativamente. Se vuoi una gestione trailing realmente autonoma lato broker, servirà una strategia alternativa o un broker/API che la supporti nella stessa struttura ordine.
