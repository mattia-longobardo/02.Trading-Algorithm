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

MANAGE_SIGNAL_SCHEMA = {
    "name": "manage_trade_signal",
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["HOLD", "UPDATE", "CLOSE", "CANCEL"]},
            "symbol": {"type": "string"},
            "new_take_profit": {"type": ["number", "null"]},
            "new_stop_loss": {"type": ["number", "null"]},
            "new_trailing_stop_distance": {"type": ["number", "null"]},
            "close_immediately": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": [
            "action",
            "symbol",
            "new_take_profit",
            "new_stop_loss",
            "new_trailing_stop_distance",
            "close_immediately",
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
        self.logger.info("Calling OpenAI Responses API for %s", schema["name"])
        response = self.client.responses.create(
            model="gpt-5.4",
            reasoning={"effort": "medium"},
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
            f"For both stocks and crypto, use {self.config.currency} as the reference currency. "
            f"For crypto, only consider symbols quoted in {self.config.currency}. "
            "Return only JSON matching the schema. If risk/reward is unattractive, choose SKIP. "
            "If you choose OPEN, entry_price, take_profit, stop_loss, and trailing_stop_distance must all be non-null positive numbers. "
            "Important: when Alpaca supports it, this bot opens the position first and then places a broker-side trailing stop as a separate sell order. "
            "Alpaca does not support a trailing stop as a native bracket leg, so take_profit is then bot-managed metadata rather than a linked broker-side take-profit order."
        )
        payload = self.build_symbol_payload(symbol, category, candles, existing_trades)
        return self._request_json(instructions, payload, NEW_SIGNAL_SCHEMA)

    def request_trade_management(
        self,
        symbol: str,
        category: str,
        candles: list[dict[str, Any]],
        existing_trades: list[dict[str, Any]],
    ) -> dict[str, Any]:
        instructions = (
            "You are managing an existing long trade or pending order. You must perform web search before deciding. "
            f"For both stocks and crypto, use {self.config.currency} as the reference currency. "
            f"For crypto, keep all reasoning aligned with symbols quoted in {self.config.currency}. "
            "You may HOLD, UPDATE, CLOSE, or CANCEL. Do not propose a new entry. "
            "When updating levels, remember that Alpaca trailing stops are supported only as separate single orders, not as bracket legs. "
            "So for trailing-stop trades, the broker-managed value is trailing_stop_distance, while take_profit remains bot-managed and stop_loss is analytical context. "
            "Return only JSON matching the schema."
        )
        payload = self.build_symbol_payload(symbol, category, candles, existing_trades)
        return self._request_json(instructions, payload, MANAGE_SIGNAL_SCHEMA)

    def request_weekly_universe(
        self,
        stock_candidates: list[dict[str, Any]],
        crypto_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        instructions = (
            f"Select exactly {self.config.weekly_universe_stocks} stock symbols and {self.config.weekly_universe_crypto} crypto symbols for the coming week. "
            "Do mandatory web search before choosing. Exclude ETFs and avoid illiquid names. "
            "Avoid warrants, rights, units, preferred shares, shell companies, and other non-common-stock instruments. "
            "Use the provided Alpaca candidate lists as the only allowed universe. "
            "Base the selection on tradability, liquidity proxies, business relevance, current news flow, and sentiment analysis from web search. "
            "Prioritize symbols with strong growth potential, driven by fundamental or technical catalysts, while ensuring relative safety by avoiding highly speculative or penny stocks. "
            "For stocks, prefer companies with solid earnings, revenue growth, and sector leadership. "
            "For crypto, prefer established assets with solid market capitalization and active ecosystem participation. "
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
                "criteria": {
                    "growth_potential": "fundamental or technical catalysts",
                    "safety": "avoid highly speculative or penny stocks",
                    "stocks_preference": "solid earnings, revenue growth, sector leadership",
                    "crypto_preference": "established assets with solid market cap and ecosystem activity",
                    "momentum_focus": "positive momentum, strong fundamentals, low downside risk"
                }
            },
        }
        
        return self._request_json(instructions, payload, UNIVERSE_SCHEMA)
