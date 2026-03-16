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

Alpaca supporta ordini bracket con `take_profit` e `stop_loss`, ma non supporta un trailing stop come gamba nativa dello stesso bracket. Per questo il bot usa due modalita`:

- `BRACKET`: per i trade standard, il bot usa `LimitOrderRequest` con `order_class=BRACKET`, `take_profit` e `stop_loss`
- `TRAILING_STOP`: per i trade compatibili, il bot invia prima un ordine di ingresso semplice; dopo il fill piazza un `TrailingStopOrderRequest` separato lato broker

Limitazioni esplicite della modalita` `TRAILING_STOP`:

- il trailing stop e` un ordine singolo separato, quindi non esiste un take-profit broker-side collegato in OCO con lo stesso trailing stop
- `take_profit` resta quindi gestito dal bot e non da Alpaca come ordine linked
- `stop_loss` resta contesto strategico per GPT, mentre la protezione broker-side reale e` la distanza `trailing_stop_distance`
- i trailing stop Alpaca non sono validi come leg di bracket/OCO e non proteggono fuori regular trading hours
