# Analisi performance trade — 6→25 giugno 2026

> Dati: `backend/data/trades.sqlite` (107 trade) e `backend/data/app.sqlite`
> (1.664 snapshot equity). Logica: `backend/services/{trade_manager,portfolio_risk}.py`,
> `backend/clients/gpt_client.py`, `backend/core/utils.py`.

## 1. Sintesi numerica

| Metrica | Valore |
|---|---|
| Trade totali | 107 (61 chiusi, 9 aperti, 37 cancellati) |
| **PnL realizzato (61 chiusi)** | **−3.253 USD** |
| PnL non realizzato (9 aperti) | −1.669 USD |
| Win rate | 56% (34 W / 27 L) |
| Vincita media | +530 USD |
| Perdita media | −788 USD |
| **Reward/risk realizzato** | **0,67** (perdite > vincite) |
| Capitale investito (9 aperti) | 148.5k su ~164k equity (~91%) |

Per categoria: **CRYPTO −6.486** (43 trade) · **STOCK +3.233** (18 trade).
La crypto è il 60% dell'attività e la fonte di tutte le perdite.

> ⚠️ **Anomalia da verificare**: l'equity dell'account è salita da 150.3k
> (8 giu) a 163.8k (25 giu, +9%) mentre il ledger dei trade tracciati è
> netto −4.9k. La differenza (~+18k) non è spiegata dai trade tracciati
> (depositi? posizioni non tracciate? artefatti di riconciliazione?).
> Va verificata l'integrità del tracking prima di trarre conclusioni
> assolute sul PnL.

## 2. Diagnosi delle cause radice (dati alla mano)

### 2.1 L'edge pianificato NON viene catturato in uscita — causa #1
- **Reward/risk pianificato dal GPT: mediana 2,49 · media 2,60** (buono).
- **R realizzato medio: +0,06** (≈ breakeven, nessun edge catturato).
- **I vincitori catturano solo il 15–22% del movimento TP pianificato.
  Zero vincitori su 24 raggiungono l'80% del target.**
- R realizzato per motivo di chiusura:
  - `TRAILING_TAKE_PROFIT` (n=11): **+0,42R** ← arma presto e trail stretto
  - `MANUAL_CLOSE` (n=14): +0,68R
  - `STOP_LOSS` (n=2): −0,98R · `EXTERNAL_CLOSE` con SL (n=10): −0,89R

→ Il bot pianifica di rischiare 1R per fare 2,5R, ma il trailing-take-profit
si attiva troppo presto e trail troppo stretto, chiudendo i vincitori a
~0,4R mentre i perdenti vanno a stop pieno (−1R). Risultato: sistema
strutturalmente breakeven **prima** ancora del sizing.

### 2.2 Rischio in dollari per trade non normalizzato — causa #2
- Il sizing (`portfolio_risk.suggest_size`) è **vol-parity di portafoglio**,
  non basato sulla distanza dello stop. Quindi un −1R in dollari varia
  enormemente: da −16 a −2.867 USD.
- Posizioni: avg 8,8% equity, **max 24,3%** (cap `risk_max_position_pct=0.25`),
  7 trade > 15%.
- Conseguenza: il PnL in dollari è dominato dalla **varianza di sizing** —
  i perdenti hanno avuto size media maggiore (14.309) dei vincenti (12.257),
  trasformando un R medio ≈ 0 in −3.253 USD.
- I 5 peggiori trade da soli: **−10.800 USD** (HYPE, XLM, LLY, ETN, AMAT).

### 2.3 `confidence` e `trade_score` del GPT senza potere predittivo — causa #3
- I trade a confidence **0,76–0,82** (i "più sicuri") hanno perso di più:
  −1.461 e −1.345 di media.
- Bucket `trade_score 82–85`: **−6.814 USD** (il peggiore).
- Il GPT assegna confidence uniformemente alta (0,67–0,82) a tutto.
- Eppure questi valori sono usati per **ordinare** i segnali da aprire
  (`trade_manager._rank_signals`, sort per `(trade_score, confidence)`).

### 2.4 Solo LONG, crypto-pesante, nessun filtro di regime — causa #4
- `INSTRUCTIONS_NEW_SIGNAL`: "Use only LONG spot trading, never short".
  Direction hardcoded `'LONG'`.
- Nessun filtro di trend/regime **obbligatorio** a livello bot prima di
  aprire: la decisione è delegata interamente al giudizio del GPT.
- 30 trade chiusi `EXTERNAL_CLOSE` (−14.655): nel codice sono soprattutto
  **stop-loss eseguiti lato broker** — i prezzi di chiusura coincidono col
  livello SL (HYPE 61,8=61,8; GS 1001,1≈1001). "Stop-out clustering"
  tipico di ingressi contro-trend.
- Stop medio: CRYPTO 13,6% (max 21,5%), STOCK 6,7%. Le crypto hanno stop
  larghi (giusto, sono volatili) ma con size grande → perdite enormi in $.

### 2.5 35% di ordini cancellati — causa #5 (efficienza)
- 37 CANCELLED su 107 (22 stock, 15 crypto): ordini limite di ingresso
  scaduti (`crypto_pending_cancel_minutes=12`). Il bot decide l'entry ma
  spesso non riesce a entrare, sprecando cicli GPT.

## 3. Caveat statistico
Campione piccolo (61 chiusi in ~3 settimane): le **cifre** sono direzionali,
non statisticamente solide. I **difetti strutturali** (edge non catturato,
rischio-$ non normalizzato, confidence non calibrata, nessun filtro di
regime) sono però evidenti nel codice e nei dati a prescindere dalla varianza.

## 4. Leve di miglioramento (ordinate per impatto-$ stimato)

1. **Catturare l'edge in uscita** (§2.1): normalizzare deterministicamente i
   livelli TP/trailing su multipli di R, non fidarsi del GPT.
2. **Normalizzare il rischio-$ per trade** (§2.2): cap di sizing basato sulla
   distanza dello stop (rischio fisso % equity per trade).
3. **Filtro di regime/trend obbligatorio** + gestione crypto (§2.4).
4. **Smettere di usare confidence non calibrata** per ranking/sizing (§2.3).
5. **Osservabilità**: loggare R pianificato/realizzato, MFE/MAE, ATR (§tutte).
6. **Esecuzione ordini**: ridurre i CANCELLED (§2.5).

Il piano d'implementazione dettagliato è in
`docs/superpowers/plans/2026-06-25-trade-performance-improvements.md`.
</content>
</invoke>
