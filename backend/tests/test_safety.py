"""Test di kill switch e circuit breaker (nessuna dipendenza da rete o DB)."""

import json

from etoro_bot.config import CircuitBreakerRules
from etoro_bot.safety.circuit_breaker import CircuitBreaker
from etoro_bot.safety.kill_switch import (
    engage_kill_switch,
    kill_switch_active,
    release_kill_switch,
)


def test_kill_switch_file(tmp_path, monkeypatch):
    monkeypatch.setenv("KILL_SWITCH_DIR", str(tmp_path))
    monkeypatch.delenv("ETORO_BOT_KILL", raising=False)
    assert not kill_switch_active()
    engage_kill_switch("test")
    assert kill_switch_active()
    assert release_kill_switch()
    assert not kill_switch_active()


def test_kill_switch_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("KILL_SWITCH_DIR", str(tmp_path))
    monkeypatch.setenv("ETORO_BOT_KILL", "1")
    assert kill_switch_active()
    release_kill_switch()
    assert kill_switch_active()  # l'env non è rimovibile da codice


RULES = CircuitBreakerRules(max_daily_loss_pct=2.0, max_consecutive_losses=3, cooloff_hours=24)


def test_breaker_consecutive_losses(tmp_path):
    cb = CircuitBreaker(RULES, state_dir=tmp_path)
    for _ in range(2):
        cb.record_closed_trade(-10.0, equity_usd=100_000.0)
    assert not cb.blocks_openings()
    cb.record_closed_trade(-10.0, equity_usd=100_000.0)
    assert cb.blocks_openings()
    assert "consecutive" in (cb.state.reason or "")


def test_breaker_win_resets_streak(tmp_path):
    cb = CircuitBreaker(RULES, state_dir=tmp_path)
    cb.record_closed_trade(-10.0, equity_usd=100_000.0)
    cb.record_closed_trade(-10.0, equity_usd=100_000.0)
    cb.record_closed_trade(5.0, equity_usd=100_000.0)
    cb.record_closed_trade(-10.0, equity_usd=100_000.0)
    assert not cb.blocks_openings()


def test_breaker_daily_loss(tmp_path):
    cb = CircuitBreaker(RULES, state_dir=tmp_path)
    cb.record_closed_trade(-150.0, equity_usd=10_000.0)  # -1.5%
    assert not cb.blocks_openings()
    cb.record_closed_trade(-60.0, equity_usd=10_000.0)   # cumulato -2.1%
    assert cb.blocks_openings()


def test_breaker_survives_restart(tmp_path):
    cb = CircuitBreaker(RULES, state_dir=tmp_path)
    for _ in range(3):
        cb.record_closed_trade(-10.0, equity_usd=100_000.0)
    assert cb.blocks_openings()
    cb2 = CircuitBreaker(RULES, state_dir=tmp_path)  # riavvio
    assert cb2.blocks_openings()


def test_breaker_corrupted_state_fails_safe(tmp_path):
    (tmp_path / "circuit_breaker.json").write_text("{not json", encoding="utf-8")
    cb = CircuitBreaker(RULES, state_dir=tmp_path)
    assert cb.blocks_openings()


def test_breaker_cooloff_expires(tmp_path):
    cb = CircuitBreaker(RULES, state_dir=tmp_path)
    for _ in range(3):
        cb.record_closed_trade(-10.0, equity_usd=100_000.0)
    # forza il cooloff nel passato
    state = json.loads((tmp_path / "circuit_breaker.json").read_text())
    state["cooloff_until"] = "2000-01-01T00:00:00+00:00"
    (tmp_path / "circuit_breaker.json").write_text(json.dumps(state))
    cb2 = CircuitBreaker(RULES, state_dir=tmp_path)
    assert not cb2.blocks_openings()
