"""Read-side helpers for prompts stored in the application database.

The GPT client uses :func:`get_prompt` to look up the active version of a
prompt at call time. If anything goes wrong (DB missing, key not seeded, value
unexpectedly empty), we transparently fall back to the hard-coded default
shipped with the code so the trading bot never loses a prompt.
"""

from __future__ import annotations

import logging
from typing import Any

from core.app_db import app_fetch_all, app_fetch_one
from core.utils import isoformat_utc, utc_now

logger = logging.getLogger(__name__).getChild("prompt_store")


def get_prompt(db_path: str, key: str, default: str) -> str:
    """Return the active prompt content for ``key``, falling back to ``default``."""

    try:
        row = app_fetch_one(
            db_path,
            """
            SELECT pv.content
            FROM prompts p
            JOIN prompt_versions pv ON pv.id = p.current_version_id
            WHERE p.key = ?
            """,
            (key,),
        )
    except Exception:
        logger.exception("Failed to read prompt %s from app DB; using fallback", key)
        return default
    if not row:
        return default
    content = row.get("content")
    if not isinstance(content, str) or not content.strip():
        return default
    return content


def list_prompts(db_path: str) -> list[dict[str, Any]]:
    return app_fetch_all(
        db_path,
        """
        SELECT p.key, p.current_version_id, p.updated_at, pv.content
        FROM prompts p
        JOIN prompt_versions pv ON pv.id = p.current_version_id
        ORDER BY p.key
        """,
    )


def get_prompt_with_version(db_path: str, key: str) -> dict[str, Any] | None:
    return app_fetch_one(
        db_path,
        """
        SELECT p.key, p.current_version_id AS version_id, p.updated_at, pv.content
        FROM prompts p
        JOIN prompt_versions pv ON pv.id = p.current_version_id
        WHERE p.key = ?
        """,
        (key,),
    )


def list_versions(db_path: str, key: str) -> list[dict[str, Any]]:
    return app_fetch_all(
        db_path,
        """
        SELECT pv.id, pv.prompt_key, pv.content, pv.comment, pv.saved_by, pv.saved_at,
               u.username AS saved_by_username,
               (CASE WHEN p.current_version_id = pv.id THEN 1 ELSE 0 END) AS is_current
        FROM prompt_versions pv
        LEFT JOIN users u ON u.id = pv.saved_by
        LEFT JOIN prompts p ON p.key = pv.prompt_key
        WHERE pv.prompt_key = ?
        ORDER BY pv.saved_at DESC, pv.id DESC
        """,
        (key,),
    )


def save_new_version(
    db_path: str,
    *,
    key: str,
    content: str,
    comment: str | None,
    saved_by: int | None,
) -> dict[str, Any]:
    if not content or not content.strip():
        raise ValueError("Prompt content cannot be empty")
    from core.app_db import app_cursor

    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        # Ensure the parent `prompts` row exists before inserting the
        # version (FK on `prompt_versions.prompt_key`). Use a placeholder
        # current_version_id=0 on first insert; the UPDATE below sets it
        # to the actual version id once the row is in place.
        cursor.execute(
            """
            INSERT INTO prompts (key, current_version_id, updated_at)
            VALUES (?, 0, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, now),
        )
        cursor.execute(
            """
            INSERT INTO prompt_versions (prompt_key, content, comment, saved_by, saved_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (key, content, comment, saved_by, now),
        )
        version_id = cursor.lastrowid
        cursor.execute(
            "UPDATE prompts SET current_version_id = ?, updated_at = ? WHERE key = ?",
            (version_id, now, key),
        )
    version = app_fetch_one(
        db_path, "SELECT * FROM prompt_versions WHERE id = ?", (version_id,)
    )
    assert version is not None
    return version


def rollback_to_version(db_path: str, *, key: str, version_id: int) -> dict[str, Any]:
    from core.app_db import app_cursor

    version = app_fetch_one(
        db_path,
        "SELECT * FROM prompt_versions WHERE id = ? AND prompt_key = ?",
        (version_id, key),
    )
    if not version:
        raise ValueError("Version not found for this prompt")
    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            "UPDATE prompts SET current_version_id = ?, updated_at = ? WHERE key = ?",
            (version_id, now, key),
        )
    return version
