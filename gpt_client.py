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
            "web_search_sources": {"type": "array", "items": {"type": "string"}},
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
            "web_search_sources",
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
            "web_search_sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "action",
            "symbol",
            "new_take_profit",
            "new_stop_loss",
            "new_trailing_stop_distance",
            "close_immediately",
            "reasoning",
            "web_search_sources",
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
            "Use only LONG spot trading, never short, never ETF. Compute technical indicators yourself from OHLCV. "
            f"For both stocks and crypto, use {self.config.currency} as the reference currency. "
            f"For crypto, only consider symbols quoted in {self.config.currency}. "
            "Return only JSON matching the schema. If risk/reward is unattractive, choose SKIP. "
            "If you choose OPEN, entry_price, take_profit, stop_loss, and trailing_stop_distance must all be non-null positive numbers."
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
            "You may HOLD, UPDATE, CLOSE, or CANCEL. Do not propose a new entry. Return only JSON matching the schema."
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
                "exclude_etf": True,
                "currency": self.config.currency,
                "must_choose_only_from_candidates": True,
                "prefer_large_cap_and_high_attention": True,
            },
        }
        return self._request_json(instructions, payload, UNIVERSE_SCHEMA)
