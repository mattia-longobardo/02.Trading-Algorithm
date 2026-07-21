"""Caricamento configurazione da file YAML + env.

La precedenza runtime completa (app_settings DB > yaml > env) è composta in
services/app_settings.py; qui vivono solo i default da file, senza dipendenze
dal database così che risk/safety restino usabili anche a DB giù.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", Path(__file__).resolve().parents[2] / "config"))


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@dataclass(frozen=True)
class CircuitBreakerRules:
    max_daily_loss_pct: float = 2.0
    max_consecutive_losses: int = 4
    cooloff_hours: int = 24


@dataclass(frozen=True)
class RiskRules:
    max_position_pct_equity: float = 5.0
    max_total_exposure_pct: float = 60.0
    max_sector_exposure_pct: float = 20.0
    max_open_positions: int = 10
    max_orders_per_run: int = 3
    max_orders_per_day: int = 5
    min_cash_buffer_pct: float = 20.0
    allowed_asset_types: tuple[str, ...] = ("stock", "etf")
    circuit_breaker: CircuitBreakerRules = field(default_factory=CircuitBreakerRules)


def load_risk_rules() -> RiskRules:
    raw = _load_yaml("risk_rules.yaml")
    cb = raw.pop("circuit_breaker", {}) or {}
    known = {k: v for k, v in raw.items() if k in RiskRules.__dataclass_fields__}
    if "allowed_asset_types" in known:
        known["allowed_asset_types"] = tuple(known["allowed_asset_types"])
    return RiskRules(**known, circuit_breaker=CircuitBreakerRules(**cb))


def load_settings() -> dict[str, Any]:
    """Default da config/settings.yaml (senza sovrapposizioni DB)."""
    return _load_yaml("settings.yaml")


def load_risk_score_config() -> dict[str, Any]:
    return _load_yaml("risk_score.yaml")


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://bot:bot@localhost:5432/etoro_bot"
    )
