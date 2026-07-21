"""Test del risk manager deterministico: ogni regola ha il suo caso."""

from datetime import datetime, timezone

import pytest

from etoro_bot.config import RiskRules
from etoro_bot.domain import (
    AssetType,
    PortfolioSnapshot,
    Position,
    ProposedOrder,
    Side,
)
from etoro_bot.risk.rules import evaluate_orders

RULES = RiskRules()  # default prudenti di config


def snapshot(cash=10_000.0, positions=None):
    return PortfolioSnapshot(cash_usd=cash, positions=positions or [])


def order(symbol="AAPL", amount=200.0, side=Side.BUY, asset_type=AssetType.STOCK,
          sector="tech", position_id=None):
    return ProposedOrder(
        symbol=symbol, instrument_id=1, side=side, amount_usd=amount,
        asset_type=asset_type, sector=sector, position_id=position_id,
    )


def position(symbol="MSFT", amount=300.0, sector="tech", pid=1):
    return Position(
        etoro_position_id=pid, symbol=symbol, instrument_id=pid, amount_usd=amount,
        entry_price=100.0, opened_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        sector=sector,
    )


def test_order_within_all_limits_is_approved():
    verdicts = evaluate_orders([order()], snapshot(), RULES)
    assert verdicts[0].approved


def test_max_order_amount():
    # 10.000 USD disponibili / 10 posizioni massime = 1.000 USD per trade.
    verdicts = evaluate_orders([order(amount=1_001.0)], snapshot(), RULES)
    assert not verdicts[0].approved
    assert any("massimo per ordine" in r for r in verdicts[0].reasons)


def test_disallowed_asset_type_rejected():
    bad = ProposedOrder(
        symbol="EURUSD", instrument_id=5, side=Side.BUY, amount_usd=100,
        asset_type=AssetType.STOCK, sector="fx",
    )
    # forza un asset type non ammesso simulando regole più strette
    rules = RiskRules(allowed_asset_types=("etf",))
    verdicts = evaluate_orders([bad], snapshot(), rules)
    assert not verdicts[0].approved
    assert any("non ammesso" in r for r in verdicts[0].reasons)


def test_short_selling_rejected():
    verdicts = evaluate_orders([order(side=Side.SELL)], snapshot(), RULES)
    # sell senza position_id = chiusura malformata
    assert not verdicts[0].approved


def test_close_always_passes_with_position_id():
    verdicts = evaluate_orders(
        [order(side=Side.SELL, position_id=42, amount=999_999.0)], snapshot(cash=0.0), RULES
    )
    assert verdicts[0].approved


def test_zero_equity_no_openings():
    verdicts = evaluate_orders([order(amount=10.0)], snapshot(cash=0.0), RULES)
    assert not verdicts[0].approved
    assert any("equity zero" in r for r in verdicts[0].reasons)


def test_position_pct_equity_cumulative_with_existing():
    # equity 10k: MSFT già a 300 → un nuovo ordine MSFT da 250 porterebbe a 550 = 5.5% > 5%
    snap = snapshot(cash=9_700.0, positions=[position(symbol="MSFT", amount=300.0)])
    verdicts = evaluate_orders([order(symbol="MSFT", amount=250.0)], snap, RULES)
    assert not verdicts[0].approved
    assert any("% dell'equity" in r for r in verdicts[0].reasons)


def test_total_exposure_limit():
    # equity 1000, esposizione già 590 (59%): +20 → 61% > 60%
    snap = snapshot(cash=410.0, positions=[position(amount=590.0, sector="energy")])
    rules = RiskRules(max_position_pct_equity=100.0, min_cash_buffer_pct=0.0,
                      max_sector_exposure_pct=100.0)
    verdicts = evaluate_orders([order(amount=20.0, sector="tech")], snap, rules)
    assert not verdicts[0].approved
    assert any("esposizione totale" in r for r in verdicts[0].reasons)


def test_sector_exposure_limit():
    # equity 10k, tech già a 1900: +200 → 21% > 20%
    snap = snapshot(cash=8_100.0, positions=[position(amount=1_900.0, sector="tech")])
    rules = RiskRules(max_position_pct_equity=100.0, max_total_exposure_pct=100.0)
    verdicts = evaluate_orders([order(amount=200.0, sector="tech")], snap, rules)
    assert not verdicts[0].approved
    assert any("settore" in r for r in verdicts[0].reasons)


def test_max_open_positions():
    positions = [position(symbol=f"S{i}", pid=i, amount=10.0) for i in range(10)]
    snap = snapshot(cash=9_900.0, positions=positions)
    verdicts = evaluate_orders([order(amount=50.0)], snap, RULES)
    assert not verdicts[0].approved
    assert any("posizioni aperte" in r for r in verdicts[0].reasons)


def test_max_orders_per_run_cumulative():
    orders = [order(symbol=f"T{i}", amount=100.0, sector=f"s{i}") for i in range(4)]
    verdicts = evaluate_orders(orders, snapshot(cash=100_000.0), RULES)
    assert [v.approved for v in verdicts] == [True, True, True, False]
    assert any("ordini per run" in r for r in verdicts[3].reasons)


def test_max_orders_per_day_counts_journal():
    orders = [order(symbol=f"T{i}", amount=100.0, sector=f"s{i}") for i in range(2)]
    verdicts = evaluate_orders(orders, snapshot(cash=100_000.0), RULES, orders_filled_today=4)
    assert [v.approved for v in verdicts] == [True, False]
    assert any("giornalieri" in r for r in verdicts[1].reasons)


def test_cash_buffer():
    # equity 1000, cash 1000: un ordine da 810 lascerebbe 190 = 19% < 20%
    rules = RiskRules(max_open_positions=1, max_position_pct_equity=100.0,
                      max_total_exposure_pct=100.0, max_sector_exposure_pct=100.0)
    verdicts = evaluate_orders([order(amount=810.0)], snapshot(cash=1_000.0), rules)
    assert not verdicts[0].approved
    assert any("cash buffer" in r.lower() for r in verdicts[0].reasons)


def test_each_passes_alone_but_cumulative_breaches():
    """Il caso richiesto dalla spec: ogni ordine passa da solo, il cumulo sfora."""
    rules = RiskRules(max_open_positions=2, max_position_pct_equity=100.0,
                      max_total_exposure_pct=100.0, max_sector_exposure_pct=100.0,
                      min_cash_buffer_pct=20.0, max_orders_per_run=10,
                      max_orders_per_day=10)
    snap = snapshot(cash=1_000.0)
    o1 = order(symbol="A", amount=400.0, sector="s1")
    o2 = order(symbol="B", amount=500.0, sector="s2")
    # da soli passano entrambi
    assert evaluate_orders([o1], snap, rules)[0].approved
    assert evaluate_orders([o2], snap, rules)[0].approved
    # in sequenza il secondo sfora il cash buffer (1000-400-500=100 → 10% < 20%)
    verdicts = evaluate_orders([o1, o2], snap, rules)
    assert verdicts[0].approved and not verdicts[1].approved


def test_rejection_does_not_consume_cumulative_budget():
    rules = RiskRules(max_orders_per_run=2)
    orders = [
        order(symbol="A", amount=11_000.0),   # respinto (oltre cash/10)
        order(symbol="B", amount=100.0, sector="s1"),
        order(symbol="C", amount=100.0, sector="s2"),
    ]
    verdicts = evaluate_orders(orders, snapshot(cash=100_000.0), rules)
    assert [v.approved for v in verdicts] == [False, True, True]
