"""Test delle metriche di backtest contro valori noti calcolati a mano."""

from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest

from etoro_bot.services.backtest import (
    BacktestService,
    alpha_beta,
    annualized_volatility,
    cagr,
    calmar,
    daily_returns,
    expectancy,
    exposure_pct,
    information_ratio,
    max_drawdown,
    profit_factor,
    recovery_factor,
    sharpe,
    sortino,
    total_return,
    win_rate,
)


class FakeRepo:
    """Repo finto: solo i metodi letti da BacktestService, senza DB."""

    def __init__(self, snaps=(), closed=(), open_=(), audit=(), settings=None):
        self._snaps = list(snaps)
        self._closed = list(closed)
        self._open = list(open_)
        self._audit = list(audit)
        self._settings = settings or {}

    def equity_series(self):
        return list(self._snaps)

    def closed_positions(self):
        return list(self._closed)

    def open_positions(self):
        return list(self._open)

    def settings_audit(self, limit=100):
        return list(self._audit)

    def get_setting(self, key):
        return self._settings.get(key)


def snap(day, equity, cash=None, exposure=0.0):
    return SimpleNamespace(
        date=day, equity_usd=equity, cash_usd=cash if cash is not None else equity,
        exposure_usd=exposure,
    )


def closed_trade(pnl, day=date(2026, 1, 5)):
    return SimpleNamespace(
        etoro_position_id=1, symbol="AAPL", amount_usd=100.0, entry_price=10.0,
        close_price=11.0, opened_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        closed_at=datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc),
        realized_pnl_usd=pnl, close_reason="bot_close", sector="tech",
    )


# --- TWR ---------------------------------------------------------------------


def test_daily_returns_twr_with_capital_change_mid_series():
    # d1→d2: 110/100 − 1 = 0.10
    # d3: equity 165 ma con deposito di 50 quel giorno → (165−50)/110 − 1 = 115/110 − 1 = 0.0454545...
    equity = [(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 110.0), (date(2026, 1, 3), 165.0)]
    flows = {date(2026, 1, 3): 50.0}
    returns = daily_returns(equity, flows)
    assert returns == pytest.approx([0.10, 115 / 110 - 1])
    # Senza depurare il flusso il secondo giorno varrebbe 0.5: il TWR lo neutralizza.
    assert daily_returns(equity)[1] == pytest.approx(0.5)


def test_daily_returns_zero_previous_equity_is_flat():
    equity = [(date(2026, 1, 1), 100.0), (date(2026, 1, 2), 0.0), (date(2026, 1, 3), 50.0)]
    assert daily_returns(equity) == pytest.approx([-1.0, 0.0])


# --- metriche su rendimenti --------------------------------------------------


def test_total_return_known_and_empty():
    # 1.10 × 0.90 − 1 = 0.99 − 1 = −0.01
    assert total_return([0.10, -0.10]) == pytest.approx(-0.01)
    assert total_return([]) is None


def test_max_drawdown_known_curve():
    # Curva 100 → 120 → 90 → 100: picco 120, minimo dopo il picco 90
    # MDD = 90/120 − 1 = −0.25
    returns = [0.20, -0.25, 1 / 9]
    assert max_drawdown(returns) == pytest.approx(-0.25)
    assert max_drawdown([]) is None


def test_sharpe_sortino_volatility_known_series():
    # r = [0.01, 0.02, −0.01, 0.03]
    # total = 1.01·1.02·0.99·1.03 − 1 = 0.05049494
    # cagr = 1.05049494^(252/4) − 1 = 21.275106...
    # vol  = std(r, ddof=1)·√252: std = 0.01707825, vol = 0.27110883...
    # sharpe (rf=0) = 21.275106 / 0.271109 = 78.474412...
    # downside = √(mean([0,0,(−0.01)²,0]))·√252 = 0.005·√252 = 0.07937254
    # sortino (rf=0) = 21.275106 / 0.079373 = 268.041145...
    r = [0.01, 0.02, -0.01, 0.03]
    assert cagr(r) == pytest.approx(21.275106307663346)
    assert annualized_volatility(r) == pytest.approx(0.2711088342345192)
    assert sharpe(r, risk_free_rate=0.0) == pytest.approx(78.47441182702143)
    assert sortino(r, risk_free_rate=0.0) == pytest.approx(268.04114479304206)


def test_sharpe_none_when_volatility_zero_or_series_short():
    assert sharpe([0.0] * 10) is None        # vol = 0 → indefinito
    assert sharpe([0.01]) is None            # < 2 osservazioni
    assert annualized_volatility([0.01]) is None


def test_sortino_none_when_no_negative_returns():
    assert sortino([0.01, 0.02, 0.03]) is None  # downside deviation = 0


def test_calmar_known():
    # Con r = [0.01, 0.02, −0.01, 0.03]: curva 1.01, 1.0302, 1.019898, 1.050494
    # MDD = 1.019898/1.0302 − 1 = −0.01 esatto; calmar = 21.275106 / 0.01
    r = [0.01, 0.02, -0.01, 0.03]
    assert max_drawdown(r) == pytest.approx(-0.01)
    assert calmar(r) == pytest.approx(21.275106307663346 / 0.01)


def test_alpha_beta_y_equals_2x():
    # y = 2x → regressione OLS: beta = 2, alpha = 0
    x = [0.01, -0.02, 0.03, 0.0]
    y = [2 * v for v in x]
    result = alpha_beta(y, x)
    assert result is not None
    alpha, beta = result
    assert beta == pytest.approx(2.0)
    assert alpha == pytest.approx(0.0, abs=1e-12)


def test_alpha_beta_none_when_benchmark_flat_or_mismatched():
    assert alpha_beta([0.01, 0.02], [0.0, 0.0]) is None      # var(x) = 0
    assert alpha_beta([0.01, 0.02], [0.01]) is None          # lunghezze diverse


def test_information_ratio_known():
    # excess = y − x = [0.005, 0.01, −0.01, 0.01]; mean = 0.00375
    # std(excess, ddof=1) = 0.00946485; IR = 0.00375/0.00946485·√252 = 6.289526...
    y = [0.01, 0.02, -0.01, 0.03]
    x = [0.005, 0.01, 0.0, 0.02]
    assert information_ratio(y, x) == pytest.approx(6.28952617729537)


def test_recovery_factor_known():
    # r = [0.01, 0.02, −0.01, 0.03]: total = 0.05049494, MDD = −0.01
    # recovery = 0.05049494 / 0.01 = 5.049494
    r = [0.01, 0.02, -0.01, 0.03]
    assert recovery_factor(r) == pytest.approx(0.0504949400000001 / 0.01)
    assert recovery_factor([0.01, 0.02]) is None  # MDD = 0 → indefinito


def test_exposure_pct_known():
    # 2 giorni investiti su 4 → 50%
    assert exposure_pct([100.0, 0.0, 50.0, 0.0]) == pytest.approx(50.0)
    assert exposure_pct([]) is None


# --- metriche sui trade ------------------------------------------------------


def test_trade_metrics_known():
    # pnl = [10, −5, 20, −5]: win rate = 2/4 = 0.5
    # profit factor = (10+20)/|−5−5| = 30/10 = 3.0
    # expectancy = (10−5+20−5)/4 = 20/4 = 5.0
    pnls = [10.0, -5.0, 20.0, -5.0]
    assert win_rate(pnls) == pytest.approx(0.5)
    assert profit_factor(pnls) == pytest.approx(3.0)
    assert expectancy(pnls) == pytest.approx(5.0)
    assert win_rate([]) is None
    assert profit_factor([10.0, 20.0]) is None  # nessuna perdita → indefinito
    assert expectancy([]) is None


# --- servizio (repo finto, nessun DB) ---------------------------------------


def _service(repo, prices=None):
    fetcher = lambda symbol, start: dict(prices or {})  # noqa: E731
    return BacktestService(
        repo, fetcher,
        settings={"bot_capital_usd": 10000, "risk_free_rate_pct": 0.0, "benchmark_symbol": "SPY"},
    )


def test_summary_insufficient_sample_and_no_annualization():
    # 10 giorni (< 60) e 2 trade chiusi (< 30): metriche annualizzate azzerate
    snaps = [snap(date(2026, 1, d), 10000 + d * 10) for d in range(1, 11)]
    repo = FakeRepo(snaps=snaps, closed=[closed_trade(10.0), closed_trade(-5.0)])
    summary = _service(repo).summary()
    assert summary["n_days"] == 10
    assert summary["n_closed_trades"] == 2
    assert summary["insufficient_sample"] is True
    assert summary["annualization_available"] is False
    for key in ("cagr", "sharpe", "sortino", "calmar", "annualized_volatility"):
        assert summary[key] is None
    assert summary["total_return"] is not None       # non annualizzata: resta
    assert summary["win_rate"] == pytest.approx(0.5)
    assert summary["expectancy"] == pytest.approx(2.5)


def test_summary_annualization_available_with_60_days():
    base = date(2026, 1, 1)
    snaps = [
        snap(date.fromordinal(base.toordinal() + i), 10000 * (1.001 ** i)) for i in range(60)
    ]
    repo = FakeRepo(snaps=snaps)
    summary = _service(repo).summary()
    assert summary["n_days"] == 60
    assert summary["annualization_available"] is True
    assert summary["cagr"] is not None
    # 59 rendimenti costanti +0.1%: total = 1.001^59 − 1
    assert summary["total_return"] == pytest.approx(1.001**59 - 1)


def test_summary_filters_period_and_exposes_trade_extremes():
    snaps = [
        snap(date(2026, 1, 1), 100.0), snap(date(2026, 1, 2), 101.0),
        snap(date(2026, 2, 1), 102.0), snap(date(2026, 2, 2), 103.0),
    ]
    closed = [
        closed_trade(10.0, date(2026, 1, 5)),
        closed_trade(20.0, date(2026, 2, 5)),
        closed_trade(40.0, date(2026, 2, 6)),
        closed_trade(-5.0, date(2026, 2, 7)),
        closed_trade(-15.0, date(2026, 2, 8)),
    ]
    summary = _service(FakeRepo(snaps=snaps, closed=closed)).summary(
        date_from=date(2026, 2, 1), date_to=date(2026, 2, 28)
    )
    assert summary["n_days"] == 2
    assert summary["n_closed_trades"] == 4
    assert summary["max_win_usd"] == 40.0
    assert summary["max_loss_usd"] == -15.0
    assert summary["std_win_usd"] == pytest.approx(14.1421356237)
    assert summary["std_loss_usd"] == pytest.approx(7.0710678119)


def test_equity_curve_lump_sum_and_cash_flow_matched():
    # Prezzi SPY: 100, 101, 102. Capitale 10000 → lump-sum = 100 azioni.
    # Un'apertura bot da 500 USD il giorno 1 → 5 azioni per la vista matched.
    days = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]
    prices = {days[0]: 100.0, days[1]: 101.0, days[2]: 102.0}
    open_pos = SimpleNamespace(
        etoro_position_id=1, symbol="AAPL", amount_usd=500.0, entry_price=50.0,
        opened_at=datetime(2026, 1, 1, 10, tzinfo=timezone.utc), sector="tech",
    )
    repo = FakeRepo(
        snaps=[snap(days[0], 10000.0), snap(days[1], 10050.0), snap(days[2], 10100.0)],
        open_=[open_pos],
    )
    curve = _service(repo, prices=prices).equity_curve("spy")
    assert [p["equity_usd"] for p in curve] == [10000.0, 10050.0, 10100.0]
    # lump-sum: 100 azioni × prezzo → 10000, 10100, 10200
    assert [p["spy_lump_sum_usd"] for p in curve] == pytest.approx([10000.0, 10100.0, 10200.0])
    # matched: 5 azioni × prezzo → 500, 505, 510
    assert [p["spy_cash_flow_matched_usd"] for p in curve] == pytest.approx([500.0, 505.0, 510.0])


def test_monthly_returns_known():
    # Gen: 100 → 110 (+10%). Feb: 110 → 121 (+10%) → 108.9 (−10%): 1.1·0.9 − 1 = −1%
    snaps = [
        snap(date(2026, 1, 30), 100.0),
        snap(date(2026, 1, 31), 110.0),
        snap(date(2026, 2, 1), 121.0),
        snap(date(2026, 2, 2), 108.9),
    ]
    rows = _service(FakeRepo(snaps=snaps)).monthly_returns()
    assert len(rows) == 1 and rows[0]["year"] == 2026
    months = rows[0]["months"]
    assert months[0] == pytest.approx(10.0)
    assert months[1] == pytest.approx(-1.0)
    assert months[2:] == [None] * 10
