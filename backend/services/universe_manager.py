"""Universe selection and persistence.

The Alpaca path uses a three-stage flow (prefilter → parallel GPT
dossiers → final consolidation) for both stocks and crypto.
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from statistics import fmean, pstdev
from typing import Any, Mapping

from clients.gpt_client import GPTClient
from core.utils import (
    ALL_PROVIDERS,
    PROVIDER_ALPACA,
    PROVIDER_ETORO,
    AppConfig,
    ProviderUniverse,
    read_universe_file,
    universe_for_provider,
    utc_now,
    write_json_file,
    write_universe_file,
)


class UniverseManager:
    """Select and persist the active trading universe across all providers."""

    STOCK_BATCH_SIZE = 120
    CRYPTO_BATCH_SIZE = 80
    STOCK_MARKET_DATA_BATCH_SIZE = 100
    CRYPTO_MARKET_DATA_BATCH_SIZE = 60
    SHORTLIST_MULTIPLIER = 3
    STOCK_PREFILTER_MULTIPLIER = 72
    CRYPTO_PREFILTER_MULTIPLIER = 48
    STOCK_DOSSIER_MULTIPLIER = 6
    CRYPTO_DOSSIER_MULTIPLIER = 5
    STOCK_MIN_BAR_COUNT = 90
    CRYPTO_MIN_BAR_COUNT = 60
    STOCK_MIN_LAST_CLOSE = 5.0
    STOCK_MIN_AVG_DOLLAR_VOLUME_20D = 2_000_000.0
    CRYPTO_MIN_AVG_DOLLAR_VOLUME_20D = 1_000_000.0
    MAX_DOSSIER_WORKERS = 6

    def __init__(
        self,
        config: AppConfig,
        logger: logging.Logger,
        broker_clients: Mapping[str, Any] | Any | None = None,
        gpt_client: GPTClient | None = None,
        *,
        alpaca_client: Any | None = None,
    ) -> None:
        self.config = config
        self.logger = logger.getChild("universe")
        if isinstance(broker_clients, Mapping):
            self._brokers: dict[str, Any] = dict(broker_clients)
        elif broker_clients is not None:
            self._brokers = {PROVIDER_ALPACA: broker_clients}
        else:
            self._brokers = {}
        if alpaca_client is not None:
            self._brokers[PROVIDER_ALPACA] = alpaca_client
        if gpt_client is None:
            raise TypeError("UniverseManager requires a gpt_client")
        self.gpt_client = gpt_client

    @property
    def alpaca_client(self) -> Any | None:
        return self._brokers.get(PROVIDER_ALPACA)

    def broker(self, provider: str) -> Any | None:
        return self._brokers.get(provider)

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalize_symbol(symbol: Any) -> str:
        return str(symbol or "").upper().strip()

    @staticmethod
    def _dedupe_payload_by_symbol(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
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
        return any(
            token in name
            for token in (
                " etf", " exchange traded fund", " fund", " etn", " etp",
                " index fund", " index trust", " trust",
            )
        )

    @staticmethod
    def _looks_like_non_common_stock(asset: object) -> bool:
        name = str(getattr(asset, "name", "")).lower()
        return any(
            token in name
            for token in (
                " warrant", " rights", " right", " units", " unit",
                " depositary", " preferred", " redeemable",
            )
        )

    @staticmethod
    def _looks_like_shell_company(asset: object) -> bool:
        name = str(getattr(asset, "name", "")).lower()
        return any(
            token in name
            for token in (
                " acquisition corp", " acquisition corporation",
                " blank check", " shell company",
                " special purpose acquisition", " spac",
            )
        )

    @staticmethod
    def _asset_snapshot(asset: object) -> dict[str, Any]:
        return {
            "symbol": str(getattr(asset, "symbol", "")).upper(),
            "name": str(getattr(asset, "name", "")).strip(),
            "status": str(getattr(asset, "status", "")).lower(),
            "tradable": bool(getattr(asset, "tradable", False)),
            "fractionable": bool(getattr(asset, "fractionable", False)),
        }

    @staticmethod
    def _chunk_payload(payload: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
        if batch_size <= 0:
            return [payload]
        return [payload[index : index + batch_size] for index in range(0, len(payload), batch_size)]

    @staticmethod
    def _filter_payload_by_symbols(payload: list[dict[str, Any]], symbols: list[str]) -> list[dict[str, Any]]:
        wanted = {str(symbol).upper().strip() for symbol in symbols}
        return [asset for asset in payload if str(asset.get("symbol", "")).upper() in wanted]

    @staticmethod
    def _metric_average(values: list[float], digits: int = 2) -> float | None:
        if not values:
            return None
        return round(fmean(values), digits)

    @staticmethod
    def _percent_change(closes: list[float], offset: int) -> float | None:
        if len(closes) <= offset:
            return None
        base = closes[-(offset + 1)]
        latest = closes[-1]
        if base <= 0:
            return None
        return round(((latest / base) - 1.0) * 100.0, 2)

    # -- common Alpaca-style enrichment helpers ---------------------------

    def _compute_market_metrics(self, bars: list[dict[str, Any]], category: str) -> dict[str, Any]:
        ordered_bars = sorted(bars, key=lambda row: str(row.get("timestamp", "")))
        closes: list[float] = []
        volumes: list[float] = []
        dollar_volumes: list[float] = []

        for row in ordered_bars:
            close = self._safe_float(row.get("close"))
            volume = self._safe_float(row.get("volume"))
            if close is None or close <= 0 or volume is None or volume < 0:
                continue
            closes.append(close)
            volumes.append(volume)
            dollar_volumes.append(close * volume)

        metrics: dict[str, Any] = {
            "bar_count": len(closes),
            "last_close": round(closes[-1], 6) if closes else None,
            "avg_volume_20d": self._metric_average(volumes[-20:]),
            "avg_dollar_volume_20d": self._metric_average(dollar_volumes[-20:]),
            "return_20d_pct": self._percent_change(closes, 20),
            "return_60d_pct": self._percent_change(closes, 60),
            "return_120d_pct": self._percent_change(closes, 120),
            "distance_from_52w_high_pct": None,
            "realized_volatility_20d_pct": None,
        }
        if not closes:
            return metrics

        high_window = closes[-252:] if category == "STOCK" else closes[-180:]
        highest_close = max(high_window) if high_window else None
        if highest_close and highest_close > 0:
            metrics["distance_from_52w_high_pct"] = round(((closes[-1] / highest_close) - 1.0) * 100.0, 2)

        recent_closes = closes[-21:]
        daily_returns = [
            (current_close / previous_close) - 1.0
            for previous_close, current_close in zip(recent_closes, recent_closes[1:])
            if previous_close > 0
        ]
        if len(daily_returns) >= 10:
            annualization_factor = math.sqrt(252.0 if category == "STOCK" else 365.0)
            metrics["realized_volatility_20d_pct"] = round(pstdev(daily_returns) * annualization_factor * 100.0, 2)
        return metrics

    def _market_data_batch_size(self, category: str) -> int:
        if category == "STOCK":
            return self.STOCK_MARKET_DATA_BATCH_SIZE
        return self.CRYPTO_MARKET_DATA_BATCH_SIZE

    def _fetch_market_metrics_by_symbol(
        self,
        provider: str,
        category: str,
        symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        broker = self.broker(provider)
        if broker is None:
            return {}
        metrics_by_symbol: dict[str, dict[str, Any]] = {}
        start = utc_now() - timedelta(days=400)
        for symbol_batch in self._chunk_payload(
            [{"symbol": symbol} for symbol in symbols],
            self._market_data_batch_size(category),
        ):
            requested_symbols = [
                self._normalize_symbol(asset.get("symbol")) for asset in symbol_batch if asset.get("symbol")
            ]
            if not requested_symbols:
                continue
            try:
                batch_bars = broker.get_multi_bars(requested_symbols, category, start=start)
                if not isinstance(batch_bars, dict):
                    batch_bars = {}
            except Exception:
                self.logger.exception(
                    "Market-data enrichment failed for %s/%s batch of %s symbols; continuing without metrics",
                    provider,
                    category,
                    len(requested_symbols),
                )
                batch_bars = {}
            for symbol in requested_symbols:
                metrics_by_symbol[symbol] = self._compute_market_metrics(batch_bars.get(symbol, []), category)
        return metrics_by_symbol

    def _candidate_prefilter_score(self, asset: dict[str, Any], preferred_symbols: set[str]) -> float:
        symbol = self._normalize_symbol(asset.get("symbol"))
        avg_dollar_volume = max(self._safe_float(asset.get("avg_dollar_volume_20d")) or 0.0, 0.0)
        return_20d = self._safe_float(asset.get("return_20d_pct")) or 0.0
        return_60d = self._safe_float(asset.get("return_60d_pct")) or 0.0
        return_120d = self._safe_float(asset.get("return_120d_pct")) or 0.0
        distance_from_high = self._safe_float(asset.get("distance_from_52w_high_pct"))
        realized_volatility = self._safe_float(asset.get("realized_volatility_20d_pct")) or 0.0
        bar_count = int(asset.get("bar_count") or 0)

        liquidity_score = max(0.0, min(math.log10(max(avg_dollar_volume, 1.0)) - 5.0, 4.0)) * 15.0
        trend_score = (max(return_20d, -20.0) * 0.25) + (max(return_60d, -35.0) * 0.50) + (max(return_120d, -50.0) * 0.35)
        proximity_score = max(0.0, 30.0 + distance_from_high) if distance_from_high is not None else 0.0
        history_score = min(bar_count / 20.0, 10.0)
        volatility_budget = 20.0 + (self.config.risk_tolerance * 4.0)
        volatility_penalty = max(realized_volatility - volatility_budget, 0.0) * 0.35
        continuity_bonus = 8.0 if symbol in preferred_symbols else 0.0
        fractionable_bonus = 2.0 if asset.get("fractionable") else 0.0
        return round(
            liquidity_score + trend_score + proximity_score + history_score + continuity_bonus + fractionable_bonus - volatility_penalty,
            4,
        )

    def _passes_liquidity_prefilter(self, category: str, asset: dict[str, Any]) -> bool:
        bar_count = int(asset.get("bar_count") or 0)
        last_close = self._safe_float(asset.get("last_close"))
        avg_dollar_volume = self._safe_float(asset.get("avg_dollar_volume_20d"))

        if category == "STOCK":
            if last_close is not None and last_close < self.STOCK_MIN_LAST_CLOSE:
                return False
            if bar_count and bar_count < self.STOCK_MIN_BAR_COUNT:
                return False
            if avg_dollar_volume is not None and avg_dollar_volume < self.STOCK_MIN_AVG_DOLLAR_VOLUME_20D:
                return False
            return True

        if bar_count and bar_count < self.CRYPTO_MIN_BAR_COUNT:
            return False
        if avg_dollar_volume is not None and avg_dollar_volume < self.CRYPTO_MIN_AVG_DOLLAR_VOLUME_20D:
            return False
        return True

    def _prefilter_limit(self, category: str, required_count: int, batch_size: int, available_count: int) -> int:
        if available_count <= 0:
            return 0
        multiplier = self.STOCK_PREFILTER_MULTIPLIER if category == "STOCK" else self.CRYPTO_PREFILTER_MULTIPLIER
        return min(available_count, max(batch_size * 3, required_count * multiplier))

    def _enrich_payload_with_market_metrics(
        self,
        provider: str,
        category: str,
        payload: list[dict[str, Any]],
        preferred_symbols: list[str],
    ) -> list[dict[str, Any]]:
        if not payload:
            return []
        normalized_preferred_symbols = {self._normalize_symbol(symbol) for symbol in preferred_symbols}
        metrics_by_symbol = self._fetch_market_metrics_by_symbol(
            provider,
            category,
            [self._normalize_symbol(asset.get("symbol")) for asset in payload],
        )
        enriched_payload: list[dict[str, Any]] = []
        for asset in payload:
            symbol = self._normalize_symbol(asset.get("symbol"))
            enriched_asset = dict(asset)
            enriched_asset.update(metrics_by_symbol.get(symbol, {}))
            enriched_asset["prefilter_score"] = self._candidate_prefilter_score(enriched_asset, normalized_preferred_symbols)
            enriched_payload.append(enriched_asset)
        return enriched_payload

    def _build_prefiltered_payload(
        self,
        category: str,
        payload: list[dict[str, Any]],
        required_count: int,
        batch_size: int,
        preferred_symbols: list[str],
    ) -> list[dict[str, Any]]:
        if not payload:
            return []

        preferred_set = {self._normalize_symbol(symbol) for symbol in preferred_symbols}
        pinned_symbols: set[str] = set()
        pinned_payload: list[dict[str, Any]] = []
        remaining_payload: list[dict[str, Any]] = []

        for asset in payload:
            symbol = self._normalize_symbol(asset.get("symbol"))
            if symbol in preferred_set and symbol not in pinned_symbols:
                pinned_symbols.add(symbol)
                pinned_payload.append(asset)
                continue
            remaining_payload.append(asset)

        remaining_payload.sort(
            key=lambda asset: (
                1 if self._passes_liquidity_prefilter(category, asset) else 0,
                self._safe_float(asset.get("prefilter_score")) or float("-inf"),
                self._safe_float(asset.get("avg_dollar_volume_20d")) or 0.0,
                int(asset.get("bar_count") or 0),
                str(asset.get("symbol", "")),
            ),
            reverse=True,
        )
        limit = self._prefilter_limit(category, required_count, batch_size, len(payload))
        prefiltered_payload = (pinned_payload + remaining_payload)[:limit]
        self.logger.info(
            "Universe prefilter for %s reduced candidates from %s to %s before GPT",
            category,
            len(payload),
            len(prefiltered_payload),
        )
        return prefiltered_payload

    def _dossier_candidate_limit(self, category: str, required_count: int, available_count: int) -> int:
        if available_count <= 0:
            return 0
        if category == "STOCK":
            multiplier = self.STOCK_DOSSIER_MULTIPLIER
            minimum = 18
        else:
            multiplier = self.CRYPTO_DOSSIER_MULTIPLIER
            minimum = 12
        return min(available_count, max(required_count * multiplier, minimum))

    def _build_dossier_candidates(
        self,
        category: str,
        prefiltered_payload: list[dict[str, Any]],
        required_count: int,
    ) -> list[dict[str, Any]]:
        limit = self._dossier_candidate_limit(category, required_count, len(prefiltered_payload))
        selected = prefiltered_payload[:limit]
        self.logger.info(
            "Universe dossier stage for %s will analyze %s candidates in parallel",
            category,
            len(selected),
        )
        return selected

    def _build_dossier_peer_context(
        self,
        category: str,
        candidates: list[dict[str, Any]],
        required_count: int,
        preferred_symbols: list[str],
    ) -> dict[str, Any]:
        return {
            "category": category,
            "required_count": required_count,
            "current_universe": [self._normalize_symbol(symbol) for symbol in preferred_symbols],
            "candidate_count": len(candidates),
            "top_prefilter_symbols": [self._normalize_symbol(asset.get("symbol")) for asset in candidates[:10]],
            "scoring_hint": "prefer quality, liquidity, medium-term momentum, downside control, and differentiated catalysts",
        }

    def _build_dossier_record(self, candidate: dict[str, Any], dossier: dict[str, Any], preferred_symbols: set[str]) -> dict[str, Any]:
        symbol = self._normalize_symbol(candidate.get("symbol"))
        return {
            "symbol": symbol,
            "name": candidate.get("name"),
            "category": dossier.get("category") or candidate.get("category") or "",
            "fractionable": bool(candidate.get("fractionable")),
            "in_current_universe": symbol in preferred_symbols,
            "prefilter_score": candidate.get("prefilter_score"),
            "local_market_metrics": {
                "bar_count": candidate.get("bar_count"),
                "last_close": candidate.get("last_close"),
                "avg_volume_20d": candidate.get("avg_volume_20d"),
                "avg_dollar_volume_20d": candidate.get("avg_dollar_volume_20d"),
                "return_20d_pct": candidate.get("return_20d_pct"),
                "return_60d_pct": candidate.get("return_60d_pct"),
                "return_120d_pct": candidate.get("return_120d_pct"),
                "distance_from_52w_high_pct": candidate.get("distance_from_52w_high_pct"),
                "realized_volatility_20d_pct": candidate.get("realized_volatility_20d_pct"),
            },
            "summary": dossier.get("summary", ""),
            "bull_case": dossier.get("bull_case", []),
            "bear_case": dossier.get("bear_case", []),
            "recent_catalysts": dossier.get("recent_catalysts", []),
            "key_risks": dossier.get("key_risks", []),
            "theme_tags": dossier.get("theme_tags", []),
            "news_sentiment": dossier.get("news_sentiment", "neutral"),
            "quality_score": dossier.get("quality_score"),
            "liquidity_score": dossier.get("liquidity_score"),
            "momentum_score": dossier.get("momentum_score"),
            "downside_control_score": dossier.get("downside_control_score"),
            "fit_score": dossier.get("fit_score"),
            "conviction_score": dossier.get("conviction_score"),
            "reasoning": dossier.get("reasoning", ""),
        }

    def _generate_parallel_symbol_dossiers(
        self,
        provider: str,
        category: str,
        candidates: list[dict[str, Any]],
        required_count: int,
        preferred_symbols: list[str],
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []

        preferred_set = {self._normalize_symbol(symbol) for symbol in preferred_symbols}
        peer_context = self._build_dossier_peer_context(category, candidates, required_count, preferred_symbols)
        ordered_results: dict[int, dict[str, Any]] = {}
        max_workers = min(self.MAX_DOSSIER_WORKERS, len(candidates))

        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"{provider}-{category.lower()}-dossier") as executor:
            future_by_index = {
                executor.submit(
                    self.gpt_client.request_universe_symbol_dossier,
                    category,
                    candidate,
                    peer_context,
                    provider,
                ): index
                for index, candidate in enumerate(candidates)
            }
            for future in as_completed(future_by_index):
                index = future_by_index[future]
                candidate = candidates[index]
                symbol = self._normalize_symbol(candidate.get("symbol"))
                try:
                    dossier = future.result()
                except Exception:
                    self.logger.exception("Universe dossier generation failed for %s/%s/%s", provider, category, symbol)
                    continue
                ordered_results[index] = self._build_dossier_record(candidate, dossier, preferred_set)

        return [ordered_results[index] for index in sorted(ordered_results)]

    def _sanitize_stock_selection(self, symbols: list[str], valid_candidates: set[str]) -> list[str]:
        selected: list[str] = []
        for symbol in symbols:
            normalized = self._normalize_symbol(symbol)
            if normalized in valid_candidates and normalized not in selected:
                selected.append(normalized)
        return selected

    def _sanitize_crypto_selection(
        self,
        symbols: list[str],
        valid_candidates: set[str],
        quote_currency: str,
    ) -> list[str]:
        selected: list[str] = []
        quote = quote_currency.upper()
        for symbol in symbols:
            normalized = self._normalize_symbol(symbol)
            candidates_to_try = [normalized]
            if "/" not in normalized:
                candidates_to_try.insert(0, f"{normalized}/{quote}")
            for candidate in candidates_to_try:
                if candidate in valid_candidates and candidate not in selected:
                    selected.append(candidate)
                    break
        return selected

    def _sanitize_selection(
        self,
        provider: str,
        category: str,
        symbols: list[str],
        valid_candidates: set[str],
    ) -> list[str]:
        if category == "STOCK":
            return self._sanitize_stock_selection(symbols, valid_candidates)
        quote = self.config.provider_account_currency(provider)
        return self._sanitize_crypto_selection(symbols, valid_candidates, quote)

    def _top_up_selection(
        self,
        provider: str,
        category: str,
        selected_symbols: list[str],
        ordered_payload: list[dict[str, Any]],
        required_count: int,
    ) -> list[str]:
        ordered_candidates = [self._normalize_symbol(asset.get("symbol")) for asset in ordered_payload]
        valid_candidates = {symbol for symbol in ordered_candidates if symbol}
        completed_selection = self._sanitize_selection(provider, category, selected_symbols, valid_candidates)
        for symbol in ordered_candidates:
            if symbol and symbol not in completed_selection:
                completed_selection.append(symbol)
            if len(completed_selection) >= required_count:
                break
        return completed_selection[:required_count]

    # -- Alpaca path ------------------------------------------------------

    def _get_alpaca_stock_candidate_payload(self) -> list[dict[str, Any]]:
        broker = self.alpaca_client
        if broker is None:
            return []
        assets = broker.list_assets("US_EQUITY")
        payload = [
            self._asset_snapshot(asset)
            for asset in assets
            if getattr(asset, "tradable", False)
            and getattr(asset, "status", "").lower() == "active"
            and not self._looks_like_etf(asset)
            and not self._looks_like_non_common_stock(asset)
            and not self._looks_like_shell_company(asset)
        ]
        payload = self._dedupe_payload_by_symbol(payload)
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload

    def _get_alpaca_crypto_candidate_payload(self) -> list[dict[str, Any]]:
        broker = self.alpaca_client
        if broker is None:
            return []
        assets = broker.list_assets("CRYPTO")
        quote_suffix = f"/{self.config.account_currency}"
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

    def _select_category_universe(
        self,
        provider: str,
        category: str,
        payload: list[dict[str, Any]],
        required_count: int,
        batch_size: int,
        preferred_symbols: list[str] | None = None,
    ) -> list[str]:
        if not payload or required_count <= 0:
            return []

        preferred_symbols = preferred_symbols or []
        prefiltered_payload = self._build_prefiltered_payload(
            category=category,
            payload=payload,
            required_count=required_count,
            batch_size=batch_size,
            preferred_symbols=preferred_symbols,
        )
        if not prefiltered_payload:
            return []

        dossier_candidates = self._build_dossier_candidates(category, prefiltered_payload, required_count)
        dossiers = self._generate_parallel_symbol_dossiers(
            provider=provider,
            category=category,
            candidates=dossier_candidates,
            required_count=required_count,
            preferred_symbols=preferred_symbols,
        )
        if not dossiers:
            return self._top_up_selection(provider, category, [], prefiltered_payload, required_count)

        dossier_symbols = [self._normalize_symbol(dossier.get("symbol")) for dossier in dossiers]
        successful_dossier_payload = self._filter_payload_by_symbols(dossier_candidates, dossier_symbols)

        try:
            final_result = self.gpt_client.request_universe_final_selection_from_dossiers(
                category=category,
                dossiers=dossiers,
                required_count=min(required_count, len(dossiers)),
                current_universe=preferred_symbols,
                provider=provider,
            )
            selected_symbols = self._sanitize_selection(
                provider,
                category,
                final_result.get("symbols", []),
                {self._normalize_symbol(dossier.get("symbol")) for dossier in dossiers},
            )
        except Exception:
            self.logger.exception("GPT dossier-based final universe selection failed for %s; using deterministic fallback", category)
            selected_symbols = []

        completed_selection = self._top_up_selection(provider, category, selected_symbols, successful_dossier_payload, required_count)
        if len(completed_selection) >= required_count:
            return completed_selection
        return self._top_up_selection(provider, category, completed_selection, prefiltered_payload, required_count)

    def _select_alpaca_universe(self, current_universe: ProviderUniverse) -> dict[str, list[str]]:
        broker = self.alpaca_client
        if broker is None:
            return {}
        try:
            base_stock_payload = self._get_alpaca_stock_candidate_payload()
            base_crypto_payload = self._get_alpaca_crypto_candidate_payload()
            full_stock_payload = self._enrich_payload_with_market_metrics(
                PROVIDER_ALPACA,
                "STOCK",
                base_stock_payload,
                universe_for_provider(current_universe, PROVIDER_ALPACA).get("STOCK", []),
            )
            full_crypto_payload = self._enrich_payload_with_market_metrics(
                PROVIDER_ALPACA,
                "CRYPTO",
                base_crypto_payload,
                universe_for_provider(current_universe, PROVIDER_ALPACA).get("CRYPTO", []),
            )
            self._write_candidate_lists(full_stock_payload, full_crypto_payload)

            stocks = self._select_category_universe(
                PROVIDER_ALPACA,
                category="STOCK",
                payload=full_stock_payload,
                required_count=self.config.weekly_universe_stocks,
                batch_size=self.STOCK_BATCH_SIZE,
                preferred_symbols=universe_for_provider(current_universe, PROVIDER_ALPACA).get("STOCK", []),
            )
            crypto = self._select_category_universe(
                PROVIDER_ALPACA,
                category="CRYPTO",
                payload=full_crypto_payload,
                required_count=self.config.weekly_universe_crypto,
                batch_size=self.CRYPTO_BATCH_SIZE,
                preferred_symbols=universe_for_provider(current_universe, PROVIDER_ALPACA).get("CRYPTO", []),
            )
        except Exception:
            self.logger.exception("Trading universe selection failed for Alpaca; keeping the previous valid universe")
            return {
                "STOCK": list(universe_for_provider(current_universe, PROVIDER_ALPACA).get("STOCK", [])),
                "CRYPTO": list(universe_for_provider(current_universe, PROVIDER_ALPACA).get("CRYPTO", [])),
            }

        return {"STOCK": stocks, "CRYPTO": crypto}

    def _write_candidate_lists(
        self,
        stock_payload: list[dict[str, Any]],
        crypto_payload: list[dict[str, Any]],
    ) -> None:
        write_json_file(
            self.config.universe_log_file,
            {"STOCK": stock_payload, "CRYPTO": crypto_payload},
        )

    # -- eToro path -------------------------------------------------------

    def _get_etoro_stock_candidate_payload(self) -> list[dict[str, Any]]:
        broker = self.broker(PROVIDER_ETORO)
        if broker is None:
            return []
        assets = broker.list_assets("STOCK")
        payload = [
            self._asset_snapshot(asset)
            for asset in assets
            if getattr(asset, "tradable", False)
            and not self._looks_like_etf(asset)
            and not self._looks_like_non_common_stock(asset)
            and not self._looks_like_shell_company(asset)
        ]
        payload = self._dedupe_payload_by_symbol(payload)
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload

    def _get_etoro_crypto_candidate_payload(self) -> list[dict[str, Any]]:
        broker = self.broker(PROVIDER_ETORO)
        if broker is None:
            return []
        assets = broker.list_assets("CRYPTO")
        payload = [
            self._asset_snapshot(asset)
            for asset in assets
            if getattr(asset, "tradable", False)
        ]
        payload = self._dedupe_payload_by_symbol(payload)
        payload.sort(key=lambda asset: str(asset["symbol"]))
        return payload

    def _select_etoro_universe(self, current_universe: ProviderUniverse) -> dict[str, list[str]]:
        broker = self.broker(PROVIDER_ETORO)
        if broker is None:
            return {}
        preferred = universe_for_provider(current_universe, PROVIDER_ETORO)
        try:
            base_stock_payload = self._get_etoro_stock_candidate_payload()
            base_crypto_payload = self._get_etoro_crypto_candidate_payload()
            full_stock_payload = self._enrich_payload_with_market_metrics(
                PROVIDER_ETORO, "STOCK", base_stock_payload, preferred.get("STOCK", [])
            )
            full_crypto_payload = self._enrich_payload_with_market_metrics(
                PROVIDER_ETORO, "CRYPTO", base_crypto_payload, preferred.get("CRYPTO", [])
            )
            self._write_candidate_lists(full_stock_payload, full_crypto_payload)

            stocks = self._select_category_universe(
                PROVIDER_ETORO, "STOCK", full_stock_payload,
                self.config.weekly_universe_stocks, self.STOCK_BATCH_SIZE, preferred.get("STOCK", []),
            )
            crypto = self._select_category_universe(
                PROVIDER_ETORO, "CRYPTO", full_crypto_payload,
                self.config.weekly_universe_crypto, self.CRYPTO_BATCH_SIZE, preferred.get("CRYPTO", []),
            )
        except Exception:
            self.logger.exception("Trading universe selection failed for eToro; keeping the previous valid universe")
            return {
                "STOCK": list(preferred.get("STOCK", [])),
                "CRYPTO": list(preferred.get("CRYPTO", [])),
            }
        return {"STOCK": stocks, "CRYPTO": crypto}

    # -- public entry points ---------------------------------------------

    def select_trading_universe(self) -> ProviderUniverse:
        current_universe = self.get_current_universe()
        result: ProviderUniverse = {provider: {} for provider in ALL_PROVIDERS}

        if self.alpaca_client is not None:
            result[PROVIDER_ALPACA] = self._select_alpaca_universe(current_universe)
        else:
            result[PROVIDER_ALPACA] = {"STOCK": [], "CRYPTO": []}

        if self.broker(PROVIDER_ETORO) is not None:
            result[PROVIDER_ETORO] = self._select_etoro_universe(current_universe)
        else:
            result[PROVIDER_ETORO] = {"STOCK": [], "CRYPTO": []}

        write_universe_file(result)
        self.logger.info("Selected trading universe: %s", result)
        return result

    def select_weekly_universe(self) -> ProviderUniverse:
        return self.select_trading_universe()

    def get_current_universe(self) -> ProviderUniverse:
        return read_universe_file()
