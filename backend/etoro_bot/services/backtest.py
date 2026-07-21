"""Track record dei trade reali del bot (§11.1).

Non è un backtest storico di una strategia meccanica: è l'analisi dei trade
realmente eseguiti (demo o reale), letti SOLO dal registry bot (§7).
Rendimenti calcolati con Time-Weighted Return (TWR, standard GIPS): ogni
variazione di bot_capital_usd chiude un sub-periodo.

Le metriche sono funzioni pure (definizioni standard, quantstats-like,
252 giorni/anno) e ritornano None quando indefinite. I prezzi del benchmark
arrivano da un `price_fetcher(symbol, start_date) -> dict[date, float]`
iniettato: nessuna rete in questo modulo.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import numpy as np

from etoro_bot.config import load_settings
from etoro_bot.db.repo import Repository

TRADING_DAYS_PER_YEAR = 252
MIN_TRADES_FOR_STATS = 30    # §11.2: sotto, campione insufficiente
MIN_DAYS_FOR_ANNUALIZATION = 60  # §11.2: sotto, niente metriche annualizzate

PriceFetcher = Callable[[str, date], dict[date, float]]


# --- serie di rendimenti (TWR) ---------------------------------------------


def daily_returns(
    equity: list[tuple[date, float]],
    capital_changes: dict[date, float] | None = None,
) -> list[float]:
    """Rendimenti giornalieri TWR dalla serie equity (data, equity_usd).

    `capital_changes[d]` è il flusso di capitale (delta di bot_capital_usd)
    avvenuto il giorno d: il rendimento di quel giorno usa l'equity depurata
    del flusso, così depositi/prelievi non contano come performance.
    """
    flows = capital_changes or {}
    points = sorted(equity)
    returns: list[float] = []
    for (_, prev_equity), (day, curr_equity) in zip(points, points[1:]):
        flow = flows.get(day, 0.0)
        returns.append((curr_equity - flow) / prev_equity - 1.0 if prev_equity > 0 else 0.0)
    return returns


# --- metriche pure su rendimenti --------------------------------------------


def total_return(returns: list[float]) -> float | None:
    if not returns:
        return None
    return float(np.prod(np.asarray(returns) + 1.0) - 1.0)


def cagr(returns: list[float], periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float | None:
    total = total_return(returns)
    if total is None or total <= -1.0:
        return None
    years = len(returns) / periods_per_year
    if years <= 0:
        return None
    return float((1.0 + total) ** (1.0 / years) - 1.0)


def annualized_volatility(
    returns: list[float], periods_per_year: int = TRADING_DAYS_PER_YEAR
) -> float | None:
    if len(returns) < 2:
        return None
    return float(np.std(returns, ddof=1) * np.sqrt(periods_per_year))


def sharpe(returns: list[float], risk_free_rate: float = 0.0) -> float | None:
    """(CAGR − risk_free) / volatilità annualizzata (risk_free annuo, es. 0.05)."""
    growth = cagr(returns)
    vol = annualized_volatility(returns)
    if growth is None or vol is None or vol == 0:
        return None
    return float((growth - risk_free_rate) / vol)


def sortino(returns: list[float], risk_free_rate: float = 0.0) -> float | None:
    """Come Sharpe ma con downside deviation: sqrt(mean(min(r,0)²)) annualizzata."""
    growth = cagr(returns)
    if growth is None:
        return None
    arr = np.asarray(returns)
    downside = float(np.sqrt(np.mean(np.minimum(arr, 0.0) ** 2)) * np.sqrt(TRADING_DAYS_PER_YEAR))
    if downside == 0:
        return None
    return float((growth - risk_free_rate) / downside)


def max_drawdown(returns: list[float]) -> float | None:
    """Massima perdita peak-to-trough sulla curva cumulata (valore ≤ 0)."""
    if not returns:
        return None
    curve = np.cumprod(np.asarray(returns) + 1.0)
    peaks = np.maximum.accumulate(curve)
    return float(np.min(curve / peaks - 1.0))


def calmar(returns: list[float]) -> float | None:
    growth = cagr(returns)
    mdd = max_drawdown(returns)
    if growth is None or mdd is None or mdd == 0:
        return None
    return float(growth / abs(mdd))


def alpha_beta(
    returns: list[float], benchmark_returns: list[float]
) -> tuple[float, float] | None:
    """Regressione OLS dei rendimenti giornalieri bot vs benchmark → (alpha, beta)."""
    if len(returns) != len(benchmark_returns) or len(returns) < 2:
        return None
    y = np.asarray(returns)
    x = np.asarray(benchmark_returns)
    var_x = float(np.var(x))
    if var_x == 0:
        return None
    beta = float(np.cov(x, y, ddof=0)[0, 1] / var_x)
    alpha = float(np.mean(y) - beta * np.mean(x))
    return alpha, beta


def information_ratio(returns: list[float], benchmark_returns: list[float]) -> float | None:
    """media(excess return vs benchmark) / tracking error, annualizzato."""
    if len(returns) != len(benchmark_returns) or len(returns) < 2:
        return None
    excess = np.asarray(returns) - np.asarray(benchmark_returns)
    tracking_error = float(np.std(excess, ddof=1))
    if tracking_error == 0:
        return None
    return float(np.mean(excess) / tracking_error * np.sqrt(TRADING_DAYS_PER_YEAR))


def recovery_factor(returns: list[float]) -> float | None:
    total = total_return(returns)
    mdd = max_drawdown(returns)
    if total is None or mdd is None or mdd == 0:
        return None
    return float(total / abs(mdd))


def exposure_pct(exposures: list[float]) -> float | None:
    """% di giorni con almeno una posizione aperta (exposure > 0)."""
    if not exposures:
        return None
    return float(sum(1 for e in exposures if e > 0) / len(exposures) * 100.0)


# --- metriche pure sui trade chiusi -----------------------------------------


def win_rate(trade_pnls: list[float]) -> float | None:
    if not trade_pnls:
        return None
    return float(sum(1 for pnl in trade_pnls if pnl > 0) / len(trade_pnls))


def profit_factor(trade_pnls: list[float]) -> float | None:
    profits = sum(pnl for pnl in trade_pnls if pnl > 0)
    losses = sum(pnl for pnl in trade_pnls if pnl < 0)
    if losses == 0:
        return None
    return float(profits / abs(losses))


def expectancy(trade_pnls: list[float]) -> float | None:
    if not trade_pnls:
        return None
    return float(np.mean(trade_pnls))


# --- servizio ---------------------------------------------------------------


class BacktestService:
    """Assembla dal repo la serie equity, i trade chiusi e il benchmark SPY."""

    def __init__(
        self,
        repo: Repository,
        price_fetcher: PriceFetcher,
        settings: dict[str, Any] | None = None,
    ):
        self._repo = repo
        self._price_fetcher = price_fetcher
        self._settings = settings if settings is not None else load_settings()

    # --- input dal repo ------------------------------------------------------
    def _equity_points(
        self, date_from: date | None = None, date_to: date | None = None
    ) -> list[tuple[date, float]]:
        return [
            (snap.date, snap.equity_usd)
            for snap in self._repo.equity_series()
            if (date_from is None or snap.date >= date_from)
            and (date_to is None or snap.date <= date_to)
        ]

    def _capital_changes(self) -> dict[date, float]:
        """Flussi di capitale dal log di audit di bot_capital_usd (delta per giorno)."""
        flows: dict[date, float] = {}
        for entry in self._repo.settings_audit(limit=1000):
            if entry.key != "bot_capital_usd":
                continue
            old = (entry.old_value or {}).get("value")
            new = (entry.new_value or {}).get("value")
            if old is None or new is None:
                continue  # primo set: capitale iniziale, non un flusso
            day = entry.changed_at.date()
            flows[day] = flows.get(day, 0.0) + float(new) - float(old)
        return {d: f for d, f in flows.items() if f != 0.0}

    def _benchmark_symbol(self) -> str:
        return str(self._settings.get("benchmark_symbol", "SPY"))

    def _risk_free_rate(self) -> float:
        return float(self._settings.get("risk_free_rate_pct", 5.0)) / 100.0

    @staticmethod
    def _price_on(prices: dict[date, float], day: date, lookback_days: int = 7) -> float | None:
        """Ultimo prezzo disponibile ≤ day (weekend/festivi senza candela)."""
        for offset in range(lookback_days + 1):
            price = prices.get(day - timedelta(days=offset))
            if price is not None:
                return price
        return None

    def _benchmark_returns(self, dates: list[date]) -> list[float] | None:
        """Rendimenti del benchmark sugli stessi intervalli della serie equity."""
        if len(dates) < 2:
            return None
        try:
            prices = self._price_fetcher(self._benchmark_symbol(), dates[0])
        except Exception:
            return None
        if not prices:
            return None
        returns: list[float] = []
        for prev_day, day in zip(dates, dates[1:]):
            prev_price = self._price_on(prices, prev_day)
            price = self._price_on(prices, day)
            if prev_price is None or price is None or prev_price == 0:
                return None
            returns.append(price / prev_price - 1.0)
        return returns

    # --- API ------------------------------------------------------------------
    def summary(
        self, date_from: date | None = None, date_to: date | None = None
    ) -> dict[str, Any]:
        points = self._equity_points(date_from, date_to)
        returns = daily_returns(points, self._capital_changes())
        pnls = [
            p.realized_pnl_usd
            for p in self._repo.closed_positions()
            if p.realized_pnl_usd is not None
            and p.closed_at is not None
            and (date_from is None or p.closed_at.date() >= date_from)
            and (date_to is None or p.closed_at.date() <= date_to)
        ]
        exposures = [
            snap.exposure_usd
            for snap in self._repo.equity_series()
            if (date_from is None or snap.date >= date_from)
            and (date_to is None or snap.date <= date_to)
        ]
        bench = self._benchmark_returns([d for d, _ in points])
        risk_free = self._risk_free_rate()

        n_days = len(points)
        n_closed = len(pnls)
        annualization_available = n_days >= MIN_DAYS_FOR_ANNUALIZATION
        ab = alpha_beta(returns, bench) if bench is not None else None

        metrics: dict[str, Any] = {
            "total_return": total_return(returns),
            "cagr": cagr(returns),
            "annualized_volatility": annualized_volatility(returns),
            "sharpe": sharpe(returns, risk_free),
            "sortino": sortino(returns, risk_free),
            "max_drawdown": max_drawdown(returns),
            "calmar": calmar(returns),
            "alpha": ab[0] if ab else None,
            "beta": ab[1] if ab else None,
            "information_ratio": information_ratio(returns, bench) if bench else None,
            "win_rate": win_rate(pnls),
            "profit_factor": profit_factor(pnls),
            "recovery_factor": recovery_factor(returns),
            "expectancy": expectancy(pnls),
            "exposure_pct": exposure_pct(exposures),
            "max_win_usd": max((p for p in pnls if p > 0), default=None),
            "max_loss_usd": min((p for p in pnls if p < 0), default=None),
            "std_win_usd": (
                float(np.std([p for p in pnls if p > 0], ddof=1))
                if len([p for p in pnls if p > 0]) > 1 else None
            ),
            "std_loss_usd": (
                float(np.std([p for p in pnls if p < 0], ddof=1))
                if len([p for p in pnls if p < 0]) > 1 else None
            ),
        }
        if not annualization_available:
            # §11.2: nessuna estrapolazione annualizzata sotto i 60 giorni
            for key in ("cagr", "sharpe", "sortino", "calmar", "annualized_volatility"):
                metrics[key] = None

        return {
            **metrics,
            "n_closed_trades": n_closed,
            "n_days": n_days,
            "insufficient_sample": n_closed < MIN_TRADES_FOR_STATS,
            "annualization_available": annualization_available,
            "risk_free_rate_pct": risk_free * 100.0,
        }

    def equity_curve(
        self,
        benchmark: str = "spy",
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        """Curva equity bot + benchmark lump-sum e cash-flow matched (§11.1)."""
        points = self._equity_points(date_from, date_to)
        if not points:
            return []
        symbol = benchmark.upper() if benchmark else self._benchmark_symbol()
        try:
            prices = self._price_fetcher(symbol, points[0][0])
        except Exception:
            prices = {}

        capital = points[0][1]
        first_price = self._price_on(prices, points[0][0]) if prices else None
        lump_sum_shares = capital / first_price if first_price else None

        # Ogni apertura bot replicata come acquisto benchmark di pari importo.
        openings: list[tuple[date, float]] = []
        for pos in [*self._repo.open_positions(), *self._repo.closed_positions()]:
            open_day = pos.opened_at.date()
            open_price = self._price_on(prices, open_day) if prices else None
            if open_price:
                openings.append((open_day, pos.amount_usd / open_price))
        openings.sort()

        curve: list[dict[str, Any]] = []
        for day, equity_usd in points:
            price = self._price_on(prices, day) if prices else None
            lump = lump_sum_shares * price if lump_sum_shares and price else None
            matched = (
                sum(shares for open_day, shares in openings if open_day <= day) * price
                if price
                else None
            )
            curve.append(
                {
                    "date": day.isoformat(),
                    "equity_usd": equity_usd,
                    "spy_lump_sum_usd": lump,
                    "spy_cash_flow_matched_usd": matched,
                }
            )
        return curve

    def monthly_returns(self) -> list[dict[str, Any]]:
        """Rendimenti mensili (%) dalla serie TWR: righe {year, months[12]}."""
        points = self._equity_points()
        returns = daily_returns(points, self._capital_changes())
        by_month: dict[tuple[int, int], float] = {}
        for (day, _), ret in zip(points[1:], returns):
            key = (day.year, day.month)
            by_month[key] = by_month.get(key, 1.0) * (1.0 + ret)
        rows: dict[int, list[float | None]] = {}
        for (year, month), growth in sorted(by_month.items()):
            rows.setdefault(year, [None] * 12)[month - 1] = round((growth - 1.0) * 100.0, 4)
        return [{"year": year, "months": months} for year, months in sorted(rows.items())]

    def trades(self) -> list[dict[str, Any]]:
        """Trade chiusi dal registry bot (§7), per la pagina Backtest."""
        return [
            {
                "etoro_position_id": p.etoro_position_id,
                "symbol": p.symbol,
                "amount_usd": p.amount_usd,
                "entry_price": p.entry_price,
                "close_price": p.close_price,
                "opened_at": p.opened_at.isoformat(),
                "closed_at": p.closed_at.isoformat() if p.closed_at else None,
                "realized_pnl_usd": p.realized_pnl_usd,
                "close_reason": p.close_reason,
                "sector": p.sector,
            }
            for p in self._repo.closed_positions()
        ]
