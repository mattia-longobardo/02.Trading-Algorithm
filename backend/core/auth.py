"""Password hashing, session tokens, and current-user resolution."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import bcrypt

from core.app_db import app_cursor, app_fetch_one
from core.utils import isoformat_utc, parse_datetime, utc_now


SESSION_COOKIE_NAME = "trading_session"
SESSION_TTL_DAYS = 14


# -- password hashing -------------------------------------------------------


def hash_password(plain: str) -> str:
    if not plain:
        raise ValueError("Password cannot be empty")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# -- sessions ---------------------------------------------------------------


@dataclass(slots=True)
class AuthenticatedUser:
    id: int
    username: str
    display_name: str
    role: str
    disabled: bool
    session_id: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
        }


def _new_session_token() -> str:
    """Opaque high-entropy token. URL-safe, 32 random bytes ~= 43 characters."""

    return secrets.token_urlsafe(32)


def create_session(db_path: str, user_id: int, ttl_days: int = SESSION_TTL_DAYS) -> str:
    token = _new_session_token()
    now = utc_now()
    created_at = isoformat_utc(now) or ""
    expires_at = isoformat_utc(now + timedelta(days=ttl_days)) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            "INSERT INTO sessions (id, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, created_at, expires_at),
        )
    return token


def revoke_session(db_path: str, session_id: str) -> None:
    if not session_id:
        return
    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (now, session_id),
        )


def revoke_all_sessions_for_user(db_path: str, user_id: int) -> None:
    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (now, user_id),
        )


def resolve_session(db_path: str, session_id: str | None) -> AuthenticatedUser | None:
    """Return the user behind a session cookie, or None if invalid/expired/disabled."""

    if not session_id:
        return None
    row = app_fetch_one(
        db_path,
        """
        SELECT s.id AS session_id, s.expires_at, s.revoked_at,
               u.id AS user_id, u.username, u.display_name, u.role, u.disabled
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.id = ?
        """,
        (session_id,),
    )
    if not row:
        return None
    if row["revoked_at"]:
        return None
    expires_at = parse_datetime(row["expires_at"])
    if expires_at is None or expires_at <= utc_now():
        return None
    if int(row.get("disabled") or 0) == 1:
        return None
    return AuthenticatedUser(
        id=int(row["user_id"]),
        username=str(row["username"]),
        display_name=str(row["display_name"]),
        role=str(row["role"]),
        disabled=bool(row["disabled"]),
        session_id=str(row["session_id"]),
    )


# -- user CRUD --------------------------------------------------------------


def get_user_by_username(db_path: str, username: str) -> dict[str, Any] | None:
    if not username:
        return None
    return app_fetch_one(db_path, "SELECT * FROM users WHERE username = ?", (username,))


def get_user_by_id(db_path: str, user_id: int) -> dict[str, Any] | None:
    return app_fetch_one(db_path, "SELECT * FROM users WHERE id = ?", (user_id,))


def list_users(db_path: str) -> list[dict[str, Any]]:
    from core.app_db import app_fetch_all

    return app_fetch_all(
        db_path,
        "SELECT id, username, display_name, role, disabled, created_at, updated_at FROM users ORDER BY username",
    )


def create_user(
    db_path: str,
    *,
    username: str,
    password: str,
    display_name: str,
    role: str,
) -> dict[str, Any]:
    if role not in ("admin", "user"):
        raise ValueError("Invalid role")
    if not username:
        raise ValueError("Username required")
    if not password:
        raise ValueError("Password required")
    if get_user_by_username(db_path, username):
        raise ValueError("Username already exists")
    now = isoformat_utc(utc_now()) or ""
    pw_hash = hash_password(password)
    with app_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO users (username, password_hash, display_name, role, disabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (username, pw_hash, display_name or username, role, now, now),
        )
    user = get_user_by_username(db_path, username)
    assert user is not None
    return user


def update_user(
    db_path: str,
    user_id: int,
    *,
    display_name: str | None = None,
    role: str | None = None,
    disabled: bool | None = None,
) -> dict[str, Any]:
    fields: list[str] = []
    params: list[Any] = []
    if display_name is not None:
        fields.append("display_name = ?")
        params.append(display_name)
    if role is not None:
        if role not in ("admin", "user"):
            raise ValueError("Invalid role")
        fields.append("role = ?")
        params.append(role)
    if disabled is not None:
        fields.append("disabled = ?")
        params.append(1 if disabled else 0)
    if not fields:
        user = get_user_by_id(db_path, user_id)
        if not user:
            raise ValueError("User not found")
        return user
    fields.append("updated_at = ?")
    params.append(isoformat_utc(utc_now()) or "")
    params.append(user_id)
    with app_cursor(db_path) as cursor:
        cursor.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
    user = get_user_by_id(db_path, user_id)
    if not user:
        raise ValueError("User not found")
    if disabled:
        revoke_all_sessions_for_user(db_path, user_id)
    return user


def reset_user_password(db_path: str, user_id: int, new_password: str) -> None:
    if not new_password:
        raise ValueError("Password required")
    pw_hash = hash_password(new_password)
    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (pw_hash, now, user_id),
        )
    revoke_all_sessions_for_user(db_path, user_id)


def change_own_password(
    db_path: str,
    user_id: int,
    current_password: str,
    new_password: str,
) -> None:
    user = get_user_by_id(db_path, user_id)
    if not user:
        raise ValueError("User not found")
    if not verify_password(current_password, str(user["password_hash"])):
        raise ValueError("Current password is incorrect")
    reset_user_password(db_path, user_id, new_password)


def update_own_profile(
    db_path: str,
    user_id: int,
    *,
    current_password: str,
    new_username: str | None = None,
    new_display_name: str | None = None,
) -> dict[str, Any]:
    """Update the user's own ``username`` / ``display_name``.

    The current password is always required to authorize the change. The
    username, when changed, must be unique. Returns the updated row.
    """

    user = get_user_by_id(db_path, user_id)
    if not user:
        raise ValueError("User not found")
    if not verify_password(current_password, str(user["password_hash"])):
        raise ValueError("Current password is incorrect")

    fields: list[str] = []
    params: list[Any] = []

    if new_username is not None:
        candidate = new_username.strip()
        if not candidate:
            raise ValueError("Username cannot be empty")
        if candidate != user["username"]:
            existing = get_user_by_username(db_path, candidate)
            if existing and int(existing["id"]) != user_id:
                raise ValueError("Username already taken")
            fields.append("username = ?")
            params.append(candidate)

    if new_display_name is not None:
        candidate = new_display_name.strip()
        if not candidate:
            raise ValueError("Display name cannot be empty")
        if candidate != user["display_name"]:
            fields.append("display_name = ?")
            params.append(candidate)

    if not fields:
        return user

    fields.append("updated_at = ?")
    params.append(isoformat_utc(utc_now()) or "")
    params.append(user_id)
    with app_cursor(db_path) as cursor:
        cursor.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
            tuple(params),
        )
    updated = get_user_by_id(db_path, user_id)
    if not updated:
        raise ValueError("User vanished during update")
    return updated


def delete_user(db_path: str, user_id: int) -> None:
    """Delete a user, preserving historical audit/prompt rows.

    Several tables (`audit_log`, `app_settings`, `prompt_versions`,
    `report_folders`) reference `users.id` without an `ON DELETE`
    clause, so SQLite would otherwise reject the DELETE with a FK
    constraint violation as soon as the user has done anything that
    was recorded. We pre-null those references inside the same
    transaction, so:

      - login/logout audit rows survive (with `actor_id=NULL` but
        `actor_name` already snapshot at write time);
      - prompt versions saved by the user are kept, just no longer
        attributed;
      - settings overrides retain their value;
      - sessions cascade automatically thanks to the FK on
        `sessions.user_id`.
    """

    with app_cursor(db_path) as cursor:
        cursor.execute(
            "UPDATE audit_log SET actor_id = NULL WHERE actor_id = ?",
            (user_id,),
        )
        cursor.execute(
            "UPDATE app_settings SET updated_by = NULL WHERE updated_by = ?",
            (user_id,),
        )
        cursor.execute(
            "UPDATE prompt_versions SET saved_by = NULL WHERE saved_by = ?",
            (user_id,),
        )
        cursor.execute(
            "UPDATE report_folders SET created_by = NULL WHERE created_by = ?",
            (user_id,),
        )
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))


def authenticate(db_path: str, username: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_username(db_path, username)
    if not user:
        return None
    if int(user.get("disabled") or 0) == 1:
        return None
    if not verify_password(password, str(user["password_hash"])):
        return None
    return user
