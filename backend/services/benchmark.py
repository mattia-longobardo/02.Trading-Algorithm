"""Confronto tra l'andamento del conto e un benchmark di mercato (S&P 500).

Il portafoglio usa gli snapshot equity giornalieri (``account_equity_snapshots``,
già aggregati multi-provider e convertiti nella valuta di visualizzazione);
il benchmark usa le candele daily dell'indice su eToro (default ``SPX500``).

Entrambe le serie vengono ancorate alla stessa data di partenza (la più
recente tra i primi punti disponibili delle due serie dentro la finestra) e
normalizzate in rendimento percentuale rispetto a quel punto, così il grafico
confronta variazioni relative e resta neutro rispetto a valuta e capitale.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from core.utils import AppConfig, isoformat_utc, parse_datetime, utc_now
from services.equity_snapshots import equity_curve_for_api

DEFAULT_BENCHMARK_SYMBOL = "SPX500"

# Le candele daily cambiano al più una volta al giorno: una piccola cache TTL
# evita di consumare rate-limit eToro ad ogni refresh (1/min) della pagina.
_CANDLE_CACHE_TTL_SECONDS = 15 * 60
_MAX_DAILY_CANDLES = 1000


def _day_key(value: Any) -> str | None:
    """Floor di un timestamp al bucket giornaliero, stessa forma dei bucket equity."""

    parsed = parse_datetime(value) if not isinstance(value, datetime) else value
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%dT00:00:00+00:00")


def _normalize_pct(series: list[tuple[str, float]]) -> dict[str, float]:
    """Serie assoluta → ``{bucket: rendimento % dal primo punto}``."""

    if not series:
        return {}
    base = series[0][1]
    if base == 0:
        return {}
    return {t: round((value / base - 1.0) * 100.0, 2) for t, value in series}


def _clip_to_start(
    series: list[tuple[str, float]], start_key: str
) -> list[tuple[str, float]]:
    """Taglia la serie a ``start_key`` ancorando l'ultimo valore precedente.

    Se la partenza comune cade quando una serie non quota (l'indice nel
    weekend), il capitale "investito" quel giorno compra all'ultimo prezzo
    disponibile: quel valore diventa la base, ri-datato a ``start_key``,
    così la linea parte da 0 senza buchi iniziali.
    """

    after = [item for item in series if item[0] >= start_key]
    if after and after[0][0] == start_key:
        return after
    before = [item for item in series if item[0] < start_key]
    if before:
        return [(start_key, before[-1][1])] + after
    return after


class BenchmarkService:
    """Costruisce il payload della pagina "Benchmark" del frontend."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        # symbol -> (scadenza monotonic, count scaricato, righe candele)
        self._candle_cache: dict[str, tuple[float, int, list[dict[str, Any]]]] = {}

    # ----- serie portafoglio -------------------------------------------------

    def _portfolio_series(
        self, from_dt: datetime | None, to_dt: datetime | None
    ) -> list[tuple[str, float]]:
        curve = equity_curve_for_api(
            self.config.db_app,
            from_dt=from_dt,
            to_dt=to_dt,
            granularity="daily",
            target_currency=self.config.currency,
        )
        return [(str(p["t"]), float(p["equity"])) for p in curve["points"]]

    # ----- serie benchmark ---------------------------------------------------

    def _fetch_candles(self, broker: Any, symbol: str, count: int) -> list[dict[str, Any]]:
        cached = self._candle_cache.get(symbol)
        if cached is not None:
            expires_at, cached_count, rows = cached
            if time.monotonic() < expires_at and cached_count >= count:
                return rows
        instrument_id = broker.instrument_id_for_symbol(symbol)
        if instrument_id is None:
            raise ValueError(f"symbol {symbol!r} not resolvable to an eToro instrument")
        rows = broker.get_candles_by_instrument(instrument_id, symbol, count=count, interval="OneDay")
        self._candle_cache[symbol] = (time.monotonic() + _CANDLE_CACHE_TTL_SECONDS, count, rows)
        return rows

    def _benchmark_series(
        self,
        broker: Any,
        symbol: str,
        from_dt: datetime | None,
        to_dt: datetime | None,
    ) -> list[tuple[str, float]]:
        window_start = from_dt
        if window_start is None:
            count = _MAX_DAILY_CANDLES
        else:
            days = (utc_now() - window_start).days + 5
            count = max(1, min(_MAX_DAILY_CANDLES, days))
        rows = self._fetch_candles(broker, symbol, count)

        # Niente filtro sull'inizio finestra: la candela precedente serve da
        # àncora quando la partenza cade in un giorno di mercato chiuso
        # (vedi ``_clip_to_start``); il taglio avviene in ``comparison``.
        to_iso = isoformat_utc(to_dt) if to_dt is not None else None
        series: list[tuple[str, float]] = []
        for row in rows:
            key = _day_key(row.get("timestamp"))
            if key is None:
                continue
            if to_iso is not None and key > to_iso:
                continue
            series.append((key, float(row["close"])))
        series.sort(key=lambda item: item[0])
        return series

    # ----- payload API -------------------------------------------------------

    def comparison(
        self,
        broker: Any,
        *,
        from_dt: datetime | None,
        to_dt: datetime | None,
        symbol: str = DEFAULT_BENCHMARK_SYMBOL,
    ) -> dict[str, Any]:
        symbol = str(symbol or DEFAULT_BENCHMARK_SYMBOL).upper().strip()
        portfolio = self._portfolio_series(from_dt, to_dt)

        benchmark: list[tuple[str, float]] = []
        benchmark_error: str | None = None
        if broker is None:
            benchmark_error = "no_broker_configured"
        else:
            try:
                benchmark = self._benchmark_series(broker, symbol, from_dt, to_dt)
            except Exception as exc:
                self.logger.warning("benchmark: fetch %s candles failed: %s", symbol, exc)
                benchmark_error = str(exc)

        # Ancoraggio alla partenza comune: confrontare rendimenti da date
        # diverse (es. indice da 90 giorni, conto da 30) sarebbe fuorviante.
        # ``portfolio`` è già filtrato sulla finestra; ``benchmark`` arriva
        # con lo storico extra che fa da àncora pre-partenza.
        window_start = _day_key(from_dt) if from_dt is not None else None
        if portfolio and benchmark:
            common_start = max(portfolio[0][0], benchmark[0][0])
            if window_start is not None and window_start > common_start:
                common_start = window_start
            portfolio = _clip_to_start(portfolio, common_start)
            benchmark = _clip_to_start(benchmark, common_start)
        elif benchmark and window_start is not None:
            benchmark = _clip_to_start(benchmark, window_start)

        portfolio_pct = _normalize_pct(portfolio)
        benchmark_pct = _normalize_pct(benchmark)

        points: list[dict[str, Any]] = []
        last_p: float | None = None
        last_b: float | None = None
        for bucket in sorted(set(portfolio_pct) | set(benchmark_pct)):
            # Forward-fill: l'indice non quota nel weekend, gli snapshot
            # possono mancare in un giorno — la linea resta continua.
            last_p = portfolio_pct.get(bucket, last_p)
            last_b = benchmark_pct.get(bucket, last_b)
            points.append({"t": bucket, "portfolio_pct": last_p, "benchmark_pct": last_b})

        summary: dict[str, Any] | None = None
        if portfolio:
            final_portfolio_pct = portfolio_pct[portfolio[-1][0]]
            final_benchmark_pct = benchmark_pct[benchmark[-1][0]] if benchmark else None
            summary = {
                "portfolio_pct": final_portfolio_pct,
                "benchmark_pct": final_benchmark_pct,
                "alpha_pct": (
                    round(final_portfolio_pct - final_benchmark_pct, 2)
                    if final_benchmark_pct is not None
                    else None
                ),
                "portfolio_base": portfolio[0][1],
                "portfolio_latest": portfolio[-1][1],
                "currency": self.config.currency,
            }

        return {
            "points": points,
            "summary": summary,
            "benchmark": {
                "symbol": symbol,
                "points_count": len(benchmark),
                "error": benchmark_error,
            },
        }
