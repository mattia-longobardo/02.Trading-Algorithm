"""Risk manager deterministico: funzioni pure, nessuna rete, nessun LLM.

Valuta gli ordini in sequenza simulando l'effetto cumulativo su cash,
esposizione, settori e numero di posizioni: ordini che passerebbero da soli
possono essere respinti se il cumulo sfora. Le chiusure passano sempre
(riducono il rischio); serve solo position_id.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from etoro_bot.config import RiskRules
from etoro_bot.domain import PortfolioSnapshot, ProposedOrder, RiskVerdict, Side


@dataclass
class _SimState:
    """Stato simulato del portafoglio mentre gli ordini vengono approvati."""

    cash_usd: float
    equity_usd: float
    open_positions: int
    per_symbol: dict[str, float] = field(default_factory=dict)
    per_sector: dict[str, float] = field(default_factory=dict)
    approved_in_run: int = 0
    max_trade_amount_usd: float = 0.0


def _initial_state(snapshot: PortfolioSnapshot, rules: RiskRules) -> _SimState:
    state = _SimState(
        cash_usd=snapshot.cash_usd,
        equity_usd=snapshot.equity_usd,
        open_positions=len(snapshot.positions),
    )
    for pos in snapshot.positions:
        state.per_symbol[pos.symbol] = state.per_symbol.get(pos.symbol, 0.0) + pos.amount_usd
        state.per_sector[pos.sector] = state.per_sector.get(pos.sector, 0.0) + pos.amount_usd
    state.max_trade_amount_usd = max(snapshot.cash_usd, 0.0) / rules.max_open_positions
    return state


def _check_opening(order: ProposedOrder, state: _SimState, rules: RiskRules,
                   orders_filled_today: int) -> list[str]:
    reasons: list[str] = []

    if order.asset_type.value not in rules.allowed_asset_types:
        reasons.append(
            f"asset type '{order.asset_type.value}' non ammesso "
            f"(consentiti: {', '.join(rules.allowed_asset_types)})"
        )
    if order.side is not Side.BUY:
        reasons.append("solo aperture long-only (buy) sono ammesse")
    if order.amount_usd <= 0:
        reasons.append("importo non positivo")
    if state.equity_usd <= 0:
        reasons.append("equity zero o negativa: nessuna apertura consentita")
        return reasons  # i controlli percentuali sotto non sono definiti

    if order.amount_usd > state.max_trade_amount_usd:
        reasons.append(
            f"importo {order.amount_usd:.2f} USD oltre il massimo per ordine "
            f"({state.max_trade_amount_usd:.2f} USD = equity disponibile / "
            f"{rules.max_open_positions} posizioni)"
        )

    symbol_after = state.per_symbol.get(order.symbol, 0.0) + order.amount_usd
    if symbol_after / state.equity_usd * 100 > rules.max_position_pct_equity:
        reasons.append(
            f"posizione su {order.symbol} arriverebbe a "
            f"{symbol_after / state.equity_usd * 100:.1f}% dell'equity "
            f"(max {rules.max_position_pct_equity}%)"
        )

    exposure_now = state.equity_usd - state.cash_usd
    exposure_after = exposure_now + order.amount_usd
    if exposure_after / state.equity_usd * 100 > rules.max_total_exposure_pct:
        reasons.append(
            f"esposizione totale arriverebbe a "
            f"{exposure_after / state.equity_usd * 100:.1f}% "
            f"(max {rules.max_total_exposure_pct}%)"
        )

    sector_after = state.per_sector.get(order.sector, 0.0) + order.amount_usd
    if sector_after / state.equity_usd * 100 > rules.max_sector_exposure_pct:
        reasons.append(
            f"settore '{order.sector}' arriverebbe a "
            f"{sector_after / state.equity_usd * 100:.1f}% dell'equity "
            f"(max {rules.max_sector_exposure_pct}%)"
        )

    # Ogni apertura eToro crea una posizione distinta, anche su un simbolo già detenuto.
    if state.open_positions + 1 > rules.max_open_positions:
        reasons.append(f"numero massimo di posizioni aperte raggiunto ({rules.max_open_positions})")

    if state.approved_in_run + 1 > rules.max_orders_per_run:
        reasons.append(f"massimo ordini per run raggiunto ({rules.max_orders_per_run})")

    if orders_filled_today + state.approved_in_run + 1 > rules.max_orders_per_day:
        reasons.append(f"massimo ordini giornalieri raggiunto ({rules.max_orders_per_day})")

    cash_after = state.cash_usd - order.amount_usd
    if cash_after / state.equity_usd * 100 < rules.min_cash_buffer_pct:
        reasons.append(
            f"cash buffer scenderebbe a {max(cash_after, 0.0) / state.equity_usd * 100:.1f}% "
            f"(minimo {rules.min_cash_buffer_pct}%)"
        )

    return reasons


def evaluate_orders(
    orders: list[ProposedOrder],
    snapshot: PortfolioSnapshot,
    rules: RiskRules,
    orders_filled_today: int = 0,
) -> list[RiskVerdict]:
    """Valuta gli ordini in sequenza; l'effetto degli approvati si cumula."""
    state = _initial_state(snapshot, rules)
    verdicts: list[RiskVerdict] = []

    for order in orders:
        if order.side is Side.SELL:
            # Chiusura: passa sempre, ma serve il riferimento alla posizione.
            if order.position_id is None:
                verdicts.append(RiskVerdict(
                    order=order, approved=False,
                    reasons=["chiusura senza position_id: impossibile da eseguire"],
                ))
            else:
                verdicts.append(RiskVerdict(order=order, approved=True,
                                            reasons=["chiusura: riduce il rischio"]))
            continue

        reasons = _check_opening(order, state, rules, orders_filled_today)
        approved = not reasons
        if approved:
            state.cash_usd -= order.amount_usd
            state.per_symbol[order.symbol] = (
                state.per_symbol.get(order.symbol, 0.0) + order.amount_usd
            )
            state.per_sector[order.sector] = (
                state.per_sector.get(order.sector, 0.0) + order.amount_usd
            )
            state.open_positions += 1
            state.approved_in_run += 1
            reasons = ["entro tutti i limiti"]
        verdicts.append(RiskVerdict(order=order, approved=approved, reasons=reasons))

    return verdicts
