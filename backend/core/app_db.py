"""SQLite schema and helpers for the application database.

This database is dedicated to the web app (auth, sessions, prompts, settings,
report metadata, audit log). It is intentionally separate from the trading
databases (`trades.sqlite`, `market_data.sqlite`) so a corruption or schema
change on the app side never threatens the trading state.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.utils import isoformat_utc, utc_now


APP_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    role          TEXT NOT NULL CHECK(role IN ('admin','user')),
    disabled      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id         TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    key                TEXT PRIMARY KEY,
    current_version_id INTEGER NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_key  TEXT NOT NULL REFERENCES prompts(key) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    comment     TEXT,
    saved_by    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    saved_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prompt_versions_key ON prompt_versions(prompt_key, saved_at DESC);

CREATE TABLE IF NOT EXISTS report_folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    parent_id  INTEGER REFERENCES report_folders(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT NOT NULL,
    type         TEXT NOT NULL CHECK(type IN ('weekly','quarterly','biannual','annual','other')),
    format       TEXT NOT NULL CHECK(format IN ('json','pdf')),
    size_bytes   INTEGER NOT NULL,
    generated_at TEXT NOT NULL,
    folder_id    INTEGER REFERENCES report_folders(id) ON DELETE SET NULL,
    tags         TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_filename ON reports(filename);

CREATE TABLE IF NOT EXISTS account_equity_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    equity      REAL NOT NULL,
    currency    TEXT NOT NULL DEFAULT 'USD',
    provider    TEXT NOT NULL DEFAULT 'alpaca'
);
CREATE INDEX IF NOT EXISTS idx_equity_snapshots_recorded ON account_equity_snapshots(recorded_at);
CREATE INDEX IF NOT EXISTS idx_equity_snapshots_provider ON account_equity_snapshots(provider, recorded_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_name  TEXT NOT NULL,
    entity      TEXT NOT NULL,
    entity_id   TEXT,
    action      TEXT NOT NULL,
    before_json TEXT,
    after_json  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_actor  ON audit_log(actor_id, created_at DESC);
"""


# -- low level connection helpers -------------------------------------------


def _connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(db_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA foreign_keys=ON;")
    return connection


@contextmanager
def app_cursor(db_path: str) -> Iterator[sqlite3.Cursor]:
    connection = _connect(db_path)
    cursor = connection.cursor()
    try:
        yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def app_fetch_all(db_path: str, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    connection = _connect(db_path)
    try:
        cursor = connection.execute(query, params)
        try:
            rows = cursor.fetchall()
        finally:
            cursor.close()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def app_fetch_one(db_path: str, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    connection = _connect(db_path)
    try:
        cursor = connection.execute(query, params)
        try:
            row = cursor.fetchone()
        finally:
            cursor.close()
    finally:
        connection.close()
    return dict(row) if row else None


# -- initialization & seeding -----------------------------------------------


def _ensure_equity_snapshot_columns(connection: sqlite3.Connection) -> None:
    """Backfill columns added after the initial schema (e.g. ``provider``)."""

    cursor = connection.execute("PRAGMA table_info(account_equity_snapshots)")
    try:
        existing = {row["name"] for row in cursor.fetchall()}
    finally:
        cursor.close()
    if "provider" not in existing:
        connection.execute(
            "ALTER TABLE account_equity_snapshots ADD COLUMN provider TEXT NOT NULL DEFAULT 'alpaca'"
        ).close()


def initialize_app_database(db_path: str) -> None:
    """Create all app tables if missing. Idempotent."""

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(db_path)
    try:
        connection.executescript(APP_SCHEMA)
        _ensure_equity_snapshot_columns(connection)
        connection.commit()
    finally:
        connection.close()


def seed_admin_user_if_missing(
    db_path: str,
    username: str,
    password: str,
    display_name: str,
) -> dict[str, Any] | None:
    """Insert the seed admin user from env if no user with that username exists.

    Returns the inserted row dict, or None if an admin already exists with that
    username (we never overwrite existing credentials — operators must rotate
    via the UI or a manual reset).
    """

    if not username or not password:
        return None

    # Local import to avoid a circular dependency at module import time.
    from core.auth import hash_password

    existing = app_fetch_one(db_path, "SELECT * FROM users WHERE username = ?", (username,))
    if existing:
        return None

    now = isoformat_utc(utc_now()) or ""
    password_hash = hash_password(password)
    with app_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, disabled, created_at, updated_at)
            VALUES (?, ?, ?, 'admin', 0, ?, ?)
            """,
            (username, password_hash, display_name or username, now, now),
        )
    return app_fetch_one(db_path, "SELECT * FROM users WHERE username = ?", (username,))


ALPACA_PROMPT_KEYS: tuple[str, ...] = (
    "new_signal",
    "batch_signals",
    "pending_review",
    "protection_review",
    "universe_dossier",
    "universe_shortlist",
    "universe_final",
    "universe_final_from_dossiers",
)

PROMPT_KEYS: tuple[str, ...] = ALPACA_PROMPT_KEYS


def seed_initial_prompt_versions(db_path: str, defaults: dict[str, str]) -> None:
    """Seed one initial version per prompt key from the hard-coded defaults.

    Only seeds keys that are missing from the prompts table; existing prompts
    and their version history are never touched.
    """

    now = isoformat_utc(utc_now()) or ""
    for key in PROMPT_KEYS:
        existing = app_fetch_one(db_path, "SELECT key FROM prompts WHERE key = ?", (key,))
        if existing:
            continue
        content = defaults.get(key)
        if content is None:
            continue
        # `prompt_versions.prompt_key` has a FK to `prompts.key`, so the
        # parent row must exist before we can insert a version. We insert
        # the prompts row first with a placeholder current_version_id (0),
        # then the version, and finally point current_version_id at it.
        with app_cursor(db_path) as cursor:
            cursor.execute(
                "INSERT INTO prompts (key, current_version_id, updated_at) VALUES (?, 0, ?)",
                (key, now),
            )
            cursor.execute(
                """
                INSERT INTO prompt_versions (prompt_key, content, comment, saved_by, saved_at)
                VALUES (?, ?, ?, NULL, ?)
                """,
                (key, content, "initial seed from hard-coded constants", now),
            )
            version_id = cursor.lastrowid
            cursor.execute(
                "UPDATE prompts SET current_version_id = ? WHERE key = ?",
                (version_id, key),
            )


# -- audit log helper -------------------------------------------------------


def write_audit_entry(
    db_path: str,
    *,
    actor_id: int | None,
    actor_name: str,
    entity: str,
    entity_id: str | int | None,
    action: str,
    before: Any = None,
    after: Any = None,
) -> None:
    """Record a single mutation in the audit log."""

    def _serialize(value: Any) -> str | None:
        if value is None:
            return None
        try:
            return json.dumps(value, ensure_ascii=True, default=str)
        except (TypeError, ValueError):
            return json.dumps({"_unserializable": str(value)})

    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO audit_log (actor_id, actor_name, entity, entity_id, action, before_json, after_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                actor_name or "unknown",
                entity,
                str(entity_id) if entity_id is not None else None,
                action,
                _serialize(before),
                _serialize(after),
                now,
            ),
        )


def read_setting(db_path: str, key: str) -> Any:
    row = app_fetch_one(db_path, "SELECT value FROM app_settings WHERE key = ?", (key,))
    if not row:
        return None
    raw = row["value"]
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def read_all_settings(db_path: str) -> dict[str, Any]:
    rows = app_fetch_all(db_path, "SELECT key, value FROM app_settings")
    out: dict[str, Any] = {}
    for row in rows:
        try:
            out[row["key"]] = json.loads(row["value"])
        except (TypeError, ValueError):
            out[row["key"]] = row["value"]
    return out


def write_setting(
    db_path: str,
    key: str,
    value: Any,
    *,
    updated_by: int | None,
) -> None:
    payload = json.dumps(value, ensure_ascii=True)
    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO app_settings (key, value, updated_at, updated_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (key, payload, now, updated_by),
        )


def resolve_app_db_path(env_value: str | None) -> str:
    """Same convention as the trading DBs — relative paths resolve to backend/."""

    from core.utils import resolve_runtime_path

    return resolve_runtime_path(env_value or os.path.join("data", "app.sqlite"))
