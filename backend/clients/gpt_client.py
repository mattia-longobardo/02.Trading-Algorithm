"""OpenAI integration for universe selection and trade decisions."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import APIError, APIStatusError, OpenAI, RateLimitError

from core.prompt_store import get_prompt
from core.utils import AppConfig, build_mixed_timeframe_ohlcv, retry, to_toon


# Mapping between prompt keys exposed to the admin UI and the hard-coded
# constants below. The constants are still the source of truth for the
# initial DB seed and for the runtime fallback if the DB ever becomes
# unreachable, but the active text actually used by the trading bot is
# resolved via :func:`core.prompt_store.get_prompt` on every call so that
# admin edits take effect on the next scheduled job without a redeploy.
PROMPT_KEY_NEW_SIGNAL = "new_signal"
PROMPT_KEY_BATCH_SIGNALS = "batch_signals"
PROMPT_KEY_PENDING_REVIEW = "pending_review"
PROMPT_KEY_PROTECTION_REVIEW = "protection_review"
PROMPT_KEY_UNIVERSE_DOSSIER = "universe_dossier"
PROMPT_KEY_UNIVERSE_SHORTLIST = "universe_shortlist"
PROMPT_KEY_UNIVERSE_FINAL = "universe_final"
PROMPT_KEY_UNIVERSE_FINAL_FROM_DOSSIERS = "universe_final_from_dossiers"


def _alpaca_prompt_keys() -> tuple[str, ...]:
    return (
        PROMPT_KEY_NEW_SIGNAL,
        PROMPT_KEY_BATCH_SIGNALS,
        PROMPT_KEY_PENDING_REVIEW,
        PROMPT_KEY_PROTECTION_REVIEW,
        PROMPT_KEY_UNIVERSE_DOSSIER,
        PROMPT_KEY_UNIVERSE_SHORTLIST,
        PROMPT_KEY_UNIVERSE_FINAL,
        PROMPT_KEY_UNIVERSE_FINAL_FROM_DOSSIERS,
    )


def _resolve_provider_prompt_key(base_key: str, provider: str) -> str:
    return base_key


def get_default_prompts() -> dict[str, str]:
    """Return the hard-coded default prompt content keyed by prompt key.

    Used to seed the application database on first start and as the
    fallback if the resolver cannot read the active version at call time.
    """

    return {
        PROMPT_KEY_NEW_SIGNAL: INSTRUCTIONS_NEW_SIGNAL,
        PROMPT_KEY_BATCH_SIGNALS: INSTRUCTIONS_BATCH_SIGNALS,
        PROMPT_KEY_PENDING_REVIEW: INSTRUCTIONS_PENDING_REVIEW,
        PROMPT_KEY_PROTECTION_REVIEW: INSTRUCTIONS_PROTECTION_REVIEW,
        PROMPT_KEY_UNIVERSE_DOSSIER: INSTRUCTIONS_UNIVERSE_DOSSIER,
        PROMPT_KEY_UNIVERSE_SHORTLIST: INSTRUCTIONS_UNIVERSE_SHORTLIST,
        PROMPT_KEY_UNIVERSE_FINAL: INSTRUCTIONS_UNIVERSE_FINAL,
        PROMPT_KEY_UNIVERSE_FINAL_FROM_DOSSIERS: INSTRUCTIONS_UNIVERSE_FINAL_FROM_DOSSIERS,
    }

NEW_SIGNAL_SCHEMA = {
    "name": "new_trade_signal",
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["OPEN", "SKIP"]},
            "symbol": {"type": "string"},
            "entry_price": {"type": ["number", "null"]},
            "take_profit": {"type": ["number", "null"]},
            "trailing_take_profit_distance": {"type": ["number", "null"]},
            "trailing_take_profit_activation_pct": {"type": ["number", "null"]},
            "stop_loss": {"type": ["number", "null"]},
            "trailing_stop_distance": {"type": ["number", "null"]},
            "trade_score": {"type": ["number", "null"]},
            "confidence": {"type": ["number", "null"]},
            "reasoning": {"type": "string"},
        },
        "required": [
            "action",
            "symbol",
            "entry_price",
            "take_profit",
            "trailing_take_profit_distance",
            "trailing_take_profit_activation_pct",
            "stop_loss",
            "trailing_stop_distance",
            "trade_score",
            "confidence",
            "reasoning",
        ],
        "additionalProperties": False,
    },
}

BATCH_SIGNALS_SCHEMA = {
    "name": "batch_trade_signals",
    "schema": {
        "type": "object",
        "properties": {
            "signals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["OPEN", "SKIP"]},
                        "symbol": {"type": "string"},
                        "entry_price": {"type": ["number", "null"]},
                        "take_profit": {"type": ["number", "null"]},
                        "trailing_take_profit_distance": {"type": ["number", "null"]},
                        "trailing_take_profit_activation_pct": {"type": ["number", "null"]},
                        "stop_loss": {"type": ["number", "null"]},
                        "trailing_stop_distance": {"type": ["number", "null"]},
                        "trade_score": {"type": ["number", "null"]},
                        "confidence": {"type": ["number", "null"]},
                        "reasoning": {"type": "string"},
                    },
                    "required": [
                        "action",
                        "symbol",
                        "entry_price",
                        "take_profit",
                        "trailing_take_profit_distance",
                        "trailing_take_profit_activation_pct",
                        "stop_loss",
                        "trailing_stop_distance",
                        "trade_score",
                        "confidence",
                        "reasoning",
                    ],
                    "additionalProperties": False,
                },
            },
            "reasoning": {"type": "string"},
        },
        "required": ["signals", "reasoning"],
        "additionalProperties": False,
    },
}

UNIVERSE_SYMBOL_DOSSIER_SCHEMA = {
    "name": "universe_symbol_dossier",
    "schema": {
        "type": "object",
        "properties": {
            "symbol": {"type": "string"},
            "category": {"type": "string"},
            "summary": {"type": "string"},
            "bull_case": {"type": "array", "items": {"type": "string"}},
            "bear_case": {"type": "array", "items": {"type": "string"}},
            "recent_catalysts": {"type": "array", "items": {"type": "string"}},
            "key_risks": {"type": "array", "items": {"type": "string"}},
            "theme_tags": {"type": "array", "items": {"type": "string"}},
            "news_sentiment": {
                "type": "string",
                "enum": ["positive", "mixed_positive", "neutral", "mixed_negative", "negative"],
            },
            "quality_score": {"type": "number"},
            "liquidity_score": {"type": "number"},
            "momentum_score": {"type": "number"},
            "downside_control_score": {"type": "number"},
            "fit_score": {"type": "number"},
            "conviction_score": {"type": "number"},
            "reasoning": {"type": "string"},
        },
        "required": [
            "symbol",
            "category",
            "summary",
            "bull_case",
            "bear_case",
            "recent_catalysts",
            "key_risks",
            "theme_tags",
            "news_sentiment",
            "quality_score",
            "liquidity_score",
            "momentum_score",
            "downside_control_score",
            "fit_score",
            "conviction_score",
            "reasoning",
        ],
        "additionalProperties": False,
    },
}

UNIVERSE_BATCH_SHORTLIST_SCHEMA = {
    "name": "universe_batch_shortlist",
    "schema": {
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"},
        },
        "required": ["symbols", "reasoning"],
        "additionalProperties": False,
    },
}

UNIVERSE_DOSSIER_FINAL_SCHEMA = {
    "name": "weekly_universe_from_dossiers",
    "schema": {
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"},
        },
        "required": ["symbols", "reasoning"],
        "additionalProperties": False,
    },
}

UNIVERSE_FINAL_SCHEMA = {
    "name": "weekly_universe_final",
    "schema": {
        "type": "object",
        "properties": {
            "symbols": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"},
        },
        "required": ["symbols", "reasoning"],
        "additionalProperties": False,
    },
}

PENDING_REVIEW_SCHEMA = {
    "name": "pending_trade_review",
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["KEEP", "CANCEL"]},
            "confidence": {"type": ["number", "null"]},
            "reasoning": {"type": "string"},
        },
        "required": ["action", "confidence", "reasoning"],
        "additionalProperties": False,
    },
}

OPEN_PROTECTION_REVIEW_SCHEMA = {
    "name": "open_trade_protection_review",
    "schema": {
        "type": "object",
        "properties": {
            "trailing_take_profit_distance": {"type": ["number", "null"]},
            "trailing_take_profit_activation_pct": {"type": ["number", "null"]},
            "reasoning": {"type": "string"},
        },
        "required": [
            "trailing_take_profit_distance",
            "trailing_take_profit_activation_pct",
            "reasoning",
        ],
        "additionalProperties": False,
    },
}


# Static instructions: kept identical across calls so OpenAI prompt caching
# can reuse the prefix. All runtime values (currency, risk_tolerance, category,
# horizon, batch sizing, etc.) are passed in the input payload under
# `constraints` and read by the model from there.

INSTRUCTIONS_NEW_SIGNAL = (
    "You are a disciplined trading analyst. You must perform web search before deciding. "
    "Use only LONG spot trading, never short. Compute technical indicators yourself from OHLCV. "
    "This strategy is medium-long term position trading, not daily trading or intraday speculation. "
    "Read constraints.target_holding_period_days for the preferred holding window; setups should be holdable for 3-4 months when the thesis stays valid. "
    "Do not optimize for quick daily flips, small intraday moves, or noise-driven momentum. "
    "Use constraints.currency as the reference currency for both stocks and crypto. For crypto, only consider symbols quoted in that currency. "
    "Honor constraints.risk_tolerance on a 1-10 scale where 10 is the highest risk appetite: low values should favor resilient, liquid, lower-volatility setups with tighter downside control; high values may accept more volatility and more aggressive upside theses. "
    "The OHLCV data is split into two timeframes: ohlcv.daily contains the most recent daily bars for short-term context, and ohlcv.weekly contains older bars aggregated to weekly granularity for medium/long-term context. Treat them as a continuous history, not as separate datasets. "
    "Return only JSON matching the schema. If risk/reward is unattractive, choose SKIP. "
    "If you choose OPEN, entry_price, take_profit, and stop_loss must be non-null positive numbers. "
    "trailing_take_profit_distance may be null when no trailing take profit is desired, otherwise it must be a positive number. "
    "trailing_take_profit_activation_pct must be set together with trailing_take_profit_distance: it is the percentage gain above entry_price required to arm the trailing take profit (e.g. 5 means trailing arms once the price has risen 5% above entry). Both fields must be either both null (no trailing take profit) or both positive numbers. "
    "Trailing-TP invariant (hard constraint): trailing_take_profit_activation_pct must exceed (trailing_take_profit_distance / entry_price * 100) by at least ~0.5 percentage points. This guarantees that when the trailing first arms, the trigger (high_water_mark - distance) is already above entry_price, so the trailing locks in a small minimum profit instead of closing at a loss. As a practical heuristic, keep trailing_take_profit_distance <= entry_price * (trailing_take_profit_activation_pct - 0.5) / 100. The bot rejects pairs that violate this rule, and at runtime it also floors the trigger at entry_price * 1.005 as a safety belt, so the trailing TP can never close the trade below entry_price. "
    "trailing_stop_distance may be null when no trailing stop is desired, otherwise it must be a positive number. "
    "trade_score must be a 0-100 score balancing expected profitability against risk after considering the user risk tolerance. "
    "Base the decision primarily on medium-term trend structure, macro or fundamental catalysts, business or ecosystem strength, and multi-week or multi-month risk/reward. "
    "The script manages take-profit, trailing-take-profit, stop-loss, and trailing-stop logic internally after entry; "
    "Alpaca is used only to place the entry order and to close the position at market when a rule triggers. "
    "When the trailing take profit is provided, it arms once price reaches entry_price * (1 + trailing_take_profit_activation_pct / 100) and then trails the high-water mark by the specified distance, locking in profit even if the hard take_profit level is never reached."
)

INSTRUCTIONS_BATCH_SIGNALS = (
    "You are evaluating a batch of symbols for a medium-long term LONG-only trading strategy. "
    "The asset class is in constraints.category and the cycle limit is in constraints.max_new_trades_this_cycle. "
    "You must perform web search before deciding. "
    "Analyze every provided symbol and return one result per symbol in the same batch. "
    "This is not day trading: focus on setups likely to play out over weeks or months, aligned with constraints.target_holding_period_days. "
    "Use constraints.currency as the reference currency; for crypto only consider pairs quoted in that currency. "
    "Honor constraints.risk_tolerance on a 1-10 scale where 10 means maximum tolerated risk. "
    "Low risk tolerance should emphasize quality, liquidity, drawdown control, and more conservative levels. "
    "High risk tolerance can accept more volatility, wider stops, and more speculative catalysts if the upside is compelling. "
    "The portfolio can open at most constraints.max_new_trades_this_cycle new trades in this cycle. "
    "Each symbol's OHLCV is split between ohlcv.daily (recent daily bars) and ohlcv.weekly (older bars aggregated to weekly granularity). Treat them as a continuous history. "
    "For every symbol return OPEN or SKIP. OPEN means the setup is attractive today. "
    "When OPEN is chosen, entry_price, take_profit, and stop_loss must be positive numbers. "
    "trailing_take_profit_distance may be null or a positive number. "
    "trailing_take_profit_activation_pct must follow trailing_take_profit_distance: both null when no trailing take profit is desired, otherwise both positive numbers. The activation percentage is the gain above entry_price (e.g. 5 means +5%) at which the trailing take profit arms; once armed, it trails the high-water mark by the specified distance, regardless of whether the hard take_profit is reached. "
    "Trailing-TP invariant (hard constraint): trailing_take_profit_activation_pct must exceed (trailing_take_profit_distance / entry_price * 100) by at least ~0.5 percentage points so the trigger sits above entry the moment trailing first arms. Heuristic: keep distance <= entry_price * (activation_pct - 0.5) / 100. The bot rejects pairs that violate this rule and floors the runtime trigger at entry_price * 1.005 as a safety belt. "
    "trailing_stop_distance may be null or a positive number. "
    "trade_score must be a 0-100 score balancing profitability and risk for this user; the highest scores should represent the best risk-adjusted opportunities to open first. "
    "Return only JSON matching the schema."
)

INSTRUCTIONS_PENDING_REVIEW = (
    "You are reviewing an existing LONG entry order that has remained pending for more than constraints.pending_days_threshold days. "
    "You must perform web search before deciding. "
    "Decide whether the order thesis is still valid today. "
    "Return KEEP only if opening the trade at this stage is still attractive for a medium-long term position trade. "
    "Return CANCEL if the thesis is stale, invalidated, materially weaker, or no longer worth opening now. "
    "Use constraints.currency as the reference currency and keep constraints.risk_tolerance (1-10 scale, 10 = highest) in mind. "
    "OHLCV is split between ohlcv.daily (recent daily bars) and ohlcv.weekly (older bars aggregated to weekly). Treat them as one continuous history. "
    "Base the review on current news, medium-term trend structure, catalysts, and whether the original pending entry still offers good risk/reward. "
    "Return only JSON matching the schema."
)

INSTRUCTIONS_PROTECTION_REVIEW = (
    "You are reviewing an already OPEN LONG swing-position trade. "
    "You must perform web search before deciding. "
    "Your only task is to reassess the trailing take profit configuration for this open trade. "
    "Return the full desired trailing_take_profit_distance and trailing_take_profit_activation_pct that should apply right now: keep current values if no change is needed, "
    "return different positive numbers to tighten or loosen the trailing or to shift the activation threshold, or return both fields as null to disable the trailing take profit. "
    "trailing_take_profit_activation_pct is the percentage gain above entry_price at which trailing arms (e.g. 5 means +5%); once armed, the bot trails the high-water mark by trailing_take_profit_distance. The two fields must be either both null or both positive numbers. "
    "Field semantics — read these before proposing values: trade.open_timestamp is when the trade opened; trade.high_water_mark is the *all-time highest* price reached since then and does not decay when the price retraces; trade.current_price is the latest mark; trade.pnl is current unrealized PnL in the account currency. If current_price < entry_price the trade is currently in loss; if current_price < high_water_mark the price has already retraced from its peak. "
    "Trailing-TP invariant #1 — arming-in-profit (hard constraint): trailing_take_profit_activation_pct must exceed (trailing_take_profit_distance / entry_price * 100) by at least ~0.5 percentage points, otherwise the proposal is rejected because the trigger would arm below entry_price and produce a loss labelled TRAILING_TAKE_PROFIT. Heuristic: keep distance <= entry_price * (activation_pct - 0.5) / 100. The bot also floors the runtime trigger at entry_price * 1.005 as a safety net. "
    "Trailing-TP invariant #2 — no instant-fire on a stale high (hard constraint): with the proposed distance D and activation_pct A, the runtime trigger is max(high_water_mark - D, entry_price * 1.005); this trigger must stay strictly below current_price, otherwise the trailing arms on the stale high_water_mark and the bot closes the trade at the next sync at the depressed current_price. Practically: when high_water_mark > current_price, EITHER keep activation_pct above (high_water_mark / entry_price - 1) * 100 (so the trailing stays disarmed against the stale peak) OR raise distance to at least (high_water_mark - current_price) plus a small safety margin. Do not 'rescue' a retraced trade by lowering activation_pct under this threshold — it will close immediately. "
    "Losing-trade guidance: when current_price < entry_price the trade is below entry and trailing TP is a profit-locking tool, not a loss cutter. In that state do NOT tighten the trailing — either keep the previous values or return both fields as null. Loss management belongs to stop_loss, which is reviewed separately. "
    "Profit-trade guidance: when the trade is in profit, the trend is intact, and both invariants above hold, generally lower the activation threshold and/or tighten the distance so gains are captured before they can mean-revert. "
    "Do not propose entry, stop loss, or hard take profit changes here. "
    "Use constraints.currency as the reference currency and keep constraints.risk_tolerance (1-10 scale, 10 = highest) in mind. "
    "ohlcv.daily contains a short window of recent daily bars; that is enough context to judge whether the trend is intact and how much room the trailing should give. "
    "Base the review on current news, catalyst evolution, medium-term trend structure, current profit cushion, and whether upside should be given more room or protected more tightly. "
    "Return only JSON matching the schema."
)

INSTRUCTIONS_UNIVERSE_DOSSIER = (
    "Create a compact JSON dossier for one weekly universe candidate. "
    "The asset class is in selection_rules.category. "
    "Do mandatory web search before deciding. "
    "Use both the provided local market metrics and current web information. "
    "This is a medium-long term position-trading strategy, not intraday trading. "
    "Favor setups suitable for selection_rules.target_holding_period_days, and possibly 3-4 months if the thesis remains intact. "
    "Honor selection_rules.risk_tolerance on a 1-10 scale where 10 means maximum risk appetite. "
    "Score quality, liquidity, momentum, downside control, and fit for this strategy on a 0-100 scale where higher is better. "
    "Use recent news, catalysts, sentiment, and business or ecosystem quality from web search. "
    "When the provided market metrics conflict with the web narrative, acknowledge that tension in the reasoning. "
    "Keep the summary concise and practical. "
    "Use selection_rules.currency as the reference currency, and for crypto keep Alpaca pair format like BTC/<currency>. "
    "Return only JSON matching the schema."
)

INSTRUCTIONS_UNIVERSE_SHORTLIST = (
    "Review one batch for the weekly universe selection. "
    "The asset class is in selection_rules.category, the batch index in selection_rules.batch_number out of selection_rules.batch_count, and the target shortlist size in selection_rules.shortlist_size. "
    "Do mandatory web search before choosing. Exclude ETFs and avoid illiquid names. "
    "Avoid warrants, rights, units, preferred shares, shell companies, and other non-common-stock instruments. "
    "Use only the provided Alpaca candidate list for this batch. "
    "When local market metrics are provided for a candidate, treat them as hard context and use them alongside web search. "
    "This strategy is medium-long term position trading, not daily trading. "
    "Favor assets suitable for holding selection_rules.target_holding_period_days, and potentially 3-4 months if the thesis remains intact. "
    "Honor selection_rules.risk_tolerance on a 1-10 scale where 10 means maximum risk appetite. "
    "Adjust the shortlist to this preference: low risk should favor larger, more liquid, more resilient names; high risk can include more aggressive growth or narrative-driven assets, but still avoid obvious low-quality instruments. "
    "Base the selection on tradability, liquidity proxies, business relevance, current news flow, and sentiment analysis from web search. "
    "Prefer stronger average dollar volume, constructive 20d/60d/120d trend, and candidates trading relatively close to their medium-term highs unless current news strongly contradicts the setup. "
    "Prioritize symbols with strong potential over the next months, driven by fundamental or technical catalysts, while keeping the selection coherent with the user risk tolerance. "
    "For stocks, prefer companies with solid earnings, revenue growth, sector leadership, and catalysts that can play out over multiple weeks or months. "
    "For crypto, prefer established assets with solid market capitalization, active ecosystem participation, and durable narratives rather than short-lived hype. "
    "Focus on positive momentum, strong fundamentals, and downside control appropriate for the selected risk profile. "
    "Use selection_rules.currency as the reference currency. "
    "For crypto, return only symbols quoted in that currency and keep Alpaca pair format like BTC/<currency>. "
    "Return up to selection_rules.shortlist_size symbols from this batch as the best intermediate shortlist for the final universe decision. "
    "Return only JSON matching the schema."
)

INSTRUCTIONS_UNIVERSE_FINAL = (
    "Select exactly selection_rules.required_count symbols for the weekly trading universe from the provided shortlist. "
    "The asset class is in selection_rules.category. "
    "Do mandatory web search before choosing. "
    "Use only the shortlisted candidates provided in this final consolidation step. "
    "When local market metrics are provided for a candidate, treat them as hard context and use them alongside web search. "
    "This strategy is medium-long term position trading, not daily trading. "
    "Honor selection_rules.risk_tolerance on a 1-10 scale where 10 means maximum risk appetite. "
    "Choose the strongest multi-month opportunities while balancing upside, liquidity, quality, and downside control according to that risk preference. "
    "Prefer candidates with stronger average dollar volume, constructive 20d/60d/120d trend, and better resilience relative to recent highs unless current news materially weakens the thesis. "
    "Use selection_rules.currency as the reference currency. "
    "For crypto, return only Alpaca pair symbols quoted in that currency. "
    "Return only JSON matching the schema."
)

INSTRUCTIONS_UNIVERSE_FINAL_FROM_DOSSIERS = (
    "Select exactly selection_rules.required_count symbols for the weekly trading universe from the provided candidate dossiers. "
    "The asset class is in selection_rules.category. "
    "Use only the dossier information provided in this final consolidation step. "
    "Do not invent candidates outside the dossier list. "
    "Optimize for overall portfolio quality, liquidity, conviction, and medium-term opportunity. "
    "Honor selection_rules.risk_tolerance on a 1-10 scale where 10 means maximum risk appetite. "
    "Prefer some diversification across themes or narratives when multiple candidates are similarly strong, rather than concentrating too heavily in near-duplicates. "
    "It is acceptable to keep some continuity with selection_rules.current_universe when dossier quality is still competitive, but do not keep a weaker name purely for continuity. "
    "Use selection_rules.currency as the reference currency, and for crypto return only Alpaca pair symbols quoted in that currency. "
    "Return only JSON matching the schema."
)


class GPTClient:
    """OpenAI Responses API wrapper with mandatory web search."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger.getChild("gpt")
        self.client = OpenAI(api_key=config.openai_api_key)

    def _resolve_prompt(self, key: str, default: str) -> str:
        """Return the active prompt content for ``key`` from the app DB.

        Falls back to the supplied default constant on any error or if the
        DB has not yet been seeded for this key.
        """

        db_path = getattr(self.config, "db_app", "")
        if not db_path:
            return default
        try:
            return get_prompt(db_path, key, default)
        except Exception:
            self.logger.exception("Prompt lookup for %s failed; using fallback constant", key)
            return default

    def _resolve_model(self, tier: str) -> str:
        if tier == "light":
            return self.config.openai_model_light
        if tier == "mid":
            return self.config.openai_model_mid
        return self.config.openai_model_heavy

    @retry(exceptions=(APIError, APIStatusError, RateLimitError, ValueError))
    def _request_json(
        self,
        instructions: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        *,
        use_web_search: bool = True,
        reasoning_effort: str | None = None,
        model_tier: str = "heavy",
    ) -> dict[str, Any]:
        self.logger.debug("Calling OpenAI Responses API for %s", schema["name"])
        tools = [{"type": "web_search"}] if use_web_search else None
        effort = reasoning_effort or self.config.openai_reasoning_effort
        request_kwargs: dict[str, Any] = {
            "model": self._resolve_model(model_tier),
            "reasoning": {"effort": effort},
            "instructions": instructions,
            "input": to_toon(payload),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema["name"],
                    "schema": schema["schema"],
                    "strict": True,
                }
            },
        }
        if tools:
            request_kwargs["tools"] = tools
        response = self.client.responses.create(
            **request_kwargs,
        )
        result = json.loads(response.output_text)
        return result

    def _provider_currency(self, provider: str) -> str:
        return self.config.provider_account_currency(provider)

    def build_symbol_payload(
        self,
        symbol: str,
        category: str,
        candles: list[dict[str, Any]],
        existing_trades: list[dict[str, Any]],
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        return {
            "constraints": {
                "direction": "LONG",
                "web_search_required": True,
                "no_etf": True,
                "currency": self._provider_currency(provider),
                "provider": provider,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
            "category": category,
            "symbol": symbol,
            "ohlcv": build_mixed_timeframe_ohlcv(candles),
            "existing_trades": existing_trades,
        }

    def build_batch_symbol_entry(
        self,
        symbol: str,
        candles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "ohlcv": build_mixed_timeframe_ohlcv(candles),
        }

    def request_new_signal(
        self,
        symbol: str,
        category: str,
        candles: list[dict[str, Any]],
        existing_trades: list[dict[str, Any]],
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        payload = self.build_symbol_payload(symbol, category, candles, existing_trades, provider=provider)
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_NEW_SIGNAL, provider)
        default = INSTRUCTIONS_NEW_SIGNAL
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            NEW_SIGNAL_SCHEMA,
        )

    def request_batch_trade_signals(
        self,
        category: str,
        symbol_payloads: list[dict[str, Any]],
        existing_trades: list[dict[str, Any]],
        max_new_trades: int,
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        payload = {
            "constraints": {
                "direction": "LONG",
                "web_search_required": True,
                "currency": self._provider_currency(provider),
                "provider": provider,
                "risk_tolerance": self.config.risk_tolerance,
                "category": category,
                "max_new_trades_this_cycle": max_new_trades,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
            "symbols": symbol_payloads,
            "existing_trades": existing_trades,
        }
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_BATCH_SIGNALS, provider)
        default = INSTRUCTIONS_BATCH_SIGNALS
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            BATCH_SIGNALS_SCHEMA,
        )

    def request_universe_symbol_dossier(
        self,
        category: str,
        candidate: dict[str, Any],
        peer_context: dict[str, Any],
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        payload = {
            "selection_rules": {
                "category": category,
                "currency": self._provider_currency(provider),
                "provider": provider,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
                "score_scale": "0_to_100_higher_is_better",
            },
            "candidate": candidate,
            "peer_context": peer_context,
        }
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_UNIVERSE_DOSSIER, provider)
        default = INSTRUCTIONS_UNIVERSE_DOSSIER
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            UNIVERSE_SYMBOL_DOSSIER_SCHEMA,
            use_web_search=True,
            reasoning_effort="low",
            model_tier="light",
        )

    def request_universe_batch_shortlist(
        self,
        category: str,
        candidates: list[dict[str, Any]],
        shortlist_size: int,
        batch_number: int,
        batch_count: int,
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        payload = {
            "selection_rules": {
                "category": category,
                "shortlist_size": shortlist_size,
                "batch_number": batch_number,
                "batch_count": batch_count,
                "currency": self._provider_currency(provider),
                "provider": provider,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
                "criteria": {
                    "growth_potential": "fundamental or technical catalysts",
                    "safety": "avoid highly speculative or penny stocks",
                    "stocks_preference": "solid earnings, revenue growth, sector leadership, multi-week or multi-month catalysts",
                    "crypto_preference": "established assets with solid market cap, ecosystem activity, and durable narratives",
                    "momentum_focus": "positive medium-term momentum, strong fundamentals, low downside risk",
                },
            },
            "candidates": candidates,
        }
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_UNIVERSE_SHORTLIST, provider)
        default = INSTRUCTIONS_UNIVERSE_SHORTLIST
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            UNIVERSE_BATCH_SHORTLIST_SCHEMA,
            model_tier="mid",
        )

    def request_universe_final_selection(
        self,
        category: str,
        shortlisted_candidates: list[dict[str, Any]],
        required_count: int,
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        payload = {
            "selection_rules": {
                "category": category,
                "required_count": required_count,
                "currency": self._provider_currency(provider),
                "provider": provider,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
            "shortlisted_candidates": shortlisted_candidates,
        }
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_UNIVERSE_FINAL, provider)
        default = INSTRUCTIONS_UNIVERSE_FINAL
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            UNIVERSE_FINAL_SCHEMA,
        )

    def request_universe_final_selection_from_dossiers(
        self,
        category: str,
        dossiers: list[dict[str, Any]],
        required_count: int,
        current_universe: list[str] | None = None,
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        payload = {
            "selection_rules": {
                "category": category,
                "required_count": required_count,
                "currency": self._provider_currency(provider),
                "provider": provider,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
                "prefer_diversification": True,
                "current_universe": current_universe or [],
            },
            "candidate_dossiers": dossiers,
        }
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_UNIVERSE_FINAL_FROM_DOSSIERS, provider)
        default = INSTRUCTIONS_UNIVERSE_FINAL_FROM_DOSSIERS
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            UNIVERSE_DOSSIER_FINAL_SCHEMA,
            use_web_search=False,
            reasoning_effort="low",
            model_tier="light",
        )

    def request_pending_trade_review(
        self,
        trade: dict[str, Any],
        candles: list[dict[str, Any]],
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        payload = {
            "constraints": {
                "direction": "LONG",
                "web_search_required": True,
                "currency": self._provider_currency(provider),
                "provider": provider,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "pending_days_threshold": 7,
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
            "trade": trade,
            "ohlcv": build_mixed_timeframe_ohlcv(candles),
        }
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_PENDING_REVIEW, provider)
        default = INSTRUCTIONS_PENDING_REVIEW
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            PENDING_REVIEW_SCHEMA,
        )

    def request_open_trade_protection_review(
        self,
        trade: dict[str, Any],
        candles: list[dict[str, Any]],
        provider: str = "alpaca",
    ) -> dict[str, Any]:
        payload = {
            "constraints": {
                "direction": "LONG",
                "web_search_required": True,
                "currency": self._provider_currency(provider),
                "provider": provider,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "review_frequency": "six_times_per_day",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
            "trade": trade,
            "ohlcv": {"daily": candles, "weekly": []},
        }
        prompt_key = _resolve_provider_prompt_key(PROMPT_KEY_PROTECTION_REVIEW, provider)
        default = INSTRUCTIONS_PROTECTION_REVIEW
        return self._request_json(
            self._resolve_prompt(prompt_key, default),
            payload,
            OPEN_PROTECTION_REVIEW_SCHEMA,
            model_tier="mid",
        )

    # `build_batch_symbol_entry` is already provider-agnostic.
