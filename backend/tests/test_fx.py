"""Tassi di cambio: cache, degradazione e conversione.

Nessun test tocca la rete: `_fetch_remote` è sempre sostituito, così la suite
resta deterministica e veloce anche offline.
"""

import pytest

from etoro_bot.services import fx


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    fx.reset_cache()
    yield
    fx.reset_cache()


def test_rates_include_base_identity(monkeypatch):
    monkeypatch.setattr(fx, "_fetch_remote", lambda: {"EUR": 0.92, "USD": 1.0})
    payload = fx.get_rates()
    assert payload["base"] == "USD"
    assert payload["rates"]["USD"] == 1.0
    assert payload["rates"]["EUR"] == pytest.approx(0.92)
    assert payload["stale"] is False


def test_unsupported_currencies_are_dropped(monkeypatch):
    monkeypatch.setattr(fx, "_fetch_remote", lambda: fx._normalise({"EUR": 0.92, "XXX": 3.0}))
    assert "XXX" not in fx.get_rates()["rates"]


def test_second_call_uses_cache(monkeypatch):
    calls = {"n": 0}

    def _fetch():
        calls["n"] += 1
        return {"EUR": 0.9}

    monkeypatch.setattr(fx, "_fetch_remote", _fetch)
    fx.get_rates()
    fx.get_rates()
    assert calls["n"] == 1


def test_network_failure_falls_back_to_usd_only(monkeypatch):
    def _boom():
        raise RuntimeError("rete giù")

    monkeypatch.setattr(fx, "_fetch_remote", _boom)
    payload = fx.get_rates()
    assert payload["stale"] is True
    assert payload["rates"] == {"USD": 1.0}
    # Degradazione sicura: senza tasso si mostrano dollari, non zeri.
    assert fx.rate_for("EUR") == 1.0


def test_disk_cache_survives_process_restart(monkeypatch):
    monkeypatch.setattr(fx, "_fetch_remote", lambda: {"EUR": 0.88})
    fx.get_rates()
    fx.reset_cache()

    def _boom():
        raise RuntimeError("rete giù")

    monkeypatch.setattr(fx, "_fetch_remote", _boom)
    assert fx.get_rates()["rates"]["EUR"] == pytest.approx(0.88)


def test_convert_preserves_none(monkeypatch):
    monkeypatch.setattr(fx, "_fetch_remote", lambda: {"EUR": 0.5})
    assert fx.convert(None, "EUR") is None
    assert fx.convert(200.0, "EUR") == pytest.approx(100.0)
    assert fx.convert(200.0, "USD") == pytest.approx(200.0)
