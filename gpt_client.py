"""OpenAI integration for universe selection and trade decisions."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import APIError, APIStatusError, OpenAI, RateLimitError

from utils import AppConfig, retry, to_json, trim_ohlcv_payload

NEW_SIGNAL_SCHEMA = {
    "name": "new_trade_signal",
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["OPEN", "SKIP"]},
            "symbol": {"type": "string"},
            "entry_price": {"type": ["number", "null"]},
            "take_profit": {"type": ["number", "null"]},
            "stop_loss": {"type": ["number", "null"]},
            "trailing_stop_distance": {"type": ["number", "null"]},
            "confidence": {"type": ["number", "null"]},
            "reasoning": {"type": "string"},
        },
        "required": [
            "action",
            "symbol",
            "entry_price",
            "take_profit",
            "stop_loss",
            "trailing_stop_distance",
            "confidence",
            "reasoning",
        ],
        "additionalProperties": False,
    },
}

UNIVERSE_SCHEMA = {
    "name": "weekly_universe",
    "schema": {
        "type": "object",
        "properties": {
            "stocks": {"type": "array", "items": {"type": "string"}},
            "crypto": {"type": "array", "items": {"type": "string"}},
            "reasoning": {"type": "string"},
        },
        "required": ["stocks", "crypto", "reasoning"],
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
    def _request_json(self, instructions: str, payload: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        self.logger.debug("Calling OpenAI Responses API for %s", schema["name"])
        response = self.client.responses.create(
            model="gpt-5.2",
            reasoning={"effort": "low"},
            instructions=instructions,
            input=to_json(payload),
            tools=[{"type": "web_search"}],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema["name"],
                    "schema": schema["schema"],
                    "strict": True,
                }
            },
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
            "Return only JSON matching the schema. If risk/reward is unattractive, choose SKIP. "
            "If you choose OPEN, entry_price, take_profit, and stop_loss must be non-null positive numbers. "
            "trailing_stop_distance may be null when no trailing stop is desired, otherwise it must be a positive number. "
            "Base the decision primarily on medium-term trend structure, macro or fundamental catalysts, business or ecosystem strength, and multi-week or multi-month risk/reward. "
            "The script manages take-profit, stop-loss, and trailing-stop logic internally after entry; Alpaca is used only to place the entry order and to close the position at market when a rule triggers."
        )
        payload = self.build_symbol_payload(symbol, category, candles, existing_trades)
        return self._request_json(instructions, payload, NEW_SIGNAL_SCHEMA)

    def request_trading_universe(
        self,
        stock_candidates: list[dict[str, Any]],
        crypto_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        instructions = (
            f"Select exactly {self.config.weekly_universe_stocks} stock symbols and {self.config.weekly_universe_crypto} crypto symbols for the next trading cycle. "
            "Do mandatory web search before choosing. Exclude ETFs and avoid illiquid names. "
            "Avoid warrants, rights, units, preferred shares, shell companies, and other non-common-stock instruments. "
            "Use the provided Alpaca candidate lists as the only allowed universe. "
            "This strategy is medium-long term position trading, not daily trading. "
            f"Favor assets suitable for holding roughly {self.config.strategy_horizon_days_min}-{self.config.strategy_horizon_days_max} days, and potentially 3-4 months if the thesis remains intact. "
            "Base the selection on tradability, liquidity proxies, business relevance, current news flow, and sentiment analysis from web search. "
            "Prioritize symbols with strong growth potential, driven by fundamental or technical catalysts, while ensuring relative safety by avoiding highly speculative or penny stocks. "
            "For stocks, prefer companies with solid earnings, revenue growth, sector leadership, and catalysts that can play out over multiple weeks or months. "
            "For crypto, prefer established assets with solid market capitalization, active ecosystem participation, and durable narratives rather than short-lived hype. "
            "Focus on positive momentum, strong fundamentals, and low downside risk in all selections. "
            # ------------------------------------------------
            f"Use {self.config.currency} as the reference currency. "
            f"For crypto, return only symbols quoted in {self.config.currency}. "
            f"Crypto symbols must be returned in Alpaca pair format like BTC/{self.config.currency}, never bare tickers like BTC. "
            "Return only JSON matching the schema."
        )

        payload = {
            "stock_candidates": stock_candidates,
            "crypto_candidates": crypto_candidates,
            "selection_rules": {
                "stocks_required": self.config.weekly_universe_stocks,
                "crypto_required": self.config.weekly_universe_crypto,
                "currency": self.config.currency,
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
        
        return self._request_json(instructions, payload, UNIVERSE_SCHEMA)

    def request_weekly_universe(
        self,
        stock_candidates: list[dict[str, Any]],
        crypto_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self.request_trading_universe(stock_candidates, crypto_candidates)
