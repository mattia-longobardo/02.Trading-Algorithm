# Liquidity gate before ChatGPT order generation

**Date:** 2026-06-09
**Status:** Approved (pending implementation)
**Area:** `backend/services/trade_manager.py`

## Problem

The order-generation cycle calls ChatGPT to decide which trades to open. When
there is nothing the bot could open for a category, that LLM call is wasted
(tokens, latency) and any resulting signal is rejected downstream anyway.

"Nothing to open" has two causes, which must be evaluated **independently per
asset class (STOCK and CRYPTO)**:

1. **Slots exhausted** — the max number of open trades for the category is
   already reached.
2. **Insufficient liquidity** — there is not enough cash to open even the
   smallest allowed trade.

Cause (1) is already handled. Cause (2) is not: the old credit gate was removed
in commit `ea8dc6c` ("drop the credit gate, keep only the market-open gate"), so
today GPT is still invoked when slots are free but cash is too low.

## Goal

Skip the ChatGPT order-generation call for a category when **either** condition
holds, so GPT only runs when at least one new trade is actually openable for that
category.

## Current state

### Entry points that call GPT to open trades

- **Batch (live, scheduled path):** `scheduler.job_evaluate_signals()` →
  `trade_manager.evaluate_cycle(universe)` → `_evaluate_provider_category(provider, category, symbols)`
  → `gpt_client.request_batch_trade_signals(...)` (`trade_manager.py:1253`).
  `evaluate_cycle` iterates `for category, symbols in categories.items()`, so
  `_evaluate_provider_category` already runs **once per category** — the natural
  place for a per-category gate.
- **Single-symbol (legacy / no production caller):** `maybe_open_trade(category, symbol, provider)`
  → `gpt_client.request_new_signal(...)` (`trade_manager.py:728`). No scheduler
  caller today, but it still invokes GPT, so it gets the same gate for
  consistency.

### Existing slot gate (cause 1 — already implemented)

`_evaluate_provider_category` (`trade_manager.py:1240-1247`):

```python
available_slots = self._available_trade_slots(category, provider=provider)
if available_slots <= 0:
    self.logger.debug("Skipping %s/%s batch evaluation because no slots are available", provider, category)
    return
```

`maybe_open_trade` has the equivalent slot check at `trade_manager.py:714-721`.

`_available_trade_slots` (`trade_manager.py:603-608`) is already per-category:
`max_open_trades_stock` vs `max_open_trades_crypto`, minus `count_active_trades`
(PENDING + OPEN) for that category/provider.

### Liquidity primitives (cause 2 — to be gated)

- Cash: `broker.get_available_cash()`.
- Minimum trade size: `config.etoro_min_trade_amount` (default `50.0`,
  `core/utils.py:153`).
- The cash pool is **shared** between STOCK and CRYPTO (`compute_allocated_capital`,
  `trade_manager.py:265-267`). Downstream sizing (`_risk_based_allocation` →
  `risk.suggest_size`) already returns `0` when `available_cash < minimum`, but
  only *after* GPT has been called.

## Design

### New helper

Add to `TradeManager`, alongside `_available_trade_slots`:

```python
def _has_liquidity_for_new_trade(self, provider: str = PROVIDER_ETORO) -> bool:
    """True when the provider has enough cash to open at least the smallest trade.

    Used as a pre-LLM gate so we don't ask GPT for orders we couldn't fund.
    Permissive on errors / unconfigured minimum: returns True so a transient
    cash-lookup blip never silently halts trading (downstream sizing still
    protects against over-allocation).
    """
    broker = self.broker(provider)
    if broker is None:
        return False
    minimum = float(getattr(self.config, "etoro_min_trade_amount", 0.0) or 0.0)
    if minimum <= 0:
        return True
    try:
        cash = float(broker.get_available_cash())
    except Exception:
        self.logger.warning(
            "Cash lookup failed for %s; allowing GPT cycle", provider, exc_info=True
        )
        return True
    return cash >= minimum
```

### Gate insertion points

Both gates go **after** the existing slot gate and **before** any GPT call.

1. `_evaluate_provider_category`, immediately after the `available_slots <= 0`
   block (`trade_manager.py:1247`):

   ```python
   if not self._has_liquidity_for_new_trade(provider):
       self.logger.info(
           "Skipping %s/%s batch evaluation: available cash below min trade amount",
           provider, category,
       )
       return
   ```

2. `maybe_open_trade`, immediately after its slot check (`trade_manager.py:721`):

   ```python
   if not self._has_liquidity_for_new_trade(provider):
       self.logger.info(
           "Skipping %s because available cash is below the min trade amount", symbol,
       )
       return
   ```

### Semantics of "separately for stock and crypto"

The eToro cash pool is shared, so the liquidity *value* is identical for both
categories. What runs separately is the *evaluation*: `_evaluate_provider_category`
is invoked once per category, so each category independently decides whether to
call GPT. One category can be skipped (e.g. slots exhausted) while the other
proceeds; when cash is below the minimum, both categories skip on their own pass.
This satisfies the requirement that the check be verified separately per asset
class.

### Error behaviour (explicit choice)

If `get_available_cash()` raises, the gate is **permissive** (returns `True`,
lets GPT run). Rationale: a transient broker/API error should not silently halt
order generation, and the downstream risk/sizing gate still prevents funding a
trade that cannot be afforded. Same for an unconfigured/zero minimum.

## Out of scope

- Per-category cash partitioning (cash stays a shared pool).
- Changing the slot gate, market-open gate, or downstream sizing/risk gates.
- Pre-checking the hard risk threshold before GPT (per-symbol, can't be
  precomputed at category level).

## Testing (TDD)

New tests in `backend/tests/` (extending the existing `test_trade_manager_*`
style with a mocked broker):

1. **Batch — liquidity block, STOCK:** `cash < min` ⇒ `request_batch_trade_signals`
   **not** called for STOCK.
2. **Batch — liquidity block, CRYPTO:** same, verified for CRYPTO.
3. **Batch — liquidity OK:** `cash >= min` and slots free ⇒ GPT **is** called.
4. **Independence:** STOCK slots exhausted, CRYPTO funded ⇒ STOCK skipped, CRYPTO
   still calls GPT (and vice-versa for liquidity vs slots).
5. **Permissive on error:** `get_available_cash` raises ⇒ GPT **is** called.
6. **Unconfigured minimum:** `etoro_min_trade_amount == 0` ⇒ gate never blocks.
7. **Single-symbol:** `maybe_open_trade` with `cash < min` ⇒ `request_new_signal`
   **not** called.

## Files touched

- `backend/services/trade_manager.py` — new `_has_liquidity_for_new_trade` helper;
  two gate insertions.
- `backend/tests/test_trade_manager_*.py` — new tests above (file chosen during
  implementation to match existing fixtures).
