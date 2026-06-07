# Portfolio Risk Score — design

**Date:** 2026-06-06
**Status:** Approved design, pending implementation plan
**Area:** new `backend/services/portfolio_risk.py`; consumers in `trade_manager.py`, `gpt_client.py`, `metrics_service.py`/API; config in `core/utils.py`.

## Problem

Today the bot has **no forward-looking portfolio-risk measure**. `risk_tolerance` (1-10) is only a qualitative hint passed to GPT; position sizing is **equal-slot** (`cash / free_slots`); the only risk numbers (max drawdown, Sharpe in `metrics_service.py`) are **retrospective** on closed trades. Crucially, positions are treated as **independent** — there is no aggregate volatility, **no correlation, no concentration**. The bot can hold several names that are effectively the same bet (e.g. 4 AI/semiconductor stocks) and the real risk stays invisible until a drawdown.

## Decisions (from discussion)

- A single **composite Portfolio Risk Score, 0-100**, combining volatility + concentration + correlation + exposure.
- **Concentration and correlation weigh more** than in the first draft (to directly attack the "same bet" problem).
- **Risk-based position sizing** (marginal risk contribution), replacing equal-slot.
- The score serves **all four** uses: dashboard monitoring + alert, entry constraint, sizing, and GPT context.
- Budget derived from `risk_tolerance`.

## Concept

The score is **risk-budget utilization**: ~50 = "at budget", ≥70 = over budget (alert / entry brake), 100 ≈ 2× budget. The budget is an annualized portfolio-volatility target derived from `risk_tolerance`.

## Inputs (all already available, no new external data)

- **Open positions** (`TradeManager.get_open_or_pending_trades()` → OPEN ones): `symbol`, `category`, `quantity`, `current_price` → value `vᵢ = current_price·quantity`.
- **Account**: equity `E` (`EToroClient.get_account_equity()`), cash `C`, invested `I = Σvᵢ`.
- **Price history**: `DataManager.get_symbol_history(symbol, limit)` (local DB OHLCV) → daily log-returns over a lookback (default 120 trading days) → per-symbol annualized volatility `σᵢ` and the sample correlation matrix `ρ`.
- **Config**: `risk_tolerance`, component weights, budget mapping, lookback, thresholds, sizing params.

Weights are taken **vs equity** for the volatility and exposure terms (so cash dampens risk), and **vs invested capital** for concentration and correlation (structure of the holdings).

## Algorithm

### Per-symbol statistics
- Log returns `rᵢ,t = ln(close_t / close_{t-1})` over the lookback.
- Annualized vol `σᵢ = stdev(rᵢ) · √A`, `A = 252` (STOCK) or `365` (CRYPTO).
- Correlation from overlapping return windows, then **shrinkage** toward a constant 0.5 prior for stability with few/short series: `ρ̃ = λ·ρ_sample + (1−λ)·0.5` (λ = `risk_corr_shrinkage`, default 0.6 = weight on the sample; prior used when <3 overlapping points). (A constant prior is used rather than the mean off-diagonal correlation, keeping the pairwise estimate pure and order-independent.)
- Covariance `Σᵢⱼ = ρ̃ᵢⱼ · σᵢ · σⱼ`.

### Four components (each normalized to 0-100)

1. **Volatility** — `σ_p = √(wᵀ Σ w)` with `w` = weights vs **equity** (cash gets σ=0). `vol = clamp(σ_p / σ_budget · 50, 0, 100)`.
2. **Concentration** — Herfindahl on holding weights `h` (vs **invested** I): `HHI = Σ hᵢ²`; effective positions `N_eff = 1/HHI`. With `target_positions = max_open_trades_stock + max_open_trades_crypto`: `conc = clamp((HHI − 1/target_positions) / (1 − 1/target_positions) · 100, 0, 100)` (fully diversified → 0; single name → 100).
3. **Correlation** — value-weighted average pairwise (shrunk) correlation `ρ̄` of holdings: `corr = clamp((ρ̄ − ρ_lo) / (ρ_hi − ρ_lo) · 100, 0, 100)`, `ρ_lo=0.2`, `ρ_hi=0.8`.
4. **Exposure** — `exposure = I/E`: `exp = clamp(exposure · 100, 0, 100)`.

### Composite
`risk_score = 0.30·vol + 0.30·conc + 0.25·corr + 0.15·exp` (weights configurable; concentration + correlation deliberately dominant). Result rounded 0-100.

### Budget from risk_tolerance
`σ_budget(RT) = 0.10 + (RT−1)/9 · 0.35` → RT1 ≈ 12%, RT5 ≈ 26%, RT10 = 45% annualized vol.
Thresholds: **alert** at score ≥ `risk_alert_threshold` (default 70); **hard brake** at ≥ `risk_hard_threshold` (default 85).

### Risk-based sizing (marginal contribution)
Replace equal-slot. Each new position should add roughly an equal **risk** share, not equal capital:
- `target_risk_per_slot = σ_budget / target_positions`.
- For candidate `c`: estimate its marginal vol contribution per unit weight ≈ `σ_c · corr_c`, where `corr_c` = value-weighted (shrunk) correlation of `c` to the existing book (`= 1.0` if it is the first position; floored at `corr_floor`, default 0.3, to avoid oversizing apparently-uncorrelated names on noisy estimates).
- Target weight `w_c = target_risk_per_slot / (σ_c · max(corr_c, corr_floor))`; `value_c = w_c · E`.
- Clamp to `[etoro_min_trade_amount, available_cash, max_position_pct · E]` (`max_position_pct` default 0.25).
- Missing/short history → fall back to a conservative category-median σ (STOCK 0.30, CRYPTO 0.60) and `corr_c = 0.5`; mark assessment `low_confidence`.

### Entry constraint (projected score)
Before opening, compute the **projected** `risk_score` for the portfolio *including* the (sized) candidate. If projected ≥ `risk_hard_threshold`, **shrink** the size to bring it under, and if it still can't fit at the minimum trade amount, **skip** the trade. This is what blocks adding the 5th correlated AI name.

## Architecture

**New module `backend/services/portfolio_risk.py`** — `PortfolioRiskService`:
- `__init__(config, logger, data_manager, broker_provider)` — depends on `DataManager.get_symbol_history` for bars and the broker for equity/cash; pure computation otherwise (easy to unit-test by injecting a fake history provider).
- `assess(positions, equity) -> RiskAssessment` — full current-portfolio assessment.
- `suggest_size(candidate, positions, equity, available_cash) -> float` — risk-based size.
- `project(candidate, size, positions, equity) -> RiskAssessment` — portfolio-with-candidate (for the entry gate).
- Internal helpers: `_returns_matrix(symbols)`, `_annualized_vol`, `_shrunk_correlation`, `_covariance`, `_components`.

**`RiskAssessment`** (dataclass): `score`, `portfolio_vol`, `budget_vol`, `components` (`vol/conc/corr/exp` raw 0-100), `hhi`, `n_eff`, `avg_correlation`, `exposure`, `per_position_risk_contribution` (`{symbol: pct}`), `low_confidence: bool`, `over_alert: bool`, `over_hard: bool`.

**Consumers:**
- `trade_manager.py`: `compute_allocated_capital` is superseded for entries by `PortfolioRiskService.suggest_size(...)`; `_open_trade_from_signal` (≈ line 460) gains the projected-score gate (shrink/skip). Keep equal-slot as a fallback when risk data is unavailable (`low_confidence` on the whole book).
- `gpt_client.py`: entry/batch/protection payloads get a `portfolio_risk` block in `constraints` — current `score`, `portfolio_vol`, `budget_vol`, `avg_correlation`, `n_eff`, top concentration, and **remaining budget** — so GPT reasons about what is already held.
- API/dashboard: expose the assessment (extend `metrics_service` or a new `/api/risk` endpoint) for the KPI + alert. (Frontend rendering is a separate follow-up; backend just serves the data.)

**Config additions (`core/utils.py`, env + `SETTINGS_OVERRIDABLE_KEYS` where runtime-tunable):**
`risk_weight_vol=0.30`, `risk_weight_concentration=0.30`, `risk_weight_correlation=0.25`, `risk_weight_exposure=0.15`, `risk_budget_vol_min=0.10`, `risk_budget_vol_max=0.45`, `risk_lookback_days=120`, `risk_corr_shrinkage=0.6`, `risk_alert_threshold=70`, `risk_hard_threshold=85`, `risk_sizing_corr_floor=0.30`, `risk_max_position_pct=0.25`, `risk_default_stock_vol=0.30`, `risk_default_crypto_vol=0.60`. Weights normalized to sum 1 at load.

## Error handling / edge cases

- **0 or 1 position**: correlation/HHI degenerate → corr component 0; single position HHI=1 → high concentration (correct). σ_p from the single σ.
- **No history for a symbol**: conservative default vol + `low_confidence`; never crash.
- **No price overlap between two symbols**: use shrinkage default correlation for that pair.
- **Equity ≤ 0 / no broker**: return a neutral, `low_confidence` assessment; sizing falls back to equal-slot; entry gate disabled (don't block trading on missing data).
- **Crypto vs stock** annualization handled per symbol.

## Testing

- Per-symbol vol from a known return series; annualization per class.
- Correlation + shrinkage on synthetic series (perfectly correlated → ρ̄≈1; independent → ≈0).
- `σ_p` matches `√(wᵀΣw)` on a hand-built 2-asset case; cash lowers it.
- Concentration: equal weights over `target_positions` → conc≈0; single name → 100.
- Composite weighting + budget mapping (RT1/5/10).
- `suggest_size`: high-vol/high-corr candidate gets a smaller size than a low-vol/uncorrelated one; clamps (min/cash/max_pct) respected; first-position path.
- Entry gate: candidate that pushes projected score over hard threshold is shrunk, then skipped at minimum size.
- Fallbacks: missing history → conservative size + `low_confidence`; no broker/equity → neutral assessment, equal-slot sizing.
- Determinism: no `Date.now()`/random; lookback windows explicit.

## Out of scope / YAGNI

- Parametric/historical VaR and expected shortfall (composite score covers the need; can add a VaR diagnostic later).
- Intraday risk; options/hedging; leverage (system is long-only, 1×).
- Frontend widgets (separate task; this spec exposes the data).
- Changing the GPT models or the dossier/selection pipeline.
