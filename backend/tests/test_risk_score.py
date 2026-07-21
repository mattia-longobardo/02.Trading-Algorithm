"""Test del risk score composito deterministico (§11.4): niente LLM, niente DB."""

from datetime import datetime, timezone

import pytest

from etoro_bot.config import RiskRules, load_risk_score_config
from etoro_bot.domain import Position
from etoro_bot.services.risk_score import compute_risk_score, hhi, normalize

RULES = RiskRules()
CFG = load_risk_score_config()


def position(symbol="AAPL", amount=100.0, sector="tech", pid=1):
    return Position(
        etoro_position_id=pid, symbol=symbol, instrument_id=pid, amount_usd=amount,
        entry_price=10.0, opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc), sector=sector,
    )


def compute(positions=(), cash=10_000.0, equity_returns=(), spy_returns=None, breaker=None):
    return compute_risk_score(
        positions=list(positions),
        cash_usd=cash,
        equity_returns=list(equity_returns),
        spy_returns=spy_returns,
        breaker_state=breaker or {"tripped": False, "consecutive_losses": 0},
        risk_rules=RULES,
        cfg=CFG,
    )


# --- funzioni pure -----------------------------------------------------------


def test_hhi_equal_weights():
    # 4 pesi uguali: HHI = 4 · (1/4)² = 0.25, con o senza normalizzazione a monte
    assert hhi([0.25, 0.25, 0.25, 0.25]) == pytest.approx(0.25)
    assert hhi([1.0, 1.0, 1.0, 1.0]) == pytest.approx(0.25)
    # Tutto in una posizione → 1.0; nessun peso → 0.0
    assert hhi([500.0]) == pytest.approx(1.0)
    assert hhi([]) == 0.0
    assert hhi([0.0, 0.0]) == 0.0


def test_normalize_linear_and_clamp():
    # Lineare: a metà tra low e high → 5.0
    assert normalize(0.5, 0.0, 1.0) == pytest.approx(5.0)
    # Clamp: sotto low → 0, sopra high → 10
    assert normalize(-3.0, 0.0, 1.0) == 0.0
    assert normalize(42.0, 0.0, 1.0) == 10.0
    assert normalize(0.10, 0.10, 1.00) == 0.0
    assert normalize(1.00, 0.10, 1.00) == 10.0


# --- score composito ---------------------------------------------------------


def test_empty_portfolio_and_empty_equity_scores_minimum():
    # Equity vuota, nessuna posizione, breaker a riposo: tutte le componenti a 0
    # → media pesata 0 ma lo score non scende MAI sotto 1.0.
    result = compute(positions=[], cash=0.0, equity_returns=[])
    assert result.score == 1.0
    assert result.band == "low"
    assert len(result.breakdown) == len(CFG["weights"])
    assert all(item["suggestion"] is None for item in result.breakdown)


def test_bands_low_and_extreme():
    # Portafoglio vuoto → score 1.0 → fascia low (1-3).
    assert compute(positions=[], cash=10_000.0).band == "low"
    # Tutto investito in UNA posizione di UN settore, cash 0, breaker scattato,
    # equity molto volatile e in drawdown: concentrazioni HHI = 1, esposizione
    # oltre il limite, cash sotto il buffer, vol oltre il 40%, safety 10 →
    # media pesata alta → fascia extreme (o almeno high).
    volatile = [-0.10, 0.02, -0.12, 0.03, -0.11]
    result = compute(
        positions=[position(amount=10_000.0)],
        cash=0.0,
        equity_returns=volatile,
        spy_returns=volatile,  # beta 1.0
        breaker={"tripped": True, "consecutive_losses": 4},
    )
    assert result.score >= 7.0
    assert result.band in ("high", "extreme")


def test_sector_over_threshold_generates_suggestion_and_explanation():
    # Settore tech = 3000/10000 = 30% dell'equity: oltre la soglia del 20%.
    # HHI settoriale = 1.0 → componente 10/10 → suggestion presente.
    result = compute(positions=[position(amount=3_000.0, sector="tech")], cash=7_000.0)
    sector = next(i for i in result.breakdown if i["key"] == "sector_concentration")
    assert sector["value_0_10"] == pytest.approx(10.0)
    assert "tech" in sector["explanation"]
    assert "oltre la soglia del 20%" in sector["explanation"]
    assert sector["suggestion"] is not None


def test_sector_within_threshold_has_no_suggestion_wording():
    # Due settori da 500 su equity 10000 → 5% ciascuno: entro la soglia del 20%,
    # HHI = 0.5 → normalize(0.5, 0.15, 1.0) = 4.12 < 7 → nessuna suggestion.
    result = compute(
        positions=[position(amount=500.0, sector="tech", pid=1),
                   position(amount=500.0, sector="energy", pid=2)],
        cash=9_000.0,
    )
    sector = next(i for i in result.breakdown if i["key"] == "sector_concentration")
    assert "entro la soglia" in sector["explanation"]
    assert sector["suggestion"] is None


def test_breaker_tripped_maxes_safety_component():
    result = compute(breaker={"tripped": True, "consecutive_losses": 0})
    safety = next(i for i in result.breakdown if i["key"] == "safety_state")
    assert safety["value_0_10"] == pytest.approx(10.0)
    assert safety["suggestion"] is not None


def test_beta_component_zero_without_benchmark_data():
    result = compute(equity_returns=[0.01, -0.01, 0.02], spy_returns=None)
    beta = next(i for i in result.breakdown if i["key"] == "beta_vs_spy")
    assert beta["value_0_10"] == 0.0
    assert "insufficienti" in beta["explanation"]


def test_score_rounded_to_one_decimal_and_weighted():
    # Il breakdown riporta pesi in percento che sommano a 100.
    result = compute(positions=[position(amount=1_000.0)], cash=9_000.0)
    assert sum(i["weight_pct"] for i in result.breakdown) == pytest.approx(100.0)
    assert result.score == round(result.score, 1)
    assert result.score >= 1.0
