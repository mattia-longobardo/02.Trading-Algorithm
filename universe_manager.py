"""Universe selection and persistence."""

from __future__ import annotations

import logging

from alpaca_client import AlpacaClient
from gpt_client import GPTClient
from utils import AppConfig, read_universe_file, write_json_file, write_universe_file


class UniverseManager:
    """Select and persist the active trading universe."""

    MAX_STOCK_CANDIDATES_FOR_GPT = 120
    MAX_CRYPTO_CANDIDATES_FOR_GPT = 80

    def __init__(self, config: AppConfig, logger: logging.Logger, alpaca_client: AlpacaClient, gpt_client: GPTClient) -> None:
        self.config = config
        self.logger = logger.getChild("universe")
        self.alpaca_client = alpaca_client
        self.gpt_client = gpt_client

    def _write_candidate_lists(
        self,
        stock_payload: list[dict[str, str | bool | float | None]],
        crypto_payload: list[dict[str, str | bool | float | None]],
    ) -> None:
        write_json_file(
            self.config.universe_log_file,
            {
                "STOCK": stock_payload,
                "CRYPTO": crypto_payload,
            },
        )

    @staticmethod
    def _looks_like_etf(asset: object) -> bool:
        name = str(getattr(asset, "name", "")).lower()
        symbol = str(getattr(asset, "symbol", "")).lower()
        return any(token in name for token in (" etf", " fund", " trust", " etn", " etp", " index")) or symbol.endswith("x")

    @staticmethod
    def _looks_like_non_common_stock(asset: object) -> bool:
        name = str(getattr(asset, "name", "")).lower()
        return any(
            token in name
            for token in (
                " warrant",
                " rights",
                " right",
                " units",
                " unit",
                " depositary",
                " preferred",
                " redeemable",
            )
        )

    def _get_stock_candidates(self) -> list[str]:
        assets = self.alpaca_client.list_assets("US_EQUITY")
        candidates = [
            asset.symbol
            for asset in assets
            if getattr(asset, "tradable", False)
            and getattr(asset, "status", "").lower() == "active"
            and not self._looks_like_etf(asset)
            and not self._looks_like_non_common_stock(asset)
        ]
        return sorted(set(candidates))

    def _get_crypto_candidates(self) -> list[str]:
        assets = self.alpaca_client.list_assets("CRYPTO")
        quote_suffix = f"/{self.config.currency}"
        candidates = [
            asset.symbol
            for asset in assets
            if getattr(asset, "tradable", False)
            and getattr(asset, "status", "").lower() == "active"
            and str(getattr(asset, "symbol", "")).upper().endswith(quote_suffix)
        ]
        return sorted(set(candidates))

    @staticmethod
    def _asset_snapshot(asset: object) -> dict[str, str | bool | float | None]:
        return {
            "symbol": str(getattr(asset, "symbol", "")).upper(),
            "name": str(getattr(asset, "name", "")).strip(),
            "status": str(getattr(asset, "status", "")).lower(),
            "tradable": bool(getattr(asset, "tradable", False)),
            "fractionable": bool(getattr(asset, "fractionable", False)),
        }

    def _get_stock_candidate_payload(self) -> list[dict[str, str | bool | float | None]]:
        assets = self.alpaca_client.list_assets("US_EQUITY")
        payload = [
            self._asset_snapshot(asset)
            for asset in assets
            if getattr(asset, "tradable", False)
            and getattr(asset, "status", "").lower() == "active"
            and not self._looks_like_etf(asset)
            and not self._looks_like_non_common_stock(asset)
        ]
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload[: self.MAX_STOCK_CANDIDATES_FOR_GPT]

    def _get_crypto_candidate_payload(self) -> list[dict[str, str | bool | float | None]]:
        assets = self.alpaca_client.list_assets("CRYPTO")
        quote_suffix = f"/{self.config.currency}"
        payload = [
            self._asset_snapshot(asset)
            for asset in assets
            if getattr(asset, "tradable", False)
            and getattr(asset, "status", "").lower() == "active"
            and str(getattr(asset, "symbol", "")).upper().endswith(quote_suffix)
        ]
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload[: self.MAX_CRYPTO_CANDIDATES_FOR_GPT]

    def _sanitize_stock_selection(self, symbols: list[str], valid_candidates: set[str]) -> list[str]:
        selected: list[str] = []
        for symbol in symbols:
            normalized = str(symbol).upper().strip()
            if normalized in valid_candidates and normalized not in selected:
                selected.append(normalized)
        return selected

    def _sanitize_crypto_selection(self, symbols: list[str], valid_candidates: set[str]) -> list[str]:
        selected: list[str] = []
        for symbol in symbols:
            normalized = str(symbol).upper().strip()
            candidates_to_try = [normalized]
            if "/" not in normalized:
                candidates_to_try.insert(0, f"{normalized}/{self.config.currency}")
            for candidate in candidates_to_try:
                if candidate in valid_candidates and candidate not in selected:
                    selected.append(candidate)
                    break
        return selected

    def select_trading_universe(self) -> dict[str, list[str]]:
        stock_payload = self._get_stock_candidate_payload()
        crypto_payload = self._get_crypto_candidate_payload()
        self._write_candidate_lists(stock_payload, crypto_payload)
        stock_candidates = [str(asset["symbol"]) for asset in stock_payload]
        crypto_candidates = [str(asset["symbol"]) for asset in crypto_payload]
        try:
            result = self.gpt_client.request_trading_universe(stock_payload, crypto_payload)
        except Exception:
            self.logger.exception("GPT trading universe selection failed; saving empty universe")
            universe = {"STOCK": [], "CRYPTO": []}
            write_universe_file(universe)
            self.logger.info("Selected empty trading universe after GPT failure")
            return universe
        valid_stock_candidates = set(stock_candidates)
        valid_crypto_candidates = set(crypto_candidates)
        stocks = self._sanitize_stock_selection(result["stocks"], valid_stock_candidates)
        crypto = self._sanitize_crypto_selection(result["crypto"], valid_crypto_candidates)
        universe = {
            "STOCK": stocks[: self.config.weekly_universe_stocks],
            "CRYPTO": crypto[: self.config.weekly_universe_crypto],
        }
        write_universe_file(universe)
        self.logger.info("Selected trading universe: %s", universe)
        return universe

    def select_weekly_universe(self) -> dict[str, list[str]]:
        return self.select_trading_universe()

    def get_current_universe(self) -> dict[str, list[str]]:
        return read_universe_file()
