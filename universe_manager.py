"""Universe selection and persistence."""

from __future__ import annotations

import logging

from alpaca_client import AlpacaClient
from gpt_client import GPTClient
from utils import AppConfig, read_universe_file, write_universe_file


class UniverseManager:
    """Select and persist the weekly trading universe."""

    def __init__(self, config: AppConfig, logger: logging.Logger, alpaca_client: AlpacaClient, gpt_client: GPTClient) -> None:
        self.config = config
        self.logger = logger.getChild("universe")
        self.alpaca_client = alpaca_client
        self.gpt_client = gpt_client

    @staticmethod
    def _looks_like_etf(asset: object) -> bool:
        name = str(getattr(asset, "name", "")).lower()
        symbol = str(getattr(asset, "symbol", "")).lower()
        return any(token in name for token in (" etf", " fund", " trust", " etn", " etp", " index")) or symbol.endswith("x")

    def _get_stock_candidates(self) -> list[str]:
        assets = self.alpaca_client.list_assets("US_EQUITY")
        candidates = [
            asset.symbol
            for asset in assets
            if getattr(asset, "tradable", False)
            and getattr(asset, "status", "").lower() == "active"
            and not self._looks_like_etf(asset)
        ]
        return sorted(set(candidates))

    def _get_crypto_candidates(self) -> list[str]:
        assets = self.alpaca_client.list_assets("CRYPTO")
        candidates = [
            asset.symbol
            for asset in assets
            if getattr(asset, "tradable", False) and getattr(asset, "status", "").lower() == "active"
        ]
        return sorted(set(candidates))

    def select_weekly_universe(self) -> dict[str, list[str]]:
        stock_candidates = self._get_stock_candidates()
        crypto_candidates = self._get_crypto_candidates()
        result = self.gpt_client.request_weekly_universe(stock_candidates, crypto_candidates)
        universe = {"STOCK": result["stocks"][:10], "CRYPTO": result["crypto"][:10]}
        write_universe_file(universe)
        self.logger.info("Selected weekly universe: %s", universe)
        return universe

    def get_current_universe(self) -> dict[str, list[str]]:
        return read_universe_file()
