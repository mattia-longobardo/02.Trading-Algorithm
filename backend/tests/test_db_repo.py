"""Test del repository su Postgres 18 effimero (journal, registry §7, settings)."""

from datetime import date, datetime, timezone

from etoro_bot.domain import DecisionStage, ExecutionResult, ExecutionStatus, Side

NOW = datetime(2026, 7, 20, 8, 30, tzinfo=timezone.utc)


def test_run_lifecycle_and_journal(repo):
    repo.create_run("run-1", environment="demo")
    repo.add_decision("run-1", "AAPL", DecisionStage.ANALYST,
                      {"score": 0.4, "summary": "ok"})
    repo.add_decision("run-1", "AAPL", DecisionStage.RISK,
                      {"approved": False, "reasons": ["oltre limite"]})
    repo.add_execution("run-1", ExecutionResult(
        symbol="AAPL", side=Side.BUY, amount_usd=100.0,
        status=ExecutionStatus.FILLED, execution_price=200.0, etoro_position_id=99,
    ))
    repo.finish_run("run-1", {"candidates": 1, "executed": 1})

    runs = repo.list_runs()
    assert len(runs) == 1 and runs[0].summary_json["executed"] == 1
    decisions = repo.get_run_decisions("run-1")
    assert [d.stage for d in decisions] == ["analyst", "risk"]
    assert repo.count_filled_today() == 1


def test_delete_run_removes_everything_that_points_at_it(repo):
    repo.create_run("run-del", environment="demo")
    repo.add_decision("run-del", "AAPL", DecisionStage.ANALYST, {"score": 0.1})
    repo.add_execution("run-del", ExecutionResult(
        symbol="AAPL", side=Side.BUY, amount_usd=100.0,
        status=ExecutionStatus.FILLED, execution_price=200.0, etoro_position_id=42,
    ))
    repo.register_open_position(
        etoro_position_id=42, run_id="run-del", symbol="AAPL", instrument_id=1,
        amount_usd=100.0, entry_price=200.0, opened_at=NOW,
    )
    # Una seconda run non deve essere toccata.
    repo.create_run("run-keep", environment="demo")
    repo.add_decision("run-keep", "MSFT", DecisionStage.ANALYST, {"score": 0.2})

    assert repo.delete_run("run-del") is True
    assert repo.get_run("run-del") is None
    assert repo.get_run_decisions("run-del") == []
    assert repo.list_executions() == []
    assert repo.open_positions() == []

    assert repo.get_run("run-keep") is not None
    assert len(repo.get_run_decisions("run-keep")) == 1


def test_delete_run_returns_false_when_missing(repo):
    assert repo.delete_run("mai-esistita") is False


def test_bot_positions_registry(repo):
    repo.create_run("run-2", environment="demo")
    repo.register_open_position(
        etoro_position_id=123, run_id="run-2", symbol="MSFT", instrument_id=5,
        amount_usd=200.0, entry_price=400.0, opened_at=NOW, sector="tech",
    )
    assert [p.etoro_position_id for p in repo.open_positions()] == [123]

    repo.close_position(123, close_price=420.0, realized_pnl_usd=10.0, close_reason="bot_close")
    assert repo.open_positions() == []
    closed = repo.closed_positions()
    assert closed[0].realized_pnl_usd == 10.0
    # una seconda chiusura non sovrascrive
    repo.close_position(123, close_price=1.0, realized_pnl_usd=-99.0, close_reason="dup")
    assert repo.closed_positions()[0].realized_pnl_usd == 10.0


def test_equity_snapshot_upsert(repo):
    d = date(2026, 7, 20)
    repo.record_equity_snapshot(d, 10_000.0, 8_000.0, 2_000.0)
    repo.record_equity_snapshot(d, 10_100.0, 8_100.0, 2_000.0)
    series = repo.equity_series()
    assert len(series) == 1 and series[0].equity_usd == 10_100.0


def test_app_settings_and_audit(repo):
    assert repo.get_setting("environment") is None
    repo.set_setting("environment", "demo", source="test")
    repo.set_setting("environment", "real", source="test")
    assert repo.get_setting("environment") == "real"
    audit = repo.settings_audit()
    assert len(audit) == 2
    assert audit[0].new_value == {"value": "real"}
    assert audit[0].old_value == {"value": "demo"}
