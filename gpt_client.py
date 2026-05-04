"""OpenAI integration for universe selection and trade decisions."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import APIError, APIStatusError, OpenAI, RateLimitError

from utils import AppConfig, retry, to_toon, trim_ohlcv_payload

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
            "reasoning": {"type": "string"},
        },
        "required": ["trailing_take_profit_distance", "reasoning"],
        "additionalProperties": False,
    },
}


class GPTClient:
    """OpenAI Responses API wrapper with mandatory web search."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger.getChild("gpt")
        self.client = OpenAI(api_key=config.openai_api_key)

    @retry(exceptions=(APIError, APIStatusError, RateLimitError, ValueError))
    def _request_json(
        self,
        instructions: str,
        payload: dict[str, Any],
        schema: dict[str, Any],
        *,
        use_web_search: bool = True,
        reasoning_effort: str = "medium",
    ) -> dict[str, Any]:
        self.logger.debug("Calling OpenAI Responses API for %s", schema["name"])
        tools = [{"type": "web_search"}] if use_web_search else None
        request_kwargs: dict[str, Any] = {
            "model": "gpt-5.4",
            "reasoning": {"effort": reasoning_effort},
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

    def build_symbol_payload(
        self,
        symbol: str,
        category: str,
        candles: list[dict[str, Any]],
        existing_trades: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "category": category,
            "ohlcv_daily": trim_ohlcv_payload(candles),
            "existing_trades": existing_trades,
            "constraints": {
                "direction": "LONG",
                "web_search_required": True,
                "no_etf": True,
                "currency": self.config.currency,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
        }

    def request_new_signal(
        self,
        symbol: str,
        category: str,
        candles: list[dict[str, Any]],
        existing_trades: list[dict[str, Any]],
    ) -> dict[str, Any]:
        instructions = (
            "You are a disciplined trading analyst. You must perform web search before deciding. "
            "Use only LONG spot trading, never short. Compute technical indicators yourself from OHLCV. "
            "This strategy is medium-long term position trading, not daily trading or intraday speculation. "
            f"Prefer setups that can reasonably be held for about {self.config.strategy_horizon_days_min}-{self.config.strategy_horizon_days_max} days, and can remain open for 3-4 months when the thesis stays valid. "
            "Do not optimize for quick daily flips, small intraday moves, or noise-driven momentum. "
            f"For both stocks and crypto, use {self.config.currency} as the reference currency. "
            f"For crypto, only consider symbols quoted in {self.config.currency}. "
            f"The user risk tolerance is {self.config.risk_tolerance} on a 1-10 scale, where 10 is the highest risk appetite. "
            "Use that setting explicitly: low values should favor resilient, liquid, lower-volatility setups with tighter downside control; high values may accept more volatility and more aggressive upside theses. "
            "Return only JSON matching the schema. If risk/reward is unattractive, choose SKIP. "
            "If you choose OPEN, entry_price, take_profit, and stop_loss must be non-null positive numbers. "
            "trailing_take_profit_distance may be null when no trailing take profit is desired, otherwise it must be a positive number. "
            "trailing_stop_distance may be null when no trailing stop is desired, otherwise it must be a positive number. "
            "trade_score must be a 0-100 score balancing expected profitability against risk after considering the user risk tolerance. "
            "Base the decision primarily on medium-term trend structure, macro or fundamental catalysts, business or ecosystem strength, and multi-week or multi-month risk/reward. "
            "The script manages take-profit, trailing-take-profit, stop-loss, and trailing-stop logic internally after entry; "
            "Alpaca is used only to place the entry order and to close the position at market when a rule triggers. "
            "A trailing take profit, when provided, activates only after price has reached the take_profit level, then trails the high-water mark by the specified distance."
        )
        payload = self.build_symbol_payload(symbol, category, candles, existing_trades)
        return self._request_json(instructions, payload, NEW_SIGNAL_SCHEMA)

    def request_batch_trade_signals(
        self,
        category: str,
        symbol_payloads: list[dict[str, Any]],
        existing_trades: list[dict[str, Any]],
        max_new_trades: int,
    ) -> dict[str, Any]:
        instructions = (
            f"You are evaluating a batch of {category} symbols for a medium-long term LONG-only trading strategy. "
            "You must perform web search before deciding. "
            "Analyze every provided symbol and return one result per symbol in the same batch. "
            "This is not day trading: focus on setups likely to play out over weeks or months. "
            f"Use {self.config.currency} as the reference currency, and for crypto only consider pairs quoted in {self.config.currency}. "
            f"The user risk tolerance is {self.config.risk_tolerance} on a 1-10 scale, where 10 means maximum tolerated risk. "
            "Low risk tolerance should emphasize quality, liquidity, drawdown control, and more conservative levels. "
            "High risk tolerance can accept more volatility, wider stops, and more speculative catalysts if the upside is compelling. "
            f"The portfolio can open at most {max_new_trades} new {category} trades in this cycle. "
            "For every symbol return OPEN or SKIP. OPEN means the setup is attractive today. "
            "When OPEN is chosen, entry_price, take_profit, and stop_loss must be positive numbers. "
            "trailing_take_profit_distance may be null or a positive number. "
            "trailing_stop_distance may be null or a positive number. "
            "trade_score must be a 0-100 score balancing profitability and risk for this user; the highest scores should represent the best risk-adjusted opportunities to open first. "
            "Return only JSON matching the schema."
        )
        payload = {
            "category": category,
            "symbols": symbol_payloads,
            "existing_trades": existing_trades,
            "constraints": {
                "direction": "LONG",
                "web_search_required": True,
                "currency": self.config.currency,
                "risk_tolerance": self.config.risk_tolerance,
                "max_new_trades_this_cycle": max_new_trades,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
        }
        return self._request_json(instructions, payload, BATCH_SIGNALS_SCHEMA)

    def request_universe_symbol_dossier(
        self,
        category: str,
        candidate: dict[str, Any],
        peer_context: dict[str, Any],
    ) -> dict[str, Any]:
        instructions = (
            f"Create a compact JSON dossier for one weekly {category} universe candidate. "
            "Do mandatory web search before deciding. "
            "Use both the provided local market metrics and current web information. "
            "This is a medium-long term position-trading strategy, not intraday trading. "
            f"Favor setups suitable for roughly {self.config.strategy_horizon_days_min}-{self.config.strategy_horizon_days_max} days, and possibly 3-4 months if the thesis remains intact. "
            f"The user risk tolerance is {self.config.risk_tolerance} on a 1-10 scale, where 10 means maximum risk appetite. "
            "Score quality, liquidity, momentum, downside control, and fit for this strategy on a 0-100 scale where higher is better. "
            "Use recent news, catalysts, sentiment, and business or ecosystem quality from web search. "
            "When the provided market metrics conflict with the web narrative, acknowledge that tension in the reasoning. "
            "Keep the summary concise and practical. "
            f"Use {self.config.currency} as the reference currency, and for crypto keep Alpaca pair format like BTC/{self.config.currency}. "
            "Return only JSON matching the schema."
        )
        payload = {
            "category": category,
            "candidate": candidate,
            "peer_context": peer_context,
            "selection_rules": {
                "currency": self.config.currency,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
                "score_scale": "0_to_100_higher_is_better",
            },
        }
        return self._request_json(
            instructions,
            payload,
            UNIVERSE_SYMBOL_DOSSIER_SCHEMA,
            use_web_search=True,
            reasoning_effort="low",
        )

    def request_universe_batch_shortlist(
        self,
        category: str,
        candidates: list[dict[str, Any]],
        shortlist_size: int,
        batch_number: int,
        batch_count: int,
    ) -> dict[str, Any]:
        instructions = (
            f"Review batch {batch_number} of {batch_count} for the weekly {category} universe selection. "
            "Do mandatory web search before choosing. Exclude ETFs and avoid illiquid names. "
            "Avoid warrants, rights, units, preferred shares, shell companies, and other non-common-stock instruments. "
            "Use only the provided Alpaca candidate list for this batch. "
            "When local market metrics are provided for a candidate, treat them as hard context and use them alongside web search. "
            "This strategy is medium-long term position trading, not daily trading. "
            f"Favor assets suitable for holding roughly {self.config.strategy_horizon_days_min}-{self.config.strategy_horizon_days_max} days, and potentially 3-4 months if the thesis remains intact. "
            f"The user risk tolerance is {self.config.risk_tolerance} on a 1-10 scale, where 10 means maximum risk appetite. "
            "Adjust the shortlist to this preference: low risk should favor larger, more liquid, more resilient names; high risk can include more aggressive growth or narrative-driven assets, but still avoid obvious low-quality instruments. "
            "Base the selection on tradability, liquidity proxies, business relevance, current news flow, and sentiment analysis from web search. "
            "Prefer stronger average dollar volume, constructive 20d/60d/120d trend, and candidates trading relatively close to their medium-term highs unless current news strongly contradicts the setup. "
            f"Prioritize {category} symbols with strong potential over the next months, driven by fundamental or technical catalysts, while keeping the selection coherent with the user risk tolerance. "
            "For stocks, prefer companies with solid earnings, revenue growth, sector leadership, and catalysts that can play out over multiple weeks or months. "
            "For crypto, prefer established assets with solid market capitalization, active ecosystem participation, and durable narratives rather than short-lived hype. "
            "Focus on positive momentum, strong fundamentals, and downside control appropriate for the selected risk profile. "
            f"Use {self.config.currency} as the reference currency. "
            f"For crypto, return only symbols quoted in {self.config.currency} and keep Alpaca pair format like BTC/{self.config.currency}. "
            f"Return up to {shortlist_size} symbols from this batch as the best intermediate shortlist for the final universe decision. "
            "Return only JSON matching the schema."
        )

        payload = {
            "category": category,
            "candidates": candidates,
            "selection_rules": {
                "shortlist_size": shortlist_size,
                "batch_number": batch_number,
                "batch_count": batch_count,
                "currency": self.config.currency,
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
                    "momentum_focus": "positive medium-term momentum, strong fundamentals, low downside risk"
                }
            },
        }

        return self._request_json(instructions, payload, UNIVERSE_BATCH_SHORTLIST_SCHEMA)

    def request_universe_final_selection(
        self,
        category: str,
        shortlisted_candidates: list[dict[str, Any]],
        required_count: int,
    ) -> dict[str, Any]:
        instructions = (
            f"Select exactly {required_count} {category} symbols for the weekly trading universe from the provided shortlist. "
            "Do mandatory web search before choosing. "
            "Use only the shortlisted candidates provided in this final consolidation step. "
            "When local market metrics are provided for a candidate, treat them as hard context and use them alongside web search. "
            "This strategy is medium-long term position trading, not daily trading. "
            f"The user risk tolerance is {self.config.risk_tolerance} on a 1-10 scale, where 10 means maximum risk appetite. "
            "Choose the strongest multi-month opportunities while balancing upside, liquidity, quality, and downside control according to that risk preference. "
            "Prefer candidates with stronger average dollar volume, constructive 20d/60d/120d trend, and better resilience relative to recent highs unless current news materially weakens the thesis. "
            f"Use {self.config.currency} as the reference currency. "
            f"For crypto, return only Alpaca pair symbols quoted in {self.config.currency}. "
            "Return only JSON matching the schema."
        )
        payload = {
            "category": category,
            "shortlisted_candidates": shortlisted_candidates,
            "selection_rules": {
                "required_count": required_count,
                "currency": self.config.currency,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
        }
        return self._request_json(instructions, payload, UNIVERSE_FINAL_SCHEMA)

    def request_universe_final_selection_from_dossiers(
        self,
        category: str,
        dossiers: list[dict[str, Any]],
        required_count: int,
        current_universe: list[str] | None = None,
    ) -> dict[str, Any]:
        instructions = (
            f"Select exactly {required_count} {category} symbols for the weekly trading universe from the provided candidate dossiers. "
            "Use only the dossier information provided in this final consolidation step. "
            "Do not invent candidates outside the dossier list. "
            "Optimize for overall portfolio quality, liquidity, conviction, and medium-term opportunity. "
            f"The user risk tolerance is {self.config.risk_tolerance} on a 1-10 scale, where 10 means maximum risk appetite. "
            "Prefer some diversification across themes or narratives when multiple candidates are similarly strong, rather than concentrating too heavily in near-duplicates. "
            "It is acceptable to keep some continuity with the current universe when dossier quality is still competitive, but do not keep a weaker name purely for continuity. "
            f"Use {self.config.currency} as the reference currency, and for crypto return only Alpaca pair symbols quoted in {self.config.currency}. "
            "Return only JSON matching the schema."
        )
        payload = {
            "category": category,
            "candidate_dossiers": dossiers,
            "selection_rules": {
                "required_count": required_count,
                "currency": self.config.currency,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
                "prefer_diversification": True,
                "current_universe": current_universe or [],
            },
        }
        return self._request_json(
            instructions,
            payload,
            UNIVERSE_DOSSIER_FINAL_SCHEMA,
            use_web_search=False,
            reasoning_effort="low",
        )

    def request_pending_trade_review(
        self,
        trade: dict[str, Any],
        candles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        instructions = (
            "You are reviewing an existing LONG entry order that has remained pending for more than seven days. "
            "You must perform web search before deciding. "
            "Decide whether the order thesis is still valid today. "
            "Return KEEP only if opening the trade at this stage is still attractive for a medium-long term position trade. "
            "Return CANCEL if the thesis is stale, invalidated, materially weaker, or no longer worth opening now. "
            f"Use {self.config.currency} as the reference currency and keep the user's risk tolerance of {self.config.risk_tolerance} in mind. "
            "Base the review on current news, medium-term trend structure, catalysts, and whether the original pending entry still offers good risk/reward. "
            "Return only JSON matching the schema."
        )
        payload = {
            "trade": trade,
            "ohlcv_daily": trim_ohlcv_payload(candles),
            "constraints": {
                "direction": "LONG",
                "web_search_required": True,
                "currency": self.config.currency,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "pending_days_threshold": 7,
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
        }
        return self._request_json(instructions, payload, PENDING_REVIEW_SCHEMA)

    def request_open_trade_protection_review(
        self,
        trade: dict[str, Any],
        candles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        instructions = (
            "You are reviewing an already OPEN LONG swing-position trade. "
            "You must perform web search before deciding. "
            "Your only task is to reassess the trailing take profit distance for this open trade. "
            "Return the full desired trailing_take_profit_distance for the trade right now: keep the current value if no change is needed, "
            "return a different positive number to tighten or loosen it, or return null to disable the trailing take profit. "
            "Do not propose entry, stop loss, or hard take profit changes here. "
            f"Use {self.config.currency} as the reference currency and keep the user's risk tolerance of {self.config.risk_tolerance} in mind. "
            "Base the review on current news, catalyst evolution, medium-term trend structure, current profit cushion, and whether upside should be given more room or protected more tightly. "
            "Return only JSON matching the schema."
        )
        payload = {
            "trade": trade,
            "ohlcv_daily": trim_ohlcv_payload(candles),
            "constraints": {
                "direction": "LONG",
                "web_search_required": True,
                "currency": self.config.currency,
                "risk_tolerance": self.config.risk_tolerance,
                "strategy_style": "medium_long_term_position_trading",
                "review_frequency": "twice_daily",
                "target_holding_period_days": {
                    "min": self.config.strategy_horizon_days_min,
                    "max": self.config.strategy_horizon_days_max,
                },
            },
        }
        return self._request_json(instructions, payload, OPEN_PROTECTION_REVIEW_SCHEMA)
