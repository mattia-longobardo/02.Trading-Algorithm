"""Test dei guardrail di §10: enforced dal backend, mai solo dalla UI."""

import pytest

from etoro_bot.services.app_settings import (
    LIVE_CONFIRMATION,
    AppSettingsService,
    SettingsValidationError,
)


@pytest.fixture(autouse=True)
def safety_env(monkeypatch, tmp_path):
    """Kill switch/breaker su directory pulita e nessun kill via env."""
    monkeypatch.setenv("KILL_SWITCH_DIR", str(tmp_path))
    monkeypatch.delenv("ETORO_BOT_KILL", raising=False)


# Le chiavi eToro non vivono più nell'ambiente: sono credenziali personali
# cifrate su Postgres. Il servizio riceve quindi lo stato "configurate sì/no"
# dal chiamante (l'API lo ricava dall'identità SSO della richiesta).
CONFIGURED = {"etoro_configured": True}


@pytest.fixture()
def svc(repo):
    return AppSettingsService(repo)


# --- lettura -----------------------------------------------------------------


def test_effective_defaults_from_yaml(svc):
    effective = svc.get_effective()
    assert effective["environment"] == "demo"
    assert effective["schedule_utc"] == "08:30"
    assert effective["timezone"] == "Europe/Rome"
    assert effective["weekdays_only"] is True
    assert effective["risk_limits"]["max_open_positions"] == 10
    assert effective["live_ack"] is None


def test_db_value_overrides_yaml(svc, repo):
    limits = svc.get_effective()["risk_limits"]
    repo.set_setting("risk_limits", {**limits, "max_open_positions": 7})
    assert svc.get_effective()["risk_limits"]["max_open_positions"] == 7


# --- guardrail ---------------------------------------------------------------


def test_to_real_without_confirmation_is_422(svc):
    with pytest.raises(SettingsValidationError) as exc:
        svc.update({"environment": "real"})
    assert exc.value.status_code == 422
    assert "confirmation: true" in str(exc.value)


def test_to_real_allowed_without_any_prior_demo_runs(svc, repo):
    """Il guardrail "N run demo prima di real" è stato rimosso: la scelta
    demo/real è solo quella dell'utente, senza altre condizioni bloccanti lato
    codice, a patto che valgano gli altri guardrail (chiavi, kill switch,
    breaker, conferma esplicita). Nessuna run pregressa nel journal."""
    assert repo.list_runs() == []
    effective = svc.update(
        {"environment": "real", "confirmation": LIVE_CONFIRMATION}, **CONFIGURED
    )
    assert effective["environment"] == "real"
    assert effective["live_ack"] is not None
    audited_keys = {entry.key for entry in repo.settings_audit()}
    assert {"environment", "live_ack"} <= audited_keys


def test_real_blocked_without_etoro_keys(svc, repo):
    with pytest.raises(SettingsValidationError) as exc:
        svc.update({"environment": "real", "confirmation": LIVE_CONFIRMATION})
    assert "chiavi eToro" in str(exc.value)


def test_real_blocked_by_kill_switch(svc, repo):
    from etoro_bot.safety.kill_switch import engage_kill_switch

    engage_kill_switch("test")
    with pytest.raises(SettingsValidationError) as exc:
        svc.update(
            {"environment": "real", "confirmation": LIVE_CONFIRMATION}, **CONFIGURED
        )
    assert "kill switch" in str(exc.value)


def test_back_to_demo_always_allowed_without_confirmation(svc, repo):
    # Stato di partenza real (scritto direttamente, come dopo un go-live)
    repo.set_setting("environment", "real")
    effective = svc.update({"environment": "demo"})
    assert effective["environment"] == "demo"


def test_audit_recorded_on_change(svc, repo):
    svc.update({"timezone": "UTC"}, source="test")
    entries = [e for e in repo.settings_audit() if e.key == "timezone"]
    assert entries
    assert entries[0].new_value == {"value": "UTC"}
    assert entries[0].source == "test"


# --- validazione valori ------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "paper"},
        {"schedule_utc": "25:99"},
        {"schedule_utc": "8:30"},
        {"timezone": "Marte/Olympus"},
        {"risk_limits": {}},
        {"weekdays_only": "sì"},
        {"unknown_key": 1},
    ],
)
def test_invalid_values_rejected(svc, changes):
    with pytest.raises(SettingsValidationError):
        svc.update(changes)
