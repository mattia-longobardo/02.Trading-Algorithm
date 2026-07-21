"""Assemblaggio delle dipendenze reali ed esecuzione della pipeline.

Una sola run alla volta: un lock a livello modulo espone is_run_in_progress()
e fa sollevare RunInProgressError a chi tenta una run concorrente.
"""

from __future__ import annotations

import threading
import uuid
from functools import partial
from typing import Any

from etoro_bot.config import load_settings
from etoro_bot.graph.deps import GraphDeps
from etoro_bot.graph.graph import build_graph, make_checkpointer
from etoro_bot.safety.circuit_breaker import CircuitBreaker

_run_lock = threading.Lock()

# Chiavi runtime sovrascrivibili da app_settings (§10): DB > yaml > default.
_RUNTIME_KEYS = ("environment", "schedule_utc", "timezone", "weekdays_only", "risk_limits")


class RunInProgressError(RuntimeError):
    """Una run è già in corso: le run non sono concorrenti (409 lato API)."""


def is_run_in_progress() -> bool:
    return _run_lock.locked()


def _effective_settings(repo) -> dict[str, Any]:
    """Precedenza: app_settings (DB) > config/settings.yaml.

    Usa services.app_settings.AppSettingsService se esiste; altrimenti overlay
    diretto delle chiavi runtime da repo. Con DB giù restano i default yaml
    (fail-safe: sarà comunque reconcile a fermare la run se il DB serve).
    """
    settings = load_settings()
    try:
        from etoro_bot.services.app_settings import AppSettingsService

        service = AppSettingsService(repo)
        for method_name in ("effective_settings", "get_effective", "effective"):
            method = getattr(service, method_name, None)
            if callable(method):
                merged = method()
                if isinstance(merged, dict):
                    return {**settings, **merged}
    except Exception:
        pass
    for key in _RUNTIME_KEYS:
        try:
            value = repo.get_setting(key)
        except Exception:
            break
        if value is not None:
            settings[key] = value
    return settings


def _default_deps(user_id: str = "system") -> GraphDeps:
    from etoro_bot.db.repo import Repository, make_engine, make_session_factory
    from etoro_bot.etoro.client import EtoroClient

    repo = Repository(make_session_factory(make_engine()))
    settings = _effective_settings(repo)
    from etoro_bot.services.user_credentials import get_user_keys

    # Le run schedulate non hanno un'identità HTTP: usano le chiavi dell'unico
    # account che le ha configurate (app mono-utente).
    if user_id == "system":
        user_id = repo.owner_user_id() or user_id
    keys = get_user_keys(repo, user_id)
    api_key, user_key = keys.etoro_api_key, keys.etoro_user_key
    if not api_key or not user_key:
        raise RuntimeError(
            "chiavi eToro non configurate: inseriscile in Impostazioni → Chiavi API personali"
        )
    client = EtoroClient(
        api_key=api_key,
        user_key=user_key,
        environment=str(settings.get("environment", "demo")),
    )
    from etoro_bot.services.app_settings import effective_risk_rules

    rules = effective_risk_rules(repo)
    llm = None
    if keys.openai_api_key:
        import openai

        from etoro_bot.graph.llm import call_llm

        llm = partial(call_llm, client=openai.OpenAI(api_key=keys.openai_api_key))
    return GraphDeps(
        client=client,
        repo=repo,
        rules=rules,
        settings=settings,
        breaker=CircuitBreaker(rules.circuit_breaker),
        llm=llm,
    )


def run_pipeline(deps: GraphDeps | None = None, *, user_id: str = "system") -> dict:
    """Esegue una run completa della pipeline e ritorna il summary della run.

    Gli ordini approvati dal risk gate vengono sempre eseguiti per davvero,
    nell'ambiente scelto dalle impostazioni (demo o real): non esiste più una
    modalità dry-run. Con deps iniettate (test) il checkpointer non viene creato.
    """
    if not _run_lock.acquire(blocking=False):
        raise RunInProgressError("una run è già in corso")
    try:
        use_checkpointer = deps is None
        if deps is None:
            deps = _default_deps(user_id)
        settings = deps.settings
        environment = str(settings.get("environment", "demo"))

        run_id = str(uuid.uuid4())
        deps.repo.create_run(run_id, environment=environment)
        graph = build_graph(deps, checkpointer=make_checkpointer() if use_checkpointer else None)
        graph.invoke(
            {"run_id": run_id, "environment": environment},
            config={"configurable": {"thread_id": run_id}},
        )
        run = deps.repo.get_run(run_id)
        summary = dict(run.summary_json or {}) if run is not None else {}
        summary.setdefault("run_id", run_id)
        summary.setdefault("environment", environment)
        return summary
    finally:
        _run_lock.release()
