# Frontend — Schermata "Rischio" (gestione + visione + what-if)

**Status:** approved (brainstorming) — 2026-06-07
**Branch/worktree:** `worktree-risk-screen` (`.claude/worktrees/risk-screen`), off `dev-2.0`.
**Context:** estende il [frontend rework eToro-only](./2026-06-05-frontend-trading-rework-design.md). Stack invariato: Next.js 15 / React 19 / Tailwind 4 / shadcn / Radix / React Query / Recharts. Locale italiano. Token semantici dark-first + `useChartTheme()`.

## Obiettivo

Aggiungere una schermata dedicata `/risk` che dà **visione** del rischio di portfolio (oggi calcolato dal backend ma non mostrato da nessuna parte nel frontend) e **gestione** (modifica limiti di rischio, modifica SL/TP/trailing per posizione, simulatore what-if apri/chiudi).

## Cosa il backend espone già (nessuna modifica necessaria, tranne 1 endpoint)

- `GET /api/risk` → `portfolio_risk_snapshot()` restituisce:
  `score` (0–100), `portfolio_vol`, `budget_vol`, `components{vol,concentration,correlation,exposure}` (ciascuno 0–100), `hhi`, `n_eff`, `avg_correlation`, `exposure` (0–1), `per_position_risk_contribution{SYMBOL: %}`, `equity`, `positions` (conteggio), `low_confidence`, `over_alert`, `over_hard`.
- `GET /api/live/stream` (SSE) → snapshot live: `equity`, `cash`, `positions[]` con `symbol, category, units, entry_price, current_price, unrealized_pnl, unrealized_pnl_pct, take_profit, stop_loss, position_id, instrument_id, is_buy`.
- `GET /api/allocation` → `by_category`, `by_symbol`, `currency`.
- `GET /api/trades?status=OPEN` → trade completi inclusi i campi trailing (`trailing_stop_distance`, `trailing_take_profit_distance`, `trailing_take_profit_activation_pct`, `trailing_stop_price`, `trailing_take_profit_price`, `high_water_mark`).
- `PATCH /api/settings` (admin) → modifica `max_open_trades_stock`, `max_open_trades_crypto`, `risk_tolerance`.
- `PATCH /api/trades/{id}` → modifica SL/TP/trailing per posizione (già usato da `edit-trade-dialog.tsx`).

**Soglie** (da `AppConfig`, non runtime-editabili): `risk_alert_threshold = 70`, `risk_hard_threshold = 85`. Esposte indirettamente via `over_alert`/`over_hard`. Le hard-codiamo nel frontend solo per le **fasce colore** del gauge (verde < 70 · ambra 70–85 · rosso ≥ 85); la logica di alert resta guidata dai flag del backend.

## A. Backend — nuovo endpoint what-if

### `POST /api/risk/project` (auth: user)

Thin wrapper su `PortfolioRiskService.assess/project/suggest_size` (già esistenti, puri, testati).

**Request body:**
```json
{
  "symbol": "AAPL",          // richiesto se si simula un'apertura; opzionale se solo chiusure
  "category": "STOCK",       // "STOCK" | "CRYPTO", default "STOCK"
  "value": 500.0,            // opzionale: valore USD della nuova posizione. Se assente → usa suggest_size()
  "close_symbols": ["BTC"]   // opzionale: simboli da rimuovere (chiusura simulata), case-insensitive
}
```

**Comportamento** (nuovo metodo `trade_manager.portfolio_risk_projection(symbol, category, value, close_symbols)`):
1. Recupera `equity`, `cash` dal broker e `positions = _open_position_values(provider)` (come fa già `portfolio_risk_snapshot`).
2. `current = assess(positions, equity)`.
3. `base = positions` meno le posizioni in `close_symbols` (match su `symbol.upper()`).
4. Se `symbol` presente:
   - se `value` assente → `suggested = suggest_size({symbol,category}, base, equity, cash)`; usa `suggested` come `value` (se 0 → nessuna apertura, solo chiusure).
   - `projected = project({symbol,category}, value, base, equity)` (cioè `assess(base + candidate, equity)`).
   - altrimenti `projected = assess(base, equity)`.
5. Restituisce:
```json
{
  "current":   { ...RiskSnapshot... },
  "projected": { ...RiskSnapshot... },
  "suggested_size": 480.0,        // 0 se non applicabile
  "delta": { "score": 6.2, "exposure": 0.05, "portfolio_vol": 0.01, "n_eff": -0.3 }
}
```
`RiskSnapshot` ha la stessa forma di `/api/risk` (riusa `assessment.to_dict()` + `equity` + `positions`).

**Validazione:** `category ∈ {STOCK,CRYPTO}`; `value` se presente `> 0`; almeno uno tra `symbol` e `close_symbols` non vuoto, altrimenti 400. Errori broker/equity≤0 → `current`/`projected` degradano a snapshot vuoto (come fa già `assess`), nessun 500.

**Test backend (Docker):** un file che monkeypatcha il broker/equity e il `history_provider`, verifica: (a) apertura con `value` esplicito alza `exposure`/`score`; (b) `value` assente ritorna `suggested_size > 0` e proietta su quella size; (c) `close_symbols` abbassa l'esposizione; (d) payload invalido → 400.

## B. Navigazione (7 → 8 voci)

In `src/components/layout/nav-items.ts`: nuova voce `{ href: "/risk", label: "Rischio", icon: ShieldAlert }` inserita tra **Posizioni** (`/positions`) e **Trade** (`/trades`). Verificare il comportamento della bottom-nav mobile (`bottom-nav.tsx` + foglio "Altro"): se la barra principale è limitata a N voci, "Rischio" entra tra le primarie (priorità alta) e una voce secondaria scala nel foglio "Altro". Aggiornare i test di `nav-items` e `bottom-nav`.

## C. Pagina `/risk` — layout

`src/app/risk/page.tsx` (client component). Desktop-first, responsive; su mobile le righe diventano stack verticale.

```
┌─ Rischio ─────────────────────────────────── [LiveBadge] ─┐
│  ⚠ StatusBanner se over_hard (error) / over_alert (warn)   │
├──────────────┬───────────────────┬─────────────────────────┤
│ ScoreGauge   │ Componenti (4)    │ Esposizione & Conc.     │
│ score 0–100  │ vol/conc/corr/exp │ exposure% invested/eq   │
│ fascia colore│ barre 0–100 +peso │ HHI · n_eff · avg_corr  │
│ residuo budg.│                   │ cash libero             │
├──────────────┴────────┬──────────┴─────────────────────────┤
│ Contributo rischio /  │ Posizioni & protezioni (live)      │
│ posizione (barre %)   │ vedi sotto                         │
├───────────────────────┴─────────────────────────────────────┤
│ Limiti di rischio (controlli — admin)                       │
├──────────────────────────────────────────────────────────────┤
│ Simulatore What-If (apri / chiudi)                          │
└──────────────────────────────────────────────────────────────┘
```

### Dati e refresh
- `useQuery(["risk"], GET /api/risk)`, ri-pollato sul **tick allineato al minuto** (≈ `:XX:30`).
  - Refactor: estrarre la logica di `useDashboardAutoRefresh` (in `src/app/page.tsx`) in un hook condiviso **`src/lib/use-minute-refresh.ts`** che invalida un set di query keys passato come argomento. Dashboard e Risk lo riusano. (Miglioramento mirato, non refactor gratuito: oggi quella logica è inline nella dashboard.)
- `useLiveStream()` (SSE esistente) per posizioni live, equity, cash, SL/TP → card esposizione e tabella protezioni in tempo reale.
- What-if: `useMutation` su `/api/risk/project`, on-demand (no polling).

### Stati
Loading → `Skeleton`; error su `/api/risk` → `StatusBanner`; nessuna posizione aperta → `EmptyState`. Badge "bassa confidenza" quando `low_confidence` (storico prezzi mancante per qualche holding).

## D. Componenti nuovi (`src/components/risk/`)

1. **`risk-score-gauge.tsx`** — gauge semicircolare (Recharts `RadialBarChart` o SVG) del `score` 0–100, colorato per fascia (verde `--color-accent` < 70 · ambra `--color-warning` 70–85 · rosso `--color-danger` ≥ 85). Mostra `score`, fascia testuale ("Sotto controllo / Attenzione / Critico") e residuo `hard_threshold − score`. Colori via `useChartTheme()` / token.

2. **`risk-components-breakdown.tsx`** — 4 barre orizzontali 0–100 per `vol`, `concentration`, `correlation`, `exposure`, con etichetta IT ("Volatilità", "Concentrazione", "Correlazione", "Esposizione") e tooltip che spiega ciascuna. Pesi mostrati se utili (i pesi non sono nell'API → etichetta generica, niente valori inventati).

3. **`exposure-concentration-card.tsx`** — `exposure` come % + barra (invested/equity), `equity`, `cash` (da SSE), `invested = equity·exposure`; `HHI`, `n_eff` ("posizioni efficaci"), `avg_correlation`. Numeri `.tnum`.

4. **`position-risk-contribution.tsx`** — barre orizzontali ordinate per `per_position_risk_contribution[SYMBOL]` (%), simbolo cliccabile → `/symbol/<sym>`. Vuoto se nessun contributo.

5. **`positions-risk-table.tsx`** — tabella delle posizioni **live** (da SSE), una riga per posizione:
   - `symbol` (link a `/symbol/<sym>`), `category`, valore (`units·current_price`) e % su invested;
   - **Protezioni**: badge di copertura — `SL`, `SL trail`, `TP`, `TP trail` (attivo/spento) ricavati dai campi del trade (`stop_loss`, `trailing_stop_distance`, `take_profit`, `trailing_take_profit_distance`);
   - **Stop effettivo & distanza**: stop più vicino tra `stop_loss` (hard) e `trailing_stop_price` (trailing live); mostra il livello e la **distanza %** dal `current_price` allo stop. Colora per vicinanza (rosso se molto vicino);
   - **Flag "scoperta"**: badge rosso quando né `stop_loss` né `trailing_stop_distance` sono valorizzati — segnale di rischio primario;
   - Azione **"Modifica SL/TP"** → riusa `edit-trade-dialog.tsx` (che già espone SL/TP **e tutti i campi trailing**, incluso reset `high_water_mark`). La tabella ha bisogno del `Trade` completo: i campi trailing non sono nello snapshot SSE, quindi la tabella incrocia lo snapshot live con `useQuery(["trades","OPEN"], GET /api/trades?status=OPEN)` (per `position_id`/`id`); il prezzo resta live dallo snapshot, i parametri trailing dal trade. Su salvataggio invalida sia `["trades","OPEN"]` sia `["risk"]`.

6. **`risk-limits-panel.tsx`** — controlli **admin** (riusa il pattern di `admin/env-form.tsx`): `max_open_trades_stock`, `max_open_trades_crypto`, `risk_tolerance` (1–10, slider o input). Mostra il `budget_vol` corrente (da `/api/risk`) come effetto del `risk_tolerance`. Salva via `PATCH /api/settings`, poi invalida `["risk"]`. Per non-admin: stessi valori **read-only** (niente form), recuperati da `GET /api/settings`. Gating ruolo via `useAuth()` (come fa già l'app).

7. **`what-if-simulator.tsx`** — form:
   - **Apertura**: `symbol` (input), `category` (select STOCK/CRYPTO), `value` (input USD) **oppure** toggle "Suggerisci size" (lascia `value` vuoto → backend usa `suggest_size`, e la size proposta viene mostrata).
   - **Chiusura**: multi-select dei simboli aperti correnti (da SSE) → `close_symbols`.
   - Invio → `POST /api/risk/project`. Mostra **score attuale ▸ proiettato** con delta colorato (verde se scende, rosso se sale) e i Δ di componenti/esposizione/`n_eff`. Se `over_hard` proiettato → banner "supererebbe la soglia hard". Reset facile.

## E. Tipi (`src/lib/types.ts`)

```ts
export interface RiskComponents { vol: number; concentration: number; correlation: number; exposure: number; }
export interface RiskSnapshot {
  score: number; portfolio_vol: number; budget_vol: number;
  components: RiskComponents; hhi: number; n_eff: number;
  avg_correlation: number; exposure: number;
  per_position_risk_contribution: Record<string, number>;
  equity: number; positions: number;
  low_confidence: boolean; over_alert: boolean; over_hard: boolean;
}
export interface RiskProjection {
  current: RiskSnapshot; projected: RiskSnapshot;
  suggested_size: number;
  delta: { score: number; exposure: number; portfolio_vol: number; n_eff: number };
}
```

## F. Test (vitest + RTL)

- `risk-score-gauge`: fascia/colore per score 50/75/90; testo residuo budget.
- `risk-components-breakdown`: 4 barre con valori e label corrette; clamp 0–100.
- `exposure-concentration-card`: rende exposure %, n_eff, avg_corr; gestisce equity 0 / cash mancante.
- `positions-risk-table`: badge copertura corretti; calcolo distanza-allo-stop e scelta stop più vicino; flag "scoperta" quando nessuno stop; apertura dialog.
- `what-if-simulator`: rende delta con segno/colore corretti dato un payload `RiskProjection` mockato; modalità "Suggerisci size".
- `risk-limits-panel`: read-only per non-admin, form per admin.
- `nav-items` / `bottom-nav`: nuova voce presente e ordinata.
- `use-minute-refresh`: invalida le query keys passate sul tick (test del refactor estratto).
- Backend Docker: `/api/risk/project` (casi A–D sopra).

## G. Out of scope (YAGNI)

- VaR / expected shortfall / stress scenari multipli (oltre what-if singolo).
- Matrice di correlazione a coppie (solo `avg_correlation` aggregata è esposta).
- Limiti di perdita giornaliera / drawdown limit (non esistono nel backend).
- Esposizione per settore/paese (non tracciata).
- Modifica delle soglie `risk_alert_threshold` / `risk_hard_threshold` (non runtime-editabili).

## H. Sequenza di build (per il piano di implementazione)

1. Backend: metodo `portfolio_risk_projection` + endpoint `POST /api/risk/project` + test Docker.
2. Tipi `RiskSnapshot`/`RiskProjection`; refactor `use-minute-refresh.ts` (dashboard invariata nel comportamento).
3. Nav: voce "Rischio" + test.
4. Componenti di sola lettura: gauge, breakdown, exposure/concentration, contribution + pagina che li monta su `/api/risk` + SSE.
5. `positions-risk-table` (incrocio SSE × `/api/trades?status=OPEN`) + riuso `edit-trade-dialog`.
6. `risk-limits-panel` (admin/read-only).
7. `what-if-simulator`.
8. Stati (skeleton/empty/error), a11y (aria-label, `scope="col"`), polish colori/token, `.tnum`.
9. Verifica: `vitest`, `tsc --noEmit`, `next build`; backend Docker test suite.
```
