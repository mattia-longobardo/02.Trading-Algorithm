# Frontend Rework — Plan 3: Real-time live-data layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Backend is Python (FastAPI, `unittest`); the host lacks pytest/pandas, so run backend tests in Docker: `docker build -t trading-backend:test ./backend && docker run --rm -v $PWD/backend:/app -w /app trading-backend:test python -m unittest discover -s tests -v`. Frontend uses Vitest. Keep both green.

**Goal:** Add a real-time data layer — a new backend SSE endpoint streaming open positions + live quotes + per-position PnL + account equity, and a frontend hook/badge that consumes it — replacing the Positions placeholder with a live table and adding a live indicator to the dashboard.

**Architecture:** A shared, short-TTL `LiveSnapshotCache` builds one snapshot from the OPEN trades (DB, already FX-converted) enriched with best-effort live eToro quotes and account equity; it rebuilds at most once per TTL under a lock, so any number of SSE clients cause O(1) broker calls. The endpoint `GET /api/live/stream` emits `snapshot` + `heartbeat` events (same StreamingResponse pattern as `/api/logs/stream`). The frontend `useLiveStream()` opens an `EventSource` through the existing streaming proxy, tracks connection status, reconnects with backoff, pauses on hidden tab, and exposes the snapshot; `LiveBadge` shows the status; the Positions page renders the live positions.

**Tech Stack:** FastAPI + StreamingResponse (Python), eToro client (rate-limited 60/min), Next.js 15 EventSource via `/api/proxy`, React Query, Vitest.

> Backend paths under `backend/`; frontend under `frontend/`.

---

### Task 1: Backend — `LiveSnapshotCache` (rate-safe snapshot builder)

**Files:** Create `backend/services/live_snapshot.py`; Test `backend/tests/test_live_snapshot.py`.

The cache builds a snapshot dict:
```python
{
  "ts": "<iso utc>",
  "currency": "<display currency>",
  "equity": float | None,
  "cash": float | None,
  "positions": [
    {
      "id": int, "symbol": str, "category": str,
      "units": float, "entry_price": float,
      "current_price": float | None,
      "unrealized_pnl": float | None, "unrealized_pnl_pct": float | None,
      "take_profit": float | None, "stop_loss": float | None,
      "position_id": str | None, "instrument_id": int | None,
    }, ...
  ],
}
```

- [ ] **Step 1 — Failing test** `backend/tests/test_live_snapshot.py`: construct a `LiveSnapshotCache` with a fake metrics object (returns 2 OPEN trades via `list_trades`) and a fake eToro broker (returns quotes via `get_latest_quote` and an equity via `get_account_equity`). Assert: `get_snapshot()` returns a dict with `ts`, `currency`, `equity`, and `positions` of length 2; each position has `current_price` from the live quote and a recomputed `unrealized_pnl = (price - entry) * units` (respecting buy direction); a second immediate `get_snapshot()` call within the TTL does NOT call the broker again (assert broker call count unchanged); `get_snapshot(force=True)` rebuilds. Write concrete fakes (no real network). Follow the existing test style in `backend/tests/` (plain `unittest.TestCase`).
- [ ] **Step 2 — Run** the test in Docker; expect failure (module missing).
- [ ] **Step 3 — Implement** `backend/services/live_snapshot.py`:
  - `class LiveSnapshotCache` with `__init__(self, metrics, brokers, config, logger, ttl_seconds=5.0)`. Store `broker = brokers.get(PROVIDER_ETORO)`.
  - `get_snapshot(self, force=False) -> dict`: under a `threading.Lock`, if a cached snapshot exists and `age < ttl` and not `force`, return it; else rebuild and cache. Use an injectable clock (`time.monotonic` by default) so the test can assert TTL behavior deterministically (pass a `monotonic` callable like the rate limiter does).
  - Build: `trades = metrics.list_trades(status="OPEN", page_size=500).get("items", [])`. For each trade, best-effort `quote = broker.get_latest_quote(symbol, category)`; pick a price (mid of bid/ask, else bid, else the trade's `current_price`/`entry_price`); recompute `unrealized_pnl` and `_pct`; on ANY broker exception, fall back to the trade's stored `current_price`/`pnl` and log at debug (never let one symbol's failure break the snapshot). Compute `equity`/`cash` via `broker.get_account_equity()`/`get_available_cash()` best-effort (None on failure). Use the trade's `account_currency`/display currency for `currency`.
  - Keep it pure-ish and broker-tolerant. Do NOT exceed the eToro limit: the TTL gate bounds rebuild frequency; the client's own `RateLimiter` is the backstop.
- [ ] **Step 4 — Run** the test in Docker; expect PASS.
- [ ] **Step 5 — Commit:** `feat(etoro): live snapshot cache (positions + quotes + equity)`

---

### Task 2: Backend — `GET /api/live/stream` SSE endpoint

**Files:** Modify `backend/api/api_server.py` (add the endpoint + construct the cache in `create_app`). Test: extend `backend/tests/test_live_snapshot.py` or add a light endpoint-shape test if the suite has an app-test pattern; otherwise assert the event-formatting helper.

- [ ] **Step 1 — Wire the cache** in `create_app(...)`: after `metrics` and `brokers` are built, instantiate `live_cache = LiveSnapshotCache(metrics, brokers, config, api_logger)`.
- [ ] **Step 2 — Add the endpoint** mirroring `/api/logs/stream` (reuse the same `_format_event` helper or factor it out):
```python
@app.get("/api/live/stream")
def get_live_stream(_user: auth_lib.AuthenticatedUser = Depends(get_current_user)) -> StreamingResponse:
    async def streamer():
        yield _format_event("heartbeat", isoformat_utc(utc_now()) or "")
        last_heartbeat = utc_now()
        while True:
            try:
                snapshot = live_cache.get_snapshot()
                yield _format_event("snapshot", json.dumps(snapshot))
            except Exception:  # never kill the stream on a transient error
                api_logger.exception("live snapshot failed")
            now = utc_now()
            if (now - last_heartbeat).total_seconds() >= 15:
                yield _format_event("heartbeat", isoformat_utc(now) or "")
                last_heartbeat = now
            await asyncio.sleep(_LIVE_STREAM_INTERVAL_SECONDS)  # e.g. 5
    return StreamingResponse(streamer(), media_type="text/event-stream")
```
  Define `_LIVE_STREAM_INTERVAL_SECONDS = 5` (module const). Ensure `json` is imported.
- [ ] **Step 3 — Test:** add a unit test that builds an app/endpoint as the suite already does for other endpoints (look for an existing FastAPI `TestClient` usage in `backend/tests/`; if present, assert `/api/live/stream` requires auth → 401 without cookie). If the suite has no app-level test harness, instead unit-test that `_format_event("snapshot", json.dumps({...}))` produces a well-formed `event: snapshot\ndata: ...\n\n` byte string. Keep it minimal and aligned with existing patterns.
- [ ] **Step 4 — Run** backend tests in Docker; expect PASS. Also `python -c "import main"` style import check via the existing approach to ensure no import errors.
- [ ] **Step 5 — Commit:** `feat(etoro): /api/live/stream SSE endpoint`

---

### Task 3: Frontend — `useLiveStream()` hook + `LiveBadge`

**Files:** Create `src/lib/use-live-stream.ts`, `src/components/live/live-badge.tsx`, `src/lib/types.ts` (add `LiveSnapshot`/`LivePosition` types). Tests: `src/lib/__tests__/use-live-stream.test.ts`, `src/components/live/__tests__/live-badge.test.tsx`.

- [ ] **Step 1 — Types** in `types.ts`: add `LivePosition` (mirror the backend position fields) and `LiveSnapshot` (`ts: string; currency: string; equity: number | null; cash: number | null; positions: LivePosition[]`).
- [ ] **Step 2 — Hook test** `use-live-stream.test.ts`: with a mock `EventSource` (define a small fake assigned to `global.EventSource` in the test) verify: the hook starts in `"connecting"`; on an `open` it becomes `"live"`; on a `snapshot` message it parses and returns the snapshot; on `error` it becomes `"reconnecting"`/`"stale"`. (Vitest + jsdom; mock EventSource on `window`/`globalThis`.)
- [ ] **Step 3 — Implement `useLiveStream()`**: opens `new EventSource(streamUrl("/api/live/stream"))` (reuse `streamUrl` from `lib/api.ts`). State: `snapshot: LiveSnapshot | null`, `status: "connecting" | "live" | "stale" | "reconnecting"`. Handlers: `onopen` → `live`; `addEventListener("snapshot", …)` → parse JSON, set snapshot, status `live`; `addEventListener("heartbeat", …)` → keep-alive; `onerror` → close, set `reconnecting`, retry with capped exponential backoff (e.g. 1s→2s→5s→10s max). Pause when `document.hidden` (close the source; reopen on `visibilitychange`). Clean up the source + timers + listeners on unmount. Return `{ snapshot, status }`.
- [ ] **Step 4 — `LiveBadge`** (`live-badge.tsx`): takes `status` (and optional `currency`/`ts`), renders a colored dot + label ("● Live" green, "● Stale" muted/amber, "● Riconnessione…" amber, "● Connessione…" muted). Use semantic tokens; `aria-live="polite"`. Badge test: renders the right label per status.
- [ ] **Step 5 — Run** Vitest; expect PASS.
- [ ] **Step 6 — Commit:** `feat(frontend): useLiveStream hook + LiveBadge`

---

### Task 4: Frontend — live Positions table + dashboard live indicator

**Files:** Modify `src/app/positions/page.tsx` (replace placeholder with a live table), `src/components/positions/positions-live-table.tsx` (new), `src/app/page.tsx` (add `LiveBadge` to the dashboard header). Test: `positions-live-table.test.tsx`.

- [ ] **Step 1 — `PositionsLiveTable`**: presentational component taking `positions: LivePosition[]` + `loading`/empty handling; renders a dense table (symbol, units, entry, last, PnL, PnL%, TP, SL) with `.tnum` numeric cells, profit/loss tokens (sign visible, not color-only), sticky first column. Empty state when no open positions.
- [ ] **Step 2 — Positions page**: `"use client"`; call `useLiveStream()`; render a header with `LiveBadge` (status) + an equity/cash summary line (`.tnum`) and `<PositionsLiveTable positions={snapshot?.positions ?? []} />`. This is a functional live board; Plan 4 polishes it into the full cockpit.
- [ ] **Step 3 — Dashboard indicator**: in `src/app/page.tsx` header, mount `useLiveStream()` and show a `LiveBadge` (so the dashboard reflects live connection). Keep the existing dashboard queries; do NOT rip out the 30s polling here — the badge + positions are the live surface for now.
- [ ] **Step 4 — Test** `positions-live-table.test.tsx`: render with two sample positions; assert symbols + a formatted PnL with the profit/loss class; assert the empty state with `[]`.
- [ ] **Step 5 — Verify:** `npm test`, `npm run typecheck`, `npm run build` green.
- [ ] **Step 6 — Commit:** `feat(frontend): live positions table + dashboard live badge`

---

## Self-Review

**Spec coverage:** Real-time data layer (spec §7) → Tasks 1–4. Backend SSE `/api/live/stream` (spec §7 backend) → Tasks 1–2. `useLiveStream` + cache integration + `LiveBadge` (spec §7 frontend) → Task 3. Live positions surface (spec §5 Positions, partial) → Task 4 (full cockpit board is Plan 4). Rate-limit safety (spec §13 risk) → shared TTL cache in Task 1.

**Placeholder scan:** Snapshot shape, event format, hook states, and component props are all concretely specified. Backend test uses fakes (no network). No "TBD".

**Type/name consistency:** `LiveSnapshot`/`LivePosition` (Task 3 types) consumed by `useLiveStream`, `PositionsLiveTable` (Task 4). Backend snapshot keys (Task 1) match the frontend `LivePosition` fields. `streamUrl` reused from `lib/api.ts`. `_format_event`/`PROVIDER_ETORO` reused from existing backend code.

**Notes for the executor:**
- The eToro 60/min limit: rely on the TTL cache (≥5s) + the client's RateLimiter. Do NOT add per-client broker polling.
- Best-effort everything in the snapshot builder — a single failed quote must not break the stream.
- The Next proxy already streams SSE (used by logs) — no proxy changes needed.
- Don't remove the dashboard's existing polling in this plan; the live badge + positions are the live surfaces. Broader live wiring can come in Plan 6 polish if desired.
