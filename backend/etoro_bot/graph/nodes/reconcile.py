"""Nodo reconcile (codice): il conto reale è la fonte di verità.

Incrocia le posizioni dell'API con il registry bot_positions (§7): le posizioni
API non registrate (aperte a mano dall'utente) sono IGNORATE; le posizioni del
registry sparite dall'API sono marcate chiuse esternamente (PnL da trade
history se disponibile) e loggate come anomalia. QUALSIASI eccezione ferma la
run (fail-safe).
"""

from __future__ import annotations

from etoro_bot.domain import DecisionStage, PortfolioSnapshot, Position
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.state import BotState


class ReconcileError(RuntimeError):
    """Riconciliazione fallita: la run si ferma."""


def reconcile(state: BotState, deps: GraphDeps) -> dict:
    try:
        return _reconcile(state, deps)
    except ReconcileError:
        raise
    except Exception as exc:
        raise ReconcileError(f"riconciliazione fallita: {exc}") from exc


def _reconcile(state: BotState, deps: GraphDeps) -> dict:
    run_id = state["run_id"]
    portfolio = deps.client.get_portfolio() or {}
    api_ids = {
        int(p["positionID"])
        for p in portfolio.get("positions") or []
        if p.get("positionID") is not None
    }
    registry = deps.repo.open_positions()

    anomalies: list[str] = []
    vanished = [p for p in registry if p.etoro_position_id not in api_ids]
    if vanished:
        earliest = min(p.opened_at for p in vanished)
        history = {
            int(t["positionId"]): t
            for t in deps.client.get_trade_history(min_date=earliest)
            if t.get("positionId") is not None
        }
        for pos in vanished:
            trade = history.get(pos.etoro_position_id)
            pnl = trade.get("netProfit") if trade else None
            close_price = trade.get("closeRate") if trade else None
            deps.repo.close_position(
                pos.etoro_position_id,
                close_price=close_price,
                realized_pnl_usd=pnl,
                close_reason="closed_externally",
            )
            message = (
                f"posizione {pos.etoro_position_id} ({pos.symbol}) non più presente "
                f"sull'API: chiusa esternamente (pnl={pnl if pnl is not None else 'n/d'})"
            )
            anomalies.append(message)
            deps.repo.add_decision(
                run_id,
                pos.symbol,
                DecisionStage.RECONCILE_ANOMALY,
                {
                    "etoro_position_id": pos.etoro_position_id,
                    "close_price": close_price,
                    "realized_pnl_usd": pnl,
                    "detail": message,
                },
            )

    bot_open = [p for p in registry if p.etoro_position_id in api_ids]
    rates = deps.client.get_rates([p.instrument_id for p in bot_open]) if bot_open else {}
    positions: list[Position] = []
    for pos in bot_open:
        rate = rates.get(pos.instrument_id) or {}
        positions.append(
            Position(
                etoro_position_id=pos.etoro_position_id,
                symbol=pos.symbol,
                instrument_id=pos.instrument_id,
                amount_usd=pos.amount_usd,
                entry_price=pos.entry_price,
                opened_at=pos.opened_at,
                current_price=rate.get("bid") or rate.get("ask"),
                sector=getattr(pos, "sector", None) or "unknown",
            )
        )

    # La liquidità disponibile arriva direttamente dal portafoglio eToro.
    # Non viene più mantenuto un capitale manuale parallelo nelle impostazioni.
    credit = portfolio.get("credit")
    if credit is None:
        raise ReconcileError("portfolio eToro senza campo credit")
    cash = max(float(credit), 0.0)

    snapshot = PortfolioSnapshot(cash_usd=cash, positions=positions, anomalies=anomalies)
    return {"portfolio": snapshot.model_dump(mode="json")}
