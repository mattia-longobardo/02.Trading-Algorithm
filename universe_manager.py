"""Universe selection and persistence."""

from __future__ import annotations

import logging

from alpaca_client import AlpacaClient
from gpt_client import GPTClient
from utils import AppConfig, read_universe_file, write_json_file, write_universe_file


class UniverseManager:
    """Select and persist the active trading universe."""

    STOCK_BATCH_SIZE = 120
    CRYPTO_BATCH_SIZE = 80
    SHORTLIST_MULTIPLIER = 3

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
    def _dedupe_payload_by_symbol(
        payload: list[dict[str, str | bool | float | None]],
    ) -> list[dict[str, str | bool | float | None]]:
        seen: set[str] = set()
        deduped: list[dict[str, str | bool | float | None]] = []
        for asset in payload:
            symbol = str(asset.get("symbol", "")).upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            deduped.append(asset)
        return deduped

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
        payload = self._dedupe_payload_by_symbol(payload)
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload

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
        payload = self._dedupe_payload_by_symbol(payload)
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload

    @staticmethod
    def _chunk_payload(
        payload: list[dict[str, str | bool | float | None]],
        batch_size: int,
    ) -> list[list[dict[str, str | bool | float | None]]]:
        if batch_size <= 0:
            return [payload]
        return [payload[index : index + batch_size] for index in range(0, len(payload), batch_size)]

    @staticmethod
    def _filter_payload_by_symbols(
        payload: list[dict[str, str | bool | float | None]],
        symbols: list[str],
    ) -> list[dict[str, str | bool | float | None]]:
        wanted = {str(symbol).upper().strip() for symbol in symbols}
        return [asset for asset in payload if str(asset.get("symbol", "")).upper() in wanted]

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

    def _select_category_universe(
        self,
        category: str,
        payload: list[dict[str, str | bool | float | None]],
        required_count: int,
        batch_size: int,
    ) -> list[str]:
        if not payload or required_count <= 0:
            return []

        batches = self._chunk_payload(payload, batch_size)
        shortlist_size = min(max(required_count * self.SHORTLIST_MULTIPLIER, required_count), batch_size)
        shortlisted_payload: list[dict[str, str | bool | float | None]] = []
        seen_symbols: set[str] = set()

        for batch_index, batch in enumerate(batches, start=1):
            result = self.gpt_client.request_universe_batch_shortlist(
                category=category,
                candidates=batch,
                shortlist_size=min(shortlist_size, len(batch)),
                batch_number=batch_index,
                batch_count=len(batches),
            )
            valid_symbols = {str(asset["symbol"]).upper() for asset in batch}
            if category == "STOCK":
                selected_symbols = self._sanitize_stock_selection(result.get("symbols", []), valid_symbols)
            else:
                selected_symbols = self._sanitize_crypto_selection(result.get("symbols", []), valid_symbols)

            for asset in self._filter_payload_by_symbols(batch, selected_symbols):
                symbol = str(asset.get("symbol", "")).upper()
                if symbol in seen_symbols:
                    continue
                seen_symbols.add(symbol)
                shortlisted_payload.append(asset)

        if not shortlisted_payload:
            return []

        final_result = self.gpt_client.request_universe_final_selection(
            category=category,
            shortlisted_candidates=shortlisted_payload,
            required_count=min(required_count, len(shortlisted_payload)),
        )
        valid_shortlist_symbols = {str(asset["symbol"]).upper() for asset in shortlisted_payload}
        if category == "STOCK":
            return self._sanitize_stock_selection(final_result.get("symbols", []), valid_shortlist_symbols)[:required_count]
        return self._sanitize_crypto_selection(final_result.get("symbols", []), valid_shortlist_symbols)[:required_count]

    def select_trading_universe(self) -> dict[str, list[str]]:
        full_stock_payload = self._get_stock_candidate_payload()
        full_crypto_payload = self._get_crypto_candidate_payload()
        self._write_candidate_lists(full_stock_payload, full_crypto_payload)
        try:
            stocks = self._select_category_universe(
                category="STOCK",
                payload=full_stock_payload,
                required_count=self.config.weekly_universe_stocks,
                batch_size=self.STOCK_BATCH_SIZE,
            )
            crypto = self._select_category_universe(
                category="CRYPTO",
                payload=full_crypto_payload,
                required_count=self.config.weekly_universe_crypto,
                batch_size=self.CRYPTO_BATCH_SIZE,
            )
        except Exception:
            self.logger.exception("GPT trading universe selection failed; saving empty universe")
            universe = {"STOCK": [], "CRYPTO": []}
            write_universe_file(universe)
            self.logger.info("Selected empty trading universe after GPT failure")
            return universe
        universe = {
            "STOCK": stocks,
            "CRYPTO": crypto,
        }
        write_universe_file(universe)
        self.logger.info("Selected trading universe: %s", universe)
        return universe

    def select_weekly_universe(self) -> dict[str, list[str]]:
        return self.select_trading_universe()

    def get_current_universe(self) -> dict[str, list[str]]:
        return read_universe_file()
