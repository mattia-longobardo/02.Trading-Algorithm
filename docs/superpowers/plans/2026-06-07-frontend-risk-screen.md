# Schermata Rischio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungere una schermata `/risk` nel frontend che mostra il rischio di portfolio (score composito, componenti, esposizione, concentrazione, contributo per posizione, copertura protezioni) e permette di gestirlo (modifica limiti admin, modifica SL/TP/trailing per posizione, simulatore what-if apri/chiudi).

**Architecture:** Il backend calcola già il rischio (`PortfolioRiskService.assess/project/suggest_size`) ed espone `GET /api/risk`. Aggiungiamo un solo endpoint backend `POST /api/risk/project` (thin wrapper per il what-if). Il frontend consuma `/api/risk` (polling al minuto), `/api/live/stream` (SSE), `/api/trades?status=OPEN` (campi trailing) e riusa i componenti esistenti (`edit-trade-dialog`, `Card`, `StatusBanner`, `Skeleton`, `EmptyState`, `useChartTheme`).

**Tech Stack:** Backend: FastAPI, Pydantic, unittest (Docker). Frontend: Next.js 15, React 19, TypeScript, Tailwind 4, Recharts/SVG, React Query, Vitest + React Testing Library.

**Convenzioni:**
- Frontend test: `vitest` (globals attivi, jsdom). Esegui dal dir `frontend/`: `npx vitest run <path>`.
- Backend test: eseguiti in Docker. Esegui: `docker compose run --rm backend python -m pytest tests/<file> -v` (oppure il comando pytest del progetto). Mirror del pattern in `backend/tests/test_trade_manager_risk.py`.
- Tutti i numeri monetari/percentuali usano `.tnum` + helper di `src/lib/format.ts`. Colori solo da token semantici (`--color-accent/warning/danger/muted/text/line/panel`) o `useChartTheme()`. Locale **it-IT**.
- Commit dopo ogni task.

---

## File Structure

**Backend (modify):**
- `backend/services/trade_manager.py` — nuovo metodo `portfolio_risk_projection(...)`.
- `backend/api/api_server.py` — nuovo `RiskProjectPayload` + endpoint `POST /api/risk/project`.
- `backend/tests/test_trade_manager_risk.py` — test del nuovo metodo.

**Frontend (create):**
- `frontend/src/lib/risk.ts` — soglie, `riskBand`, `stopInfo`, `buildRiskRows`.
- `frontend/src/lib/use-minute-refresh.ts` — hook estratto (refresh al minuto).
- `frontend/src/components/risk/risk-score-gauge.tsx`
- `frontend/src/components/risk/risk-components-breakdown.tsx`
- `frontend/src/components/risk/exposure-concentration-card.tsx`
- `frontend/src/components/risk/position-risk-contribution.tsx`
- `frontend/src/components/risk/positions-risk-table.tsx`
- `frontend/src/components/risk/risk-limits-panel.tsx`
- `frontend/src/components/risk/what-if-simulator.tsx`
- `frontend/src/app/risk/page.tsx`
- Test affiancati in `__tests__/` per ciascun componente/lib.

**Frontend (modify):**
- `frontend/src/lib/types.ts` — `RiskComponents`, `RiskSnapshot`, `RiskProjection`.
- `frontend/src/components/layout/nav-items.ts` — voce "Rischio".
- `frontend/src/app/page.tsx` — usa `use-minute-refresh`.
- Test di nav esistenti aggiornati.

---

## Task 1: Backend — metodo `portfolio_risk_projection`

**Files:**
- Modify: `backend/services/trade_manager.py` (dopo `portfolio_risk_snapshot`, ~riga 360)
- Test: `backend/tests/test_trade_manager_risk.py`

- [ ] **Step 1: Scrivi i test (falliscono)**

Aggiungi in fondo a `backend/tests/test_trade_manager_risk.py`, prima di `if __name__`:

```python
class RiskProjectionTests(unittest.TestCase):
    OPEN = [{"symbol": "AAA", "category": "STOCK", "status": "OPEN",
             "quantity": 10, "current_price": 100.0,
             "allocated_capital": 1000.0, "provider": "etoro"}]
    HIST = {"AAA": _bars([10, 10.1, 9.9, 10.2, 10.0, 10.3]),
            "BBB": _bars([20, 20.4, 19.6, 20.8, 19.9, 20.5])}

    def test_projection_shape(self):
        tm, _ = _manager(history=self.HIST, open_trades=self.OPEN)
        out = tm.portfolio_risk_projection("BBB", "STOCK", 1000.0, None)
        self.assertEqual(set(out.keys()), {"current", "projected", "suggested_size", "delta"})
        for snap in (out["current"], out["projected"]):
            self.assertIn("score", snap)
            self.assertIn("exposure", snap)
            self.assertIn("equity", snap)
        self.assertEqual(set(out["delta"].keys()), {"score", "exposure", "portfolio_vol", "n_eff"})

    def test_opening_raises_exposure(self):
        tm, _ = _manager(history=self.HIST, open_trades=self.OPEN)
        out = tm.portfolio_risk_projection("BBB", "STOCK", 1000.0, None)
        self.assertGreater(out["projected"]["exposure"], out["current"]["exposure"])

    def test_value_absent_returns_suggested_size(self):
        tm, _ = _manager(history=self.HIST, open_trades=self.OPEN)
        out = tm.portfolio_risk_projection("BBB", "STOCK", None, None)
        self.assertGreater(out["suggested_size"], 0.0)

    def test_close_symbols_lowers_exposure(self):
        tm, _ = _manager(history=self.HIST, open_trades=self.OPEN)
        out = tm.portfolio_risk_projection(None, "STOCK", None, ["AAA"])
        self.assertLess(out["projected"]["exposure"], out["current"]["exposure"])

    def test_empty_when_no_equity(self):
        tm, _ = _manager(equity=0.0)
        out = tm.portfolio_risk_projection("BBB", "STOCK", 100.0, None)
        self.assertEqual(out["projected"]["score"], 0.0)
```

- [ ] **Step 2: Esegui i test — devono fallire**

Run: `docker compose run --rm backend python -m pytest tests/test_trade_manager_risk.py::RiskProjectionTests -v`
Expected: FAIL con `AttributeError: 'TradeManager' object has no attribute 'portfolio_risk_projection'`.

- [ ] **Step 3: Implementa il metodo**

In `backend/services/trade_manager.py`, subito dopo `portfolio_risk_snapshot` (riga ~360), aggiungi:

```python
    def portfolio_risk_projection(
        self,
        symbol: str | None,
        category: str = "STOCK",
        value: float | None = None,
        close_symbols: list[str] | None = None,
        provider: str = PROVIDER_ETORO,
    ) -> dict[str, Any]:
        """What-if: assess current vs. projected risk after opening/closing.

        Thin wrapper over the pure ``PortfolioRiskService``. Always returns a
        dict (degrades to empty assessments when equity/broker are unavailable).
        """
        broker = self.broker(provider)
        equity = 0.0
        cash = 0.0
        if broker is not None:
            try:
                equity = float(broker.get_account_equity())
            except Exception:
                equity = 0.0
            try:
                cash = float(broker.get_available_cash())
            except Exception:
                cash = 0.0
        try:
            positions = self._open_position_values(provider) if broker is not None else []
        except Exception:
            positions = []

        current = self.risk.assess(positions, equity)

        drop = {str(s).upper() for s in (close_symbols or [])}
        base = [p for p in positions if str(p.get("symbol") or "").upper() not in drop]

        suggested = 0.0
        sym = str(symbol).upper() if symbol else ""
        if sym:
            candidate = {"symbol": sym, "category": str(category or "STOCK")}
            size = value
            if size is None:
                suggested = self.risk.suggest_size(candidate, base, equity, cash)
                size = suggested
            if size and size > 0:
                projected = self.risk.project(candidate, float(size), base, equity)
            else:
                projected = self.risk.assess(base, equity)
        else:
            projected = self.risk.assess(base, equity)

        def _snap(assessment) -> dict[str, Any]:
            d = assessment.to_dict()
            d["equity"] = round(equity, 2)
            d["positions"] = len(base) + (1 if sym and (value or suggested) else 0)
            return d

        cur = current.to_dict()
        cur["equity"] = round(equity, 2)
        cur["positions"] = len(positions)
        proj = _snap(projected)
        return {
            "current": cur,
            "projected": proj,
            "suggested_size": round(float(suggested), 2),
            "delta": {
                "score": round(proj["score"] - cur["score"], 2),
                "exposure": round(proj["exposure"] - cur["exposure"], 4),
                "portfolio_vol": round(proj["portfolio_vol"] - cur["portfolio_vol"], 4),
                "n_eff": round(proj["n_eff"] - cur["n_eff"], 2),
            },
        }
```

- [ ] **Step 4: Esegui i test — devono passare**

Run: `docker compose run --rm backend python -m pytest tests/test_trade_manager_risk.py::RiskProjectionTests -v`
Expected: PASS (5 test).

- [ ] **Step 5: Commit**

```bash
git add backend/services/trade_manager.py backend/tests/test_trade_manager_risk.py
git commit -m "feat(risk): portfolio_risk_projection what-if method"
```

---

## Task 2: Backend — endpoint `POST /api/risk/project`

**Files:**
- Modify: `backend/api/api_server.py` (payload model vicino a `TradePatchPayload` ~riga 143; endpoint dopo `get_risk` ~riga 688)
- Test: `backend/tests/test_trade_manager_risk.py` (un test di validazione del payload, vedi sotto)

- [ ] **Step 1: Aggiungi il modello payload**

In `backend/api/api_server.py`, dopo `class TradePatchPayload(BaseModel): ...` (riga ~143), aggiungi:

```python
class RiskProjectPayload(BaseModel):
    symbol: str | None = None
    category: str = "STOCK"
    value: float | None = None
    close_symbols: list[str] | None = None

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        up = str(v or "STOCK").upper()
        if up not in {"STOCK", "CRYPTO"}:
            raise ValueError("category must be STOCK or CRYPTO")
        return up

    @field_validator("value")
    @classmethod
    def _positive_value(cls, v: float | None) -> float | None:
        if v is not None and v <= 0:
            raise ValueError("value must be > 0")
        return v
```

- [ ] **Step 2: Aggiungi l'endpoint**

In `backend/api/api_server.py`, subito dopo l'handler `get_risk` (riga ~688):

```python
    @app.post("/api/risk/project")
    def post_risk_project(
        payload: RiskProjectPayload,
        _user: auth_lib.AuthenticatedUser = Depends(get_current_user),
    ) -> dict[str, Any]:
        if not payload.symbol and not payload.close_symbols:
            raise HTTPException(status_code=400, detail="symbol or close_symbols required")
        return scheduler.trade_manager.portfolio_risk_projection(
            symbol=payload.symbol,
            category=payload.category,
            value=payload.value,
            close_symbols=payload.close_symbols,
        )
```

Verifica che `HTTPException` sia già importato in cima al file (lo è: usato altrove). Se non lo fosse, aggiungi `from fastapi import HTTPException`.

- [ ] **Step 3: Test di validazione del metodo (negativo)**

In `backend/tests/test_trade_manager_risk.py`, dentro `RiskProjectionTests`, aggiungi:

```python
    def test_close_only_no_symbol(self):
        tm, _ = _manager(history=self.HIST, open_trades=self.OPEN)
        out = tm.portfolio_risk_projection(None, "STOCK", None, ["AAA"])
        self.assertEqual(out["suggested_size"], 0.0)
        self.assertIn("score", out["projected"])
```

(La validazione "symbol o close_symbols obbligatori" e "category valida" è coperta dal modello Pydantic a livello HTTP; il metodo del manager resta tollerante.)

- [ ] **Step 4: Esegui i test — devono passare**

Run: `docker compose run --rm backend python -m pytest tests/test_trade_manager_risk.py -v`
Expected: PASS (tutti, inclusi i precedenti).

- [ ] **Step 5: Commit**

```bash
git add backend/api/api_server.py backend/tests/test_trade_manager_risk.py
git commit -m "feat(risk): POST /api/risk/project what-if endpoint"
```

---

## Task 3: Frontend — tipi del rischio

**Files:**
- Modify: `frontend/src/lib/types.ts` (in fondo)
- Test: `frontend/src/lib/__tests__/risk-types.test.ts`

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/lib/__tests__/risk-types.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import type { RiskSnapshot, RiskProjection } from "@/lib/types";

describe("risk types", () => {
  it("RiskSnapshot/RiskProjection compile and accept a sample payload", () => {
    const snap: RiskSnapshot = {
      score: 42, portfolio_vol: 0.2, budget_vol: 0.3,
      components: { vol: 30, concentration: 50, correlation: 40, exposure: 60 },
      hhi: 0.5, n_eff: 2, avg_correlation: 0.4, exposure: 0.6,
      per_position_risk_contribution: { AAA: 60, BBB: 40 },
      equity: 10000, positions: 2,
      low_confidence: false, over_alert: false, over_hard: false,
    };
    const proj: RiskProjection = {
      current: snap, projected: snap, suggested_size: 500,
      delta: { score: 1, exposure: 0.01, portfolio_vol: 0.001, n_eff: -0.2 },
    };
    expect(proj.current.score).toBe(42);
    expect(snap.components.vol).toBe(30);
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/lib/__tests__/risk-types.test.ts`
Expected: FAIL (type `RiskSnapshot` non esiste → errore di compilazione/transform).

- [ ] **Step 3: Aggiungi i tipi**

In fondo a `frontend/src/lib/types.ts`:

```ts
export interface RiskComponents {
  vol: number;
  concentration: number;
  correlation: number;
  exposure: number;
}

export interface RiskSnapshot {
  score: number;
  portfolio_vol: number;
  budget_vol: number;
  components: RiskComponents;
  hhi: number;
  n_eff: number;
  avg_correlation: number;
  exposure: number;
  per_position_risk_contribution: Record<string, number>;
  equity: number;
  positions: number;
  low_confidence: boolean;
  over_alert: boolean;
  over_hard: boolean;
}

export interface RiskProjection {
  current: RiskSnapshot;
  projected: RiskSnapshot;
  suggested_size: number;
  delta: { score: number; exposure: number; portfolio_vol: number; n_eff: number };
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/lib/__tests__/risk-types.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/__tests__/risk-types.test.ts
git commit -m "feat(risk): RiskSnapshot/RiskProjection types"
```

---

## Task 4: Frontend — utility di rischio (`lib/risk.ts`)

**Files:**
- Create: `frontend/src/lib/risk.ts`
- Test: `frontend/src/lib/__tests__/risk.test.ts`

- [ ] **Step 1: Scrivi i test (falliscono)**

Crea `frontend/src/lib/__tests__/risk.test.ts`:

```ts
import { describe, it, expect } from "vitest";
import {
  RISK_ALERT_THRESHOLD, RISK_HARD_THRESHOLD, riskBand, stopInfo, buildRiskRows,
} from "@/lib/risk";
import type { LivePosition, Trade } from "@/lib/types";

describe("riskBand", () => {
  it("classifies by thresholds", () => {
    expect(RISK_ALERT_THRESHOLD).toBe(70);
    expect(RISK_HARD_THRESHOLD).toBe(85);
    expect(riskBand(50)).toBe("calm");
    expect(riskBand(70)).toBe("warning");
    expect(riskBand(84.9)).toBe("warning");
    expect(riskBand(85)).toBe("critical");
  });
});

describe("stopInfo", () => {
  it("flags unprotected when no stops set", () => {
    const s = stopInfo({ currentPrice: 100, stopLoss: null, trailingStopDistance: null, trailingStopPrice: null });
    expect(s.unprotected).toBe(true);
    expect(s.effectiveStop).toBeNull();
    expect(s.distancePct).toBeNull();
  });
  it("uses the closest stop (max for a long) and computes distance %", () => {
    const s = stopInfo({ currentPrice: 100, stopLoss: 90, trailingStopDistance: 5, trailingStopPrice: 95 });
    expect(s.hasHardStop).toBe(true);
    expect(s.hasTrailingStop).toBe(true);
    expect(s.effectiveStop).toBe(95); // closest below current
    expect(s.distancePct).toBeCloseTo(5, 5);
    expect(s.unprotected).toBe(false);
  });
});

function trade(p: Partial<Trade>): Trade {
  return { id: 1, symbol: "AAA", category: "STOCK", direction: "BUY", status: "OPEN",
    entry_price: 90, target_entry_price: null, quantity: 10, allocated_capital: 900,
    take_profit: null, trailing_take_profit_distance: null, trailing_take_profit_activation_pct: null,
    stop_loss: null, trailing_stop_distance: null, high_water_mark: null,
    trailing_take_profit_price: null, trailing_stop_price: null, open_timestamp: null,
    close_timestamp: null, close_price: null, current_price: 100, pnl: null, realized_pnl: 0,
    unrealized_pnl: 100, close_reason: null, instrument_id: null, position_id: "p1",
    order_reference_id: null, reasoning: null, confidence: null, account_currency: "USD",
    created_at: "", updated_at: "", trade_score: null, ...p };
}
function live(p: Partial<LivePosition>): LivePosition {
  return { id: 1, symbol: "AAA", category: "STOCK", units: 10, entry_price: 90,
    current_price: 100, unrealized_pnl: 100, unrealized_pnl_pct: 11, take_profit: null,
    stop_loss: null, position_id: "p1", instrument_id: null, is_buy: true, ...p };
}

describe("buildRiskRows", () => {
  it("merges live × trade by id and computes value %", () => {
    const rows = buildRiskRows(
      [live({ id: 1, current_price: 100, units: 10 }), live({ id: 2, symbol: "BBB", current_price: 50, units: 10 })],
      [trade({ id: 1 }), trade({ id: 2, symbol: "BBB" })],
    );
    expect(rows).toHaveLength(2);
    const total = 100 * 10 + 50 * 10; // 1500
    expect(rows[0].valuePct).toBeCloseTo((1000 / total) * 100, 5);
    expect(rows[0].trade.id).toBe(1);
  });
  it("skips live positions without a matching trade", () => {
    const rows = buildRiskRows([live({ id: 9 })], [trade({ id: 1 })]);
    expect(rows).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/lib/__tests__/risk.test.ts`
Expected: FAIL (modulo `@/lib/risk` non esiste).

- [ ] **Step 3: Implementa `lib/risk.ts`**

Crea `frontend/src/lib/risk.ts`:

```ts
import type { LivePosition, Trade } from "@/lib/types";

/** Frontend mirror delle soglie backend (solo per fasce-colore; gli alert reali
 * arrivano dai flag over_alert/over_hard di /api/risk). */
export const RISK_ALERT_THRESHOLD = 70;
export const RISK_HARD_THRESHOLD = 85;

export type RiskBand = "calm" | "warning" | "critical";

export function riskBand(score: number): RiskBand {
  if (score >= RISK_HARD_THRESHOLD) return "critical";
  if (score >= RISK_ALERT_THRESHOLD) return "warning";
  return "calm";
}

export interface StopInfo {
  effectiveStop: number | null;
  distancePct: number | null;
  hasHardStop: boolean;
  hasTrailingStop: boolean;
  unprotected: boolean;
}

/** Calcola lo stop effettivo (il più vicino al prezzo) e la distanza %.
 * Il bot è long-only: per un long lo stop più vicino sotto il prezzo è il MAX
 * tra hard stop e trailing-stop price. */
export function stopInfo(args: {
  currentPrice: number | null;
  stopLoss: number | null;
  trailingStopDistance: number | null;
  trailingStopPrice: number | null;
}): StopInfo {
  const hasHardStop = args.stopLoss != null;
  const hasTrailingStop = args.trailingStopDistance != null;
  const candidates = [args.stopLoss, args.trailingStopPrice].filter(
    (v): v is number => v != null && !Number.isNaN(v) && v > 0,
  );
  const effectiveStop = candidates.length ? Math.max(...candidates) : null;
  const cp = args.currentPrice;
  const distancePct =
    cp != null && cp > 0 && effectiveStop != null ? ((cp - effectiveStop) / cp) * 100 : null;
  return {
    effectiveStop,
    distancePct,
    hasHardStop,
    hasTrailingStop,
    unprotected: !hasHardStop && !hasTrailingStop,
  };
}

export interface RiskPositionRow {
  trade: Trade;
  live: LivePosition;
  value: number;
  valuePct: number;
  stop: StopInfo;
}

/** Incrocia lo snapshot live (prezzo/valore freschi) con i trade aperti
 * (campi trailing) tramite l'id del trade. Salta le live senza trade. */
export function buildRiskRows(positions: LivePosition[], trades: Trade[]): RiskPositionRow[] {
  const byId = new Map(trades.map((t) => [t.id, t]));
  const rows: Array<Omit<RiskPositionRow, "valuePct"> & { value: number }> = [];
  for (const live of positions) {
    const trade = byId.get(live.id);
    if (!trade) continue;
    const price = live.current_price ?? trade.current_price ?? 0;
    const value = (live.units ?? 0) * price;
    rows.push({
      trade,
      live,
      value,
      stop: stopInfo({
        currentPrice: live.current_price,
        stopLoss: live.stop_loss ?? trade.stop_loss,
        trailingStopDistance: trade.trailing_stop_distance,
        trailingStopPrice: trade.trailing_stop_price,
      }),
    });
  }
  const total = rows.reduce((s, r) => s + r.value, 0);
  return rows.map((r) => ({ ...r, valuePct: total > 0 ? (r.value / total) * 100 : 0 }));
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/lib/__tests__/risk.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/risk.ts frontend/src/lib/__tests__/risk.test.ts
git commit -m "feat(risk): risk band + stop-distance + row-merge utils"
```

---

## Task 5: Frontend — hook `use-minute-refresh` (refactor condiviso)

**Files:**
- Create: `frontend/src/lib/use-minute-refresh.ts`
- Test: `frontend/src/lib/__tests__/use-minute-refresh.test.ts`
- Modify: `frontend/src/app/page.tsx` (sostituisce `useDashboardAutoRefresh`)

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/lib/__tests__/use-minute-refresh.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMinuteRefresh } from "@/lib/use-minute-refresh";
import type { ReactNode } from "react";

function wrapper(qc: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe("useMinuteRefresh", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("invalidates the given query keys on the aligned tick", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    renderHook(() => useMinuteRefresh(["risk", "metrics"]), { wrapper: wrapper(qc) });
    // advance past the next :XX:30 boundary (max 60s away)
    vi.advanceTimersByTime(61_000);
    expect(spy).toHaveBeenCalledWith({ queryKey: ["risk"] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["metrics"] });
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/lib/__tests__/use-minute-refresh.test.ts`
Expected: FAIL (modulo non esiste).

- [ ] **Step 3: Implementa l'hook (estratto da `page.tsx`)**

Crea `frontend/src/lib/use-minute-refresh.ts`:

```ts
"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

// Il cron ``monitor_trades`` del backend gira ogni minuto a ``:XX:00`` UTC.
// Allineiamo il tick client a ``:XX:30`` per leggere i prezzi aggiornati.
const REFRESH_OFFSET_SECONDS = 30;

/** Invalida periodicamente (≈ :XX:30) le query keys passate. Ritorna l'orario
 * dell'ultimo tick (o null). Estratto da useDashboardAutoRefresh. */
export function useMinuteRefresh(queryKeys: readonly string[]): Date | null {
  const qc = useQueryClient();
  const [lastTick, setLastTick] = useState<Date | null>(null);
  const keysSig = queryKeys.join(",");
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    function scheduleNext() {
      const now = new Date();
      const next = new Date(now);
      next.setSeconds(REFRESH_OFFSET_SECONDS, 0);
      if (next <= now) next.setMinutes(next.getMinutes() + 1);
      const delayMs = next.getTime() - now.getTime();
      timer = setTimeout(() => {
        for (const key of keysSig.split(",")) {
          qc.invalidateQueries({ queryKey: [key] });
        }
        setLastTick(new Date());
        scheduleNext();
      }, delayMs);
    }
    scheduleNext();
    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [qc, keysSig]);
  return lastTick;
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/lib/__tests__/use-minute-refresh.test.ts`
Expected: PASS.

- [ ] **Step 5: Refactor `page.tsx` per usare l'hook**

In `frontend/src/app/page.tsx`:
1. Rimuovi la funzione locale `useDashboardAutoRefresh` (righe ~55-80) e la costante `REFRESH_OFFSET_SECONDS` (righe ~53). Mantieni `DASHBOARD_QUERY_KEYS`.
2. Aggiungi import: `import { useMinuteRefresh } from "@/lib/use-minute-refresh";`
3. Sostituisci la riga `const lastAutoRefresh = useDashboardAutoRefresh();` con:
   `const lastAutoRefresh = useMinuteRefresh(DASHBOARD_QUERY_KEYS);`
4. Rimuovi gli import ora inutilizzati `useQueryClient` (se non più usato altrove nel file) — verifica con il typecheck.

- [ ] **Step 6: Verifica typecheck + test dashboard invariati**

Run: `npx tsc --noEmit && npx vitest run src/components/dashboard`
Expected: PASS, nessun errore di tipo.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/use-minute-refresh.ts frontend/src/lib/__tests__/use-minute-refresh.test.ts frontend/src/app/page.tsx
git commit -m "refactor(dashboard): extract useMinuteRefresh hook (shared with risk)"
```

---

## Task 6: Frontend — voce di navigazione "Rischio"

**Files:**
- Modify: `frontend/src/components/layout/nav-items.ts`
- Test: `frontend/src/components/layout/__tests__/nav-items.test.ts`

- [ ] **Step 1: Aggiorna il test (fallisce)**

In `frontend/src/components/layout/__tests__/nav-items.test.ts`, aggiungi un test (adatta agli helper già importati nel file):

```ts
import { NAV } from "@/components/layout/nav-items";

describe("NAV — voce Rischio", () => {
  it("include /risk con label Rischio, tra Posizioni e Trade", () => {
    const hrefs = NAV.map((i) => i.href);
    expect(hrefs).toContain("/risk");
    const risk = NAV.find((i) => i.href === "/risk");
    expect(risk?.label).toBe("Rischio");
    expect(hrefs.indexOf("/risk")).toBeGreaterThan(hrefs.indexOf("/positions"));
    expect(hrefs.indexOf("/risk")).toBeLessThan(hrefs.indexOf("/trades"));
  });
});
```

(Se il file usa già un blocco `describe`, inserisci solo l'`it` interno; non duplicare import esistenti.)

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/components/layout/__tests__/nav-items.test.ts`
Expected: FAIL (`/risk` non presente).

- [ ] **Step 3: Aggiungi la voce**

In `frontend/src/components/layout/nav-items.ts`:
1. Aggiungi `ShieldAlert` all'import da `lucide-react` (mantieni ordine alfabetico): inserisci `ShieldAlert,` dopo `Settings,`.
2. Inserisci nella lista `NAV`, tra `/positions` e `/trades`:
   `{ href: "/risk", label: "Rischio", icon: ShieldAlert },`

Risultato atteso di `NAV`:
```ts
export const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LineChart },
  { href: "/positions", label: "Posizioni", icon: Activity },
  { href: "/risk", label: "Rischio", icon: ShieldAlert },
  { href: "/trades", label: "Trade", icon: ClipboardList },
  { href: "/ops", label: "Operazioni", icon: Terminal },
  { href: "/universe", label: "Universe", icon: Globe },
  { href: "/reports", label: "Report", icon: FileText },
  { href: "/admin", label: "Amministrazione", icon: Settings },
];
```

`MOBILE_PRIMARY` resta `["/", "/positions", "/trades"]`: "Rischio" sarà tra le voci secondarie del foglio "Altro" (nessuna modifica alla bottom-nav richiesta).

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/components/layout/__tests__/nav-items.test.ts src/components/layout/__tests__/bottom-nav.test.tsx`
Expected: PASS (entrambi; bottom-nav non cambia comportamento).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/layout/nav-items.ts frontend/src/components/layout/__tests__/nav-items.test.ts
git commit -m "feat(risk): add Rischio nav item"
```

---

## Task 7: Frontend — `RiskScoreGauge`

**Files:**
- Create: `frontend/src/components/risk/risk-score-gauge.tsx`
- Test: `frontend/src/components/risk/__tests__/risk-score-gauge.test.tsx`

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/components/risk/__tests__/risk-score-gauge.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskScoreGauge } from "@/components/risk/risk-score-gauge";

describe("RiskScoreGauge", () => {
  it("renders the score and the calm band label", () => {
    render(<RiskScoreGauge score={42} budgetVol={0.3} hardThreshold={85} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/sotto controllo/i)).toBeInTheDocument();
  });
  it("shows the critical band when over hard threshold", () => {
    render(<RiskScoreGauge score={90} budgetVol={0.3} hardThreshold={85} />);
    expect(screen.getByText(/critico/i)).toBeInTheDocument();
  });
  it("rounds the score for display", () => {
    render(<RiskScoreGauge score={71.6} budgetVol={0.3} hardThreshold={85} />);
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText(/attenzione/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/components/risk/__tests__/risk-score-gauge.test.tsx`
Expected: FAIL (componente non esiste).

- [ ] **Step 3: Implementa il componente**

Crea `frontend/src/components/risk/risk-score-gauge.tsx`:

```tsx
"use client";

import { riskBand } from "@/lib/risk";
import { useChartTheme } from "@/components/charts/use-chart-theme";

const BAND_LABEL: Record<string, string> = {
  calm: "Sotto controllo",
  warning: "Attenzione",
  critical: "Critico",
};

export interface RiskScoreGaugeProps {
  score: number;
  budgetVol: number;
  hardThreshold: number;
}

export function RiskScoreGauge({ score, budgetVol, hardThreshold }: RiskScoreGaugeProps) {
  const theme = useChartTheme();
  const band = riskBand(score);
  const color =
    band === "critical" ? theme.negative : band === "warning" ? "#f59e0b" : theme.positive;

  // Semicerchio: 180° → 0°, raggio 80, centro (100,100).
  const R = 80;
  const CX = 100;
  const CY = 100;
  const arc = `M ${CX - R} ${CY} A ${R} ${R} 0 0 1 ${CX + R} ${CY}`;
  const L = Math.PI * R;
  const frac = Math.max(0, Math.min(1, score / 100));
  const remaining = Math.max(0, hardThreshold - score);

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 200 120" className="w-full max-w-[260px]" role="img" aria-label={`Rischio ${Math.round(score)} su 100`}>
        <path d={arc} fill="none" stroke={theme.grid} strokeWidth={14} strokeLinecap="round" />
        <path
          d={arc}
          fill="none"
          stroke={color}
          strokeWidth={14}
          strokeLinecap="round"
          strokeDasharray={`${frac * L} ${L}`}
        />
        <text x={CX} y={CY - 6} textAnchor="middle" fontSize={34} fontWeight={700} fill={theme.text}>
          {Math.round(score)}
        </text>
        <text x={CX} y={CY + 16} textAnchor="middle" fontSize={11} fill={theme.axis}>
          / 100
        </text>
      </svg>
      <div className="mt-1 text-center">
        <p className="text-sm font-semibold" style={{ color }}>
          {BAND_LABEL[band]}
        </p>
        <p className="text-xs text-(--color-muted)">
          Margine alla soglia critica: <span className="tnum">{remaining.toFixed(1)}</span> · vol budget{" "}
          <span className="tnum">{(budgetVol * 100).toFixed(0)}%</span>
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/components/risk/__tests__/risk-score-gauge.test.tsx`
Expected: PASS (3 test).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/risk/risk-score-gauge.tsx frontend/src/components/risk/__tests__/risk-score-gauge.test.tsx
git commit -m "feat(risk): RiskScoreGauge component"
```

---

## Task 8: Frontend — `RiskComponentsBreakdown`

**Files:**
- Create: `frontend/src/components/risk/risk-components-breakdown.tsx`
- Test: `frontend/src/components/risk/__tests__/risk-components-breakdown.test.tsx`

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/components/risk/__tests__/risk-components-breakdown.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskComponentsBreakdown } from "@/components/risk/risk-components-breakdown";

describe("RiskComponentsBreakdown", () => {
  const components = { vol: 30, concentration: 50, correlation: 40, exposure: 60 };

  it("renders all four Italian labels and values", () => {
    render(<RiskComponentsBreakdown components={components} />);
    expect(screen.getByText("Volatilità")).toBeInTheDocument();
    expect(screen.getByText("Concentrazione")).toBeInTheDocument();
    expect(screen.getByText("Correlazione")).toBeInTheDocument();
    expect(screen.getByText("Esposizione")).toBeInTheDocument();
    expect(screen.getByText("60")).toBeInTheDocument();
  });

  it("clamps bar width to 0-100", () => {
    render(<RiskComponentsBreakdown components={{ ...components, vol: 150 }} />);
    const bar = screen.getByTestId("risk-bar-vol");
    expect(bar.style.width).toBe("100%");
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/components/risk/__tests__/risk-components-breakdown.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implementa il componente**

Crea `frontend/src/components/risk/risk-components-breakdown.tsx`:

```tsx
"use client";

import type { RiskComponents } from "@/lib/types";

const ROWS: Array<{ key: keyof RiskComponents; label: string; hint: string }> = [
  { key: "vol", label: "Volatilità", hint: "Volatilità di portfolio rispetto al budget di rischio." },
  { key: "concentration", label: "Concentrazione", hint: "Quanto il capitale è concentrato in poche posizioni (HHI)." },
  { key: "correlation", label: "Correlazione", hint: "Correlazione media tra le posizioni: alta = poca diversificazione." },
  { key: "exposure", label: "Esposizione", hint: "Capitale investito rispetto all'equity totale." },
];

function clamp(v: number): number {
  return Math.max(0, Math.min(100, v));
}

export function RiskComponentsBreakdown({ components }: { components: RiskComponents }) {
  return (
    <ul className="space-y-3">
      {ROWS.map((r) => {
        const value = components[r.key] ?? 0;
        const w = clamp(value);
        return (
          <li key={r.key}>
            <div className="flex items-center justify-between text-sm">
              <span className="text-(--color-text)" title={r.hint}>{r.label}</span>
              <span className="tnum text-(--color-muted)">{Math.round(value)}</span>
            </div>
            <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-(--color-line)">
              <div
                data-testid={`risk-bar-${r.key}`}
                className="h-full rounded-full bg-(--color-accent)"
                style={{ width: `${w}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/components/risk/__tests__/risk-components-breakdown.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/risk/risk-components-breakdown.tsx frontend/src/components/risk/__tests__/risk-components-breakdown.test.tsx
git commit -m "feat(risk): RiskComponentsBreakdown component"
```

---

## Task 9: Frontend — `ExposureConcentrationCard`

**Files:**
- Create: `frontend/src/components/risk/exposure-concentration-card.tsx`
- Test: `frontend/src/components/risk/__tests__/exposure-concentration-card.test.tsx`

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/components/risk/__tests__/exposure-concentration-card.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ExposureConcentrationCard } from "@/components/risk/exposure-concentration-card";

describe("ExposureConcentrationCard", () => {
  it("renders exposure %, n_eff and avg correlation", () => {
    render(
      <ExposureConcentrationCard
        exposure={0.6} equity={10000} cash={4000} nEff={2.5} avgCorrelation={0.42} hhi={0.4}
        currency="USD"
      />,
    );
    expect(screen.getByText("60.0%")).toBeInTheDocument();
    expect(screen.getByText("2.5")).toBeInTheDocument(); // n_eff
    expect(screen.getByText("0.42")).toBeInTheDocument(); // avg corr
  });

  it("handles null cash gracefully", () => {
    render(
      <ExposureConcentrationCard
        exposure={0} equity={0} cash={null} nEff={0} avgCorrelation={0} hhi={0} currency="USD"
      />,
    );
    expect(screen.getByText("0.0%")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/components/risk/__tests__/exposure-concentration-card.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implementa il componente**

Crea `frontend/src/components/risk/exposure-concentration-card.tsx`:

```tsx
"use client";

import { formatCurrency } from "@/lib/format";

export interface ExposureConcentrationCardProps {
  exposure: number; // 0-1
  equity: number;
  cash: number | null;
  nEff: number;
  avgCorrelation: number;
  hhi: number;
  currency: string;
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="flex items-center justify-between">
      <dt className="text-(--color-muted)" title={hint}>{label}</dt>
      <dd className="tnum font-medium text-(--color-text)">{value}</dd>
    </div>
  );
}

export function ExposureConcentrationCard({
  exposure, equity, cash, nEff, avgCorrelation, hhi, currency,
}: ExposureConcentrationCardProps) {
  const invested = equity * exposure;
  const expPct = Math.max(0, Math.min(100, exposure * 100));
  return (
    <div className="space-y-3 text-sm">
      <div>
        <div className="flex items-center justify-between">
          <span className="text-(--color-muted)">Esposizione</span>
          <span className="tnum font-semibold text-(--color-text)">{expPct.toFixed(1)}%</span>
        </div>
        <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-(--color-line)">
          <div className="h-full rounded-full bg-(--color-info)" style={{ width: `${expPct}%` }} />
        </div>
        <p className="mt-1 text-xs text-(--color-muted)">
          Investito <span className="tnum">{formatCurrency(invested, currency)}</span> su equity{" "}
          <span className="tnum">{formatCurrency(equity, currency)}</span>
        </p>
      </div>
      <dl className="space-y-1.5">
        <Stat label="Liquidità" value={cash != null ? formatCurrency(cash, currency) : "—"} />
        <Stat label="Posizioni efficaci (n_eff)" value={nEff.toFixed(1)} hint="1 / HHI: numero equivalente di posizioni indipendenti." />
        <Stat label="Concentrazione (HHI)" value={hhi.toFixed(2)} hint="Herfindahl-Hirschman: 1 = tutto in una posizione." />
        <Stat label="Correlazione media" value={avgCorrelation.toFixed(2)} hint="Correlazione media a coppie tra le posizioni." />
      </dl>
    </div>
  );
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/components/risk/__tests__/exposure-concentration-card.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/risk/exposure-concentration-card.tsx frontend/src/components/risk/__tests__/exposure-concentration-card.test.tsx
git commit -m "feat(risk): ExposureConcentrationCard component"
```

---

## Task 10: Frontend — `PositionRiskContribution`

**Files:**
- Create: `frontend/src/components/risk/position-risk-contribution.tsx`
- Test: `frontend/src/components/risk/__tests__/position-risk-contribution.test.tsx`

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/components/risk/__tests__/position-risk-contribution.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PositionRiskContribution } from "@/components/risk/position-risk-contribution";

describe("PositionRiskContribution", () => {
  it("renders symbols sorted by contribution desc", () => {
    render(<PositionRiskContribution contributions={{ AAA: 30, BBB: 70 }} />);
    const items = screen.getAllByTestId("contrib-symbol").map((n) => n.textContent);
    expect(items[0]).toContain("BBB");
    expect(items[1]).toContain("AAA");
  });

  it("shows an empty hint with no contributions", () => {
    render(<PositionRiskContribution contributions={{}} />);
    expect(screen.getByText(/nessun/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/components/risk/__tests__/position-risk-contribution.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implementa il componente**

Crea `frontend/src/components/risk/position-risk-contribution.tsx`:

```tsx
"use client";

import Link from "next/link";

export function PositionRiskContribution({ contributions }: { contributions: Record<string, number> }) {
  const rows = Object.entries(contributions)
    .map(([symbol, pct]) => ({ symbol, pct }))
    .sort((a, b) => b.pct - a.pct);

  if (rows.length === 0) {
    return <p className="text-sm text-(--color-muted)">Nessun contributo di rischio (nessuna posizione aperta).</p>;
  }

  const max = Math.max(...rows.map((r) => Math.abs(r.pct)), 1);

  return (
    <ul className="space-y-2">
      {rows.map((r) => (
        <li key={r.symbol} className="flex items-center gap-3 text-sm">
          <Link
            href={`/symbol/${encodeURIComponent(r.symbol)}`}
            data-testid="contrib-symbol"
            className="w-16 shrink-0 truncate font-medium hover:underline"
          >
            {r.symbol}
          </Link>
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-(--color-line)">
            <div
              className="h-full rounded-full bg-(--color-accent)"
              style={{ width: `${(Math.abs(r.pct) / max) * 100}%` }}
            />
          </div>
          <span className="tnum w-12 shrink-0 text-right text-(--color-muted)">{r.pct.toFixed(1)}%</span>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/components/risk/__tests__/position-risk-contribution.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/risk/position-risk-contribution.tsx frontend/src/components/risk/__tests__/position-risk-contribution.test.tsx
git commit -m "feat(risk): PositionRiskContribution component"
```

---

## Task 11: Frontend — `PositionsRiskTable` (protezioni + edit dialog)

**Files:**
- Create: `frontend/src/components/risk/positions-risk-table.tsx`
- Test: `frontend/src/components/risk/__tests__/positions-risk-table.test.tsx`

Il componente è presentazionale: riceve `rows: RiskPositionRow[]` (già unite via `buildRiskRows`) e un callback `onEdit(trade)`. Mostra: simbolo (link), valore + %, badge di copertura (SL / SL trail / TP / TP trail), stop effettivo + distanza %, flag "scoperta", pulsante "Modifica". L'apertura del `Dialog`/`EditTradeDialog` è gestita dalla pagina (Task 14), come fa `app/trades/page.tsx`.

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/components/risk/__tests__/positions-risk-table.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PositionsRiskTable } from "@/components/risk/positions-risk-table";
import { buildRiskRows } from "@/lib/risk";
import type { LivePosition, Trade } from "@/lib/types";

function trade(p: Partial<Trade>): Trade {
  return { id: 1, symbol: "AAA", category: "STOCK", direction: "BUY", status: "OPEN",
    entry_price: 90, target_entry_price: null, quantity: 10, allocated_capital: 900,
    take_profit: null, trailing_take_profit_distance: null, trailing_take_profit_activation_pct: null,
    stop_loss: null, trailing_stop_distance: null, high_water_mark: null,
    trailing_take_profit_price: null, trailing_stop_price: null, open_timestamp: null,
    close_timestamp: null, close_price: null, current_price: 100, pnl: null, realized_pnl: 0,
    unrealized_pnl: 100, close_reason: null, instrument_id: null, position_id: "p1",
    order_reference_id: null, reasoning: null, confidence: null, account_currency: "USD",
    created_at: "", updated_at: "", trade_score: null, ...p };
}
function live(p: Partial<LivePosition>): LivePosition {
  return { id: 1, symbol: "AAA", category: "STOCK", units: 10, entry_price: 90,
    current_price: 100, unrealized_pnl: 100, unrealized_pnl_pct: 11, take_profit: null,
    stop_loss: null, position_id: "p1", instrument_id: null, is_buy: true, ...p };
}

describe("PositionsRiskTable", () => {
  it("flags an unprotected position", () => {
    const rows = buildRiskRows([live({ id: 1 })], [trade({ id: 1 })]); // no SL/TP
    render(<PositionsRiskTable rows={rows} onEdit={() => {}} />);
    expect(screen.getAllByText(/scoperta/i).length).toBeGreaterThan(0);
  });

  it("shows protection badges and stop distance when protected", () => {
    const rows = buildRiskRows(
      [live({ id: 1, stop_loss: 90 })],
      [trade({ id: 1, stop_loss: 90, take_profit: 120, trailing_stop_distance: 5, trailing_stop_price: 95 })],
    );
    render(<PositionsRiskTable rows={rows} onEdit={() => {}} />);
    expect(screen.getAllByText("SL").length).toBeGreaterThan(0);
    expect(screen.getAllByText("TP").length).toBeGreaterThan(0);
    // distanza dal prezzo (100) allo stop effettivo (95) = 5.0%
    expect(screen.getAllByText(/5\.0%/).length).toBeGreaterThan(0);
  });

  it("calls onEdit with the trade", async () => {
    const onEdit = vi.fn();
    const rows = buildRiskRows([live({ id: 1 })], [trade({ id: 1 })]);
    render(<PositionsRiskTable rows={rows} onEdit={onEdit} />);
    await userEvent.click(screen.getAllByRole("button", { name: /modifica/i })[0]);
    expect(onEdit).toHaveBeenCalledWith(rows[0].trade);
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/components/risk/__tests__/positions-risk-table.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implementa il componente**

Crea `frontend/src/components/risk/positions-risk-table.tsx`:

```tsx
"use client";

import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/format";
import type { RiskPositionRow } from "@/lib/risk";
import type { Trade } from "@/lib/types";

function CoverageBadge({ active, label, title }: { active: boolean; label: string; title: string }) {
  return (
    <span
      title={title}
      className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
        active
          ? "bg-(--color-accent)/15 text-(--color-accent)"
          : "bg-(--color-line) text-(--color-muted) line-through"
      }`}
    >
      {label}
    </span>
  );
}

function Coverage({ row }: { row: RiskPositionRow }) {
  const t = row.trade;
  return (
    <div className="flex flex-wrap gap-1">
      <CoverageBadge active={row.stop.hasHardStop} label="SL" title="Stop loss hard" />
      <CoverageBadge active={row.stop.hasTrailingStop} label="SL trail" title="Trailing stop" />
      <CoverageBadge active={t.take_profit != null} label="TP" title="Take profit" />
      <CoverageBadge active={t.trailing_take_profit_distance != null} label="TP trail" title="Trailing take profit" />
    </div>
  );
}

function StopCell({ row }: { row: RiskPositionRow }) {
  if (row.stop.unprotected) {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-(--color-danger)/15 px-1.5 py-0.5 text-xs font-medium text-(--color-danger)">
        <ShieldAlert className="size-3" /> Scoperta
      </span>
    );
  }
  const d = row.stop.distancePct;
  const near = d != null && d <= 3;
  return (
    <span className="tnum text-xs">
      {row.stop.effectiveStop != null ? formatNumber(row.stop.effectiveStop) : "—"}
      {d != null && (
        <span className={`ml-1 ${near ? "text-(--color-danger)" : "text-(--color-muted)"}`}>
          ({d.toFixed(1)}%)
        </span>
      )}
    </span>
  );
}

const HEADERS = ["Simbolo", "Valore", "Quota", "Protezioni", "Stop / dist.", ""] as const;

export function PositionsRiskTable({
  rows,
  onEdit,
}: {
  rows: RiskPositionRow[];
  onEdit: (trade: Trade) => void;
}) {
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={ShieldAlert}
        title="Nessuna posizione aperta"
        description="Quando il bot aprirà posizioni, qui vedrai le protezioni (SL/TP/trailing) e la distanza dallo stop."
      />
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-(--color-line)">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-(--color-line) bg-(--color-panel)/60">
            {HEADERS.map((h, i) => (
              <th
                key={h || `c${i}`}
                scope="col"
                className={`px-2 py-2 text-xs font-medium text-(--color-muted) ${i === 0 ? "text-left" : "text-left"}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.trade.id}
              className="bg-(--color-panel)/40 transition-colors hover:bg-(--color-hover)/60 [&>td]:border-y [&>td]:border-(--color-line)"
            >
              <td className="px-2 py-2 font-medium">
                <Link href={`/symbol/${encodeURIComponent(row.live.symbol)}`} className="hover:underline">
                  {row.live.symbol}
                </Link>
              </td>
              <td className="tnum px-2 py-2">{formatNumber(row.value, { maximumFractionDigits: 0 })}</td>
              <td className="tnum px-2 py-2 text-(--color-muted)">{row.valuePct.toFixed(1)}%</td>
              <td className="px-2 py-2"><Coverage row={row} /></td>
              <td className="px-2 py-2"><StopCell row={row} /></td>
              <td className="px-2 py-2 text-right">
                <Button variant="secondary" className="h-7 px-2 text-xs" onClick={() => onEdit(row.trade)}>
                  Modifica
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/components/risk/__tests__/positions-risk-table.test.tsx`
Expected: PASS (3 test).

Nota: se `@testing-library/user-event` non è installato, usa `fireEvent.click` da `@testing-library/react` (verifica con `grep user-event frontend/package.json`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/risk/positions-risk-table.tsx frontend/src/components/risk/__tests__/positions-risk-table.test.tsx
git commit -m "feat(risk): PositionsRiskTable with coverage badges + stop distance"
```

---

## Task 12: Frontend — `RiskLimitsPanel` (controlli admin)

**Files:**
- Create: `frontend/src/components/risk/risk-limits-panel.tsx`
- Test: `frontend/src/components/risk/__tests__/risk-limits-panel.test.tsx`

Il pannello legge `["settings"]` via React Query (riusa lo stesso query key di `EnvForm`, così l'invalidazione è condivisa), mostra `max_open_trades_stock`, `max_open_trades_crypto`, `risk_tolerance` e il `budgetVol` passato come prop. Editabile solo se `isAdmin`. Su salvataggio invalida `["settings"]` e `["risk"]`.

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/components/risk/__tests__/risk-limits-panel.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { RiskLimitsPanel } from "@/components/risk/risk-limits-panel";

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    get: vi.fn().mockResolvedValue({
      values: { max_open_trades_stock: 3, max_open_trades_crypto: 3, risk_tolerance: 5 },
      restart_required: false,
    }),
    patch: vi.fn().mockResolvedValue({ values: {}, restart_required: false }),
  },
}));

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("RiskLimitsPanel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the loaded limit values", async () => {
    wrap(<RiskLimitsPanel isAdmin budgetVol={0.3} />);
    await waitFor(() => expect(screen.getByDisplayValue("5")).toBeInTheDocument());
  });

  it("hides the save button for non-admins", async () => {
    wrap(<RiskLimitsPanel isAdmin={false} budgetVol={0.3} />);
    await waitFor(() => expect(screen.getByText(/solo gli amministratori/i)).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /salva/i })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/components/risk/__tests__/risk-limits-panel.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implementa il componente**

Crea `frontend/src/components/risk/risk-limits-panel.tsx`:

```tsx
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import type { SettingsResponse } from "@/lib/types";

const FIELDS: Array<{ key: string; label: string; hint: string }> = [
  { key: "max_open_trades_stock", label: "Max posizioni stock", hint: "Slot massimi attivi su azioni." },
  { key: "max_open_trades_crypto", label: "Max posizioni crypto", hint: "Slot massimi attivi su crypto." },
  { key: "risk_tolerance", label: "Tolleranza al rischio (1–10)", hint: "1 = conservativo, 10 = aggressivo. Determina il budget di volatilità." },
];

export function RiskLimitsPanel({ isAdmin, budgetVol }: { isAdmin: boolean; budgetVol: number }) {
  const qc = useQueryClient();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsResponse>("/api/settings"),
  });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!settings.data) return;
    const seed: Record<string, string> = {};
    for (const f of FIELDS) {
      const v = settings.data.values[f.key];
      seed[f.key] = v === null || v === undefined ? "" : String(v);
    }
    setDraft(seed);
  }, [settings.data]);

  const mutation = useMutation({
    mutationFn: () => {
      const payload: Record<string, number> = {};
      for (const f of FIELDS) {
        const raw = draft[f.key];
        if (raw === "" || raw === undefined) continue;
        const num = Number(raw);
        if (Number.isNaN(num)) throw new Error(`${f.label} non valido`);
        payload[f.key] = num;
      }
      return api.patch<SettingsResponse>("/api/settings", payload);
    },
    onSuccess: () => {
      setSuccess("Limiti salvati.");
      qc.invalidateQueries({ queryKey: ["settings"] });
      qc.invalidateQueries({ queryKey: ["risk"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        {FIELDS.map((f) => (
          <div key={f.key} className="space-y-1">
            <label className="text-xs uppercase text-(--color-muted)">{f.label}</label>
            <Input
              value={draft[f.key] ?? ""}
              onChange={(e) => setDraft((p) => ({ ...p, [f.key]: e.target.value }))}
              disabled={!isAdmin}
              inputMode="decimal"
            />
            <p className="text-xs text-(--color-muted)">{f.hint}</p>
          </div>
        ))}
      </div>
      <p className="text-xs text-(--color-muted)">
        Budget di volatilità attuale (da tolleranza):{" "}
        <span className="tnum font-medium text-(--color-text)">{(budgetVol * 100).toFixed(0)}%</span> annualizzato.
      </p>

      {error && <StatusBanner kind="error">{error}</StatusBanner>}
      {success && <StatusBanner kind="success">{success}</StatusBanner>}

      {isAdmin ? (
        <div className="flex justify-end">
          <Button
            onClick={() => {
              setError(null);
              setSuccess(null);
              mutation.mutate();
            }}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? "Salvataggio…" : "Salva limiti"}
          </Button>
        </div>
      ) : (
        <p className="text-xs text-(--color-muted)">Solo gli amministratori possono modificare i limiti.</p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/components/risk/__tests__/risk-limits-panel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/risk/risk-limits-panel.tsx frontend/src/components/risk/__tests__/risk-limits-panel.test.tsx
git commit -m "feat(risk): RiskLimitsPanel admin controls"
```

---

## Task 13: Frontend — `WhatIfSimulator`

**Files:**
- Create: `frontend/src/components/risk/what-if-simulator.tsx`
- Test: `frontend/src/components/risk/__tests__/what-if-simulator.test.tsx`

Form: modalità apertura (symbol + category + value | "Suggerisci size") e chiusura (multi-select dei simboli aperti). Invio → `POST /api/risk/project`. Mostra score attuale ▸ proiettato + delta colorato.

- [ ] **Step 1: Scrivi il test (fallisce)**

Crea `frontend/src/components/risk/__tests__/what-if-simulator.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { WhatIfSimulator } from "@/components/risk/what-if-simulator";
import type { RiskProjection } from "@/lib/types";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  api: { post: vi.fn() },
}));

const PROJ: RiskProjection = {
  current: { score: 40 } as RiskProjection["current"],
  projected: { score: 52 } as RiskProjection["projected"],
  suggested_size: 480,
  delta: { score: 12, exposure: 0.05, portfolio_vol: 0.01, n_eff: -0.3 },
};

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("WhatIfSimulator", () => {
  beforeEach(() => vi.clearAllMocks());

  it("submits an open scenario and renders the delta", async () => {
    (api.post as ReturnType<typeof vi.fn>).mockResolvedValue(PROJ);
    wrap(<WhatIfSimulator openSymbols={["AAA"]} />);
    fireEvent.change(screen.getByLabelText(/simbolo/i), { target: { value: "BBB" } });
    fireEvent.change(screen.getByLabelText(/valore/i), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: /simula/i }));
    await waitFor(() => expect(screen.getByText(/\+12\.0/)).toBeInTheDocument());
    expect(api.post).toHaveBeenCalledWith("/api/risk/project", expect.objectContaining({ symbol: "BBB", value: 1000 }));
  });
});
```

- [ ] **Step 2: Esegui — fallisce**

Run: `npx vitest run src/components/risk/__tests__/what-if-simulator.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implementa il componente**

Crea `frontend/src/components/risk/what-if-simulator.tsx`:

```tsx
"use client";

import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBanner } from "@/components/ui/status-banner";
import { ApiError, api } from "@/lib/api";
import type { RiskProjection, TradeCategory } from "@/lib/types";

function signed(value: number, digits = 1): string {
  const prefix = value > 0 ? "+" : "";
  return `${prefix}${value.toFixed(digits)}`;
}

/** Per lo score, un delta negativo è "buono" (verde). */
function deltaClass(value: number): string {
  if (value > 0) return "text-(--color-danger)";
  if (value < 0) return "text-(--color-accent)";
  return "text-(--color-muted)";
}

export function WhatIfSimulator({ openSymbols }: { openSymbols: string[] }) {
  const [symbol, setSymbol] = useState("");
  const [category, setCategory] = useState<TradeCategory>("STOCK");
  const [value, setValue] = useState("");
  const [suggest, setSuggest] = useState(false);
  const [closeSymbols, setCloseSymbols] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { category };
      if (symbol.trim()) body.symbol = symbol.trim().toUpperCase();
      if (!suggest && value.trim()) {
        const num = Number(value);
        if (Number.isNaN(num) || num <= 0) throw new Error("Valore non valido");
        body.value = num;
      }
      if (closeSymbols.length) body.close_symbols = closeSymbols;
      if (!body.symbol && !closeSymbols.length) throw new Error("Inserisci un simbolo da aprire o seleziona posizioni da chiudere");
      return api.post<RiskProjection>("/api/risk/project", body);
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : (err as Error).message),
  });

  const result = mutation.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-1">
          <label htmlFor="wi-symbol" className="text-xs uppercase text-(--color-muted)">Simbolo (apri)</label>
          <Input id="wi-symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="es. AAPL" />
        </div>
        <div className="space-y-1">
          <label htmlFor="wi-cat" className="text-xs uppercase text-(--color-muted)">Categoria</label>
          <select
            id="wi-cat"
            className="h-9 w-full rounded-lg border border-(--color-line) bg-(--color-panel)/50 px-3 text-sm text-(--color-text)"
            value={category}
            onChange={(e) => setCategory(e.target.value as TradeCategory)}
          >
            <option value="STOCK">STOCK</option>
            <option value="CRYPTO">CRYPTO</option>
          </select>
        </div>
        <div className="space-y-1">
          <label htmlFor="wi-value" className="text-xs uppercase text-(--color-muted)">Valore (USD)</label>
          <Input
            id="wi-value"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            disabled={suggest}
            inputMode="decimal"
            placeholder={suggest ? "auto" : "es. 1000"}
          />
          <label className="flex items-center gap-1 text-xs text-(--color-muted)">
            <input type="checkbox" checked={suggest} onChange={(e) => setSuggest(e.target.checked)} />
            Suggerisci size
          </label>
        </div>
        {openSymbols.length > 0 && (
          <div className="space-y-1">
            <label className="text-xs uppercase text-(--color-muted)">Chiudi (simulato)</label>
            <div className="flex flex-wrap gap-1">
              {openSymbols.map((s) => {
                const on = closeSymbols.includes(s);
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() =>
                      setCloseSymbols((prev) => (on ? prev.filter((x) => x !== s) : [...prev, s]))
                    }
                    className={`rounded px-2 py-1 text-xs ${
                      on ? "bg-(--color-danger)/20 text-(--color-danger)" : "bg-(--color-line) text-(--color-muted)"
                    }`}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <Button
          onClick={() => {
            setError(null);
            mutation.mutate();
          }}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? "Calcolo…" : "Simula"}
        </Button>
      </div>

      {error && <StatusBanner kind="error">{error}</StatusBanner>}

      {result && (
        <div className="rounded-xl border border-(--color-line) bg-(--color-panel)/40 p-4">
          <div className="flex items-center justify-center gap-4 text-center">
            <div>
              <p className="text-xs text-(--color-muted)">Score attuale</p>
              <p className="tnum text-2xl font-semibold">{result.current.score.toFixed(0)}</p>
            </div>
            <span className="text-(--color-muted)">▸</span>
            <div>
              <p className="text-xs text-(--color-muted)">Proiettato</p>
              <p className="tnum text-2xl font-semibold">{result.projected.score.toFixed(0)}</p>
            </div>
            <div className={`tnum text-lg font-semibold ${deltaClass(result.delta.score)}`}>
              {signed(result.delta.score)}
            </div>
          </div>
          {result.suggested_size > 0 && (
            <p className="mt-2 text-center text-xs text-(--color-muted)">
              Size suggerita: <span className="tnum">{result.suggested_size.toFixed(0)} USD</span>
            </p>
          )}
          {result.projected.over_hard && (
            <StatusBanner kind="error">Supererebbe la soglia di rischio critica.</StatusBanner>
          )}
          <dl className="mt-3 grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <dt className="text-(--color-muted)">Δ Esposizione</dt>
              <dd className={`tnum ${deltaClass(result.delta.exposure)}`}>{signed(result.delta.exposure * 100)}%</dd>
            </div>
            <div>
              <dt className="text-(--color-muted)">Δ Volatilità</dt>
              <dd className={`tnum ${deltaClass(result.delta.portfolio_vol)}`}>{signed(result.delta.portfolio_vol * 100)}%</dd>
            </div>
            <div>
              <dt className="text-(--color-muted)">Δ n_eff</dt>
              <dd className={`tnum ${deltaClass(-result.delta.n_eff)}`}>{signed(result.delta.n_eff)}</dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Esegui — passa**

Run: `npx vitest run src/components/risk/__tests__/what-if-simulator.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/risk/what-if-simulator.tsx frontend/src/components/risk/__tests__/what-if-simulator.test.tsx
git commit -m "feat(risk): WhatIfSimulator (open/close projection)"
```

---

## Task 14: Frontend — pagina `/risk` (assemblaggio)

**Files:**
- Create: `frontend/src/app/risk/page.tsx`

La pagina monta tutti i componenti, recupera i dati e gestisce il dialog di modifica (come `app/trades/page.tsx`).

- [ ] **Step 1: Implementa la pagina**

Crea `frontend/src/app/risk/page.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBanner } from "@/components/ui/status-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { LiveBadge } from "@/components/live/live-badge";
import { EditTradeDialog } from "@/components/trades/edit-trade-dialog";
import { RiskScoreGauge } from "@/components/risk/risk-score-gauge";
import { RiskComponentsBreakdown } from "@/components/risk/risk-components-breakdown";
import { ExposureConcentrationCard } from "@/components/risk/exposure-concentration-card";
import { PositionRiskContribution } from "@/components/risk/position-risk-contribution";
import { PositionsRiskTable } from "@/components/risk/positions-risk-table";
import { RiskLimitsPanel } from "@/components/risk/risk-limits-panel";
import { WhatIfSimulator } from "@/components/risk/what-if-simulator";
import { useLiveStream } from "@/lib/use-live-stream";
import { useMinuteRefresh } from "@/lib/use-minute-refresh";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { buildRiskRows, RISK_HARD_THRESHOLD } from "@/lib/risk";
import type { RiskSnapshot, Trade } from "@/lib/types";
import { useQueryClient } from "@tanstack/react-query";

export default function RiskPage() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const { snapshot, status } = useLiveStream();
  useMinuteRefresh(["risk"]);
  const [editing, setEditing] = useState<Trade | null>(null);

  const risk = useQuery({
    queryKey: ["risk"],
    queryFn: () => api.get<RiskSnapshot>("/api/risk"),
  });
  const openTrades = useQuery({
    queryKey: ["trades", "OPEN"],
    queryFn: () => api.get<{ items: Trade[] }>("/api/trades?status=OPEN&page_size=200"),
  });

  const r = risk.data;
  const currency = snapshot?.currency ?? "USD";
  const rows = buildRiskRows(snapshot?.positions ?? [], openTrades.data?.items ?? []);
  const openSymbols = rows.map((row) => row.live.symbol);

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold">Rischio</h1>
          <p className="text-sm text-(--color-muted)">
            Rischio di portfolio in tempo reale: score composito, esposizione, concentrazione e protezioni.
          </p>
        </div>
        <LiveBadge status={status} />
      </header>

      {risk.isError && (
        <StatusBanner kind="error">
          Impossibile caricare i dati di rischio. Riprova o controlla la connessione al backend.
        </StatusBanner>
      )}
      {r?.over_hard ? (
        <StatusBanner kind="error">Rischio di portfolio CRITICO: lo score ha superato la soglia hard.</StatusBanner>
      ) : r?.over_alert ? (
        <StatusBanner kind="warning">Attenzione: lo score di rischio ha superato la soglia di alert.</StatusBanner>
      ) : null}
      {r?.low_confidence && (
        <StatusBanner kind="info">
          Bassa confidenza: storico prezzi insufficiente per alcune posizioni; i valori usano volatilità di default.
        </StatusBanner>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader><CardTitle>Score di rischio</CardTitle></CardHeader>
          <CardContent>
            {risk.isLoading || !r ? (
              <Skeleton className="h-32 w-full rounded-lg" />
            ) : (
              <RiskScoreGauge score={r.score} budgetVol={r.budget_vol} hardThreshold={RISK_HARD_THRESHOLD} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Componenti</CardTitle></CardHeader>
          <CardContent>
            {risk.isLoading || !r ? (
              <Skeleton className="h-32 w-full rounded-lg" />
            ) : (
              <RiskComponentsBreakdown components={r.components} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Esposizione & concentrazione</CardTitle></CardHeader>
          <CardContent>
            {risk.isLoading || !r ? (
              <Skeleton className="h-32 w-full rounded-lg" />
            ) : (
              <ExposureConcentrationCard
                exposure={r.exposure}
                equity={snapshot?.equity ?? r.equity}
                cash={snapshot?.cash ?? null}
                nEff={r.n_eff}
                avgCorrelation={r.avg_correlation}
                hhi={r.hhi}
                currency={currency}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Contributo di rischio per posizione</CardTitle></CardHeader>
          <CardContent>
            {risk.isLoading || !r ? (
              <Skeleton className="h-40 w-full rounded-lg" />
            ) : (
              <PositionRiskContribution contributions={r.per_position_risk_contribution} />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Posizioni & protezioni</CardTitle></CardHeader>
          <CardContent>
            <PositionsRiskTable rows={rows} onEdit={setEditing} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Limiti di rischio</CardTitle></CardHeader>
        <CardContent>
          <RiskLimitsPanel isAdmin={user?.role === "admin"} budgetVol={r?.budget_vol ?? 0} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>Simulatore What-If</CardTitle></CardHeader>
        <CardContent>
          <WhatIfSimulator openSymbols={openSymbols} />
        </CardContent>
      </Card>

      <Dialog open={Boolean(editing)} onOpenChange={(open) => !open && setEditing(null)}>
        <DialogContent className="bottom-0 left-0 right-0 top-auto w-full max-w-none translate-x-0 translate-y-0 rounded-t-2xl sm:bottom-auto sm:left-1/2 sm:right-auto sm:top-1/2 sm:w-full sm:max-w-lg sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl">
          {editing && (
            <EditTradeDialog
              trade={editing}
              onClose={() => setEditing(null)}
              onSaved={() => {
                setEditing(null);
                qc.invalidateQueries({ queryKey: ["trades", "OPEN"] });
                qc.invalidateQueries({ queryKey: ["risk"] });
              }}
            />
          )}
        </DialogContent>
      </Dialog>
    </section>
  );
}
```

- [ ] **Step 2: Verifica typecheck + build**

Run: `npx tsc --noEmit`
Expected: nessun errore. (Se `useQueryClient` risultasse importato due volte, consolidalo in un solo import da `@tanstack/react-query`.)

- [ ] **Step 3: Verifica che la pagina si monti (smoke test opzionale)**

Run: `npx vitest run src/components/risk`
Expected: tutti i test dei componenti risk passano.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/risk/page.tsx
git commit -m "feat(risk): assemble /risk page"
```

---

## Task 15: Verifica finale

- [ ] **Step 1: Suite frontend completa**

Run (da `frontend/`): `npx vitest run && npx tsc --noEmit && npx next build`
Expected: tutti i test verdi, nessun errore di tipo, build di produzione completata.

- [ ] **Step 2: Suite backend**

Run: `docker compose run --rm backend python -m pytest tests/test_trade_manager_risk.py -v`
Expected: tutti i test (inclusi `RiskProjectionTests`) verdi. Esegui anche la suite completa se il tempo lo consente: `docker compose run --rm backend python -m pytest -q`.

- [ ] **Step 3: Smoke manuale (se le credenziali eToro Demo sono configurate)**

Avvia lo stack, fai login, apri `/risk`. Verifica: gauge popolato, componenti, esposizione, tabella protezioni con badge e distanza-allo-stop, flag "scoperta" su posizioni senza SL, pannello limiti (admin), what-if che restituisce un delta. Senza credenziali, la pagina deve mostrare stati di loading/empty senza crash.

- [ ] **Step 4: Commit finale (se restano modifiche)**

```bash
git add -A
git commit -m "test(risk): final verification pass"
```

---

## Self-Review (note per l'esecutore)

- **Copertura spec:** Endpoint what-if (Task 1-2) ✓ · nav (Task 6) ✓ · gauge/componenti/esposizione/contributo (Task 7-10) ✓ · tabella protezioni + trailing via dialog riusato (Task 11, 14) ✓ · limiti admin (Task 12) ✓ · what-if apri+chiudi (Task 13) ✓ · refresh al minuto + SSE (Task 5, 14) ✓ · tipi (Task 3) ✓ · stati/empty/error/low-confidence (Task 14) ✓.
- **Coerenza tipi:** `RiskSnapshot`/`RiskProjection` (Task 3) usati identici in tutti i componenti e nell'endpoint; `RiskPositionRow`/`stopInfo`/`buildRiskRows` (Task 4) usati in Task 11 e 14; `useMinuteRefresh` (Task 5) usato in dashboard e `/risk`.
- **Dipendenza `user-event`:** Task 11 ha un fallback a `fireEvent` se `@testing-library/user-event` non è installato — verificare prima.
- **Trailing stop:** gestione completa via `EditTradeDialog` riusato (espone già tutti i campi trailing); visibilità via badge copertura + `trailing_stop_price`/distanza nella tabella.
