"""Index the report files in REPORT_DIR into the app database.

The actual files keep living on disk (per spec). This module only
maintains a `reports` row per file so the UI can search / tag / move
into virtual folders without touching the underlying filename.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from core.app_db import app_cursor, app_fetch_all, app_fetch_one
from core.utils import isoformat_utc, utc_now


_FILE_RE = re.compile(
    r"^(?P<type>weekly|quarterly|biannual|annual)_report_"
    r"(?P<stamp>[0-9A-Za-z_\-:]+?)\.(?P<ext>json|pdf)$"
)
_STAMP_FORMAT = "%Y%m%d_%H%M%S"


def _parse_filename_stamp(filename: str) -> datetime | None:
    """Recover the generation datetime encoded in the report filename."""

    match = _FILE_RE.match(filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("stamp"), _STAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        return None


def _period_year_month(filename: str, generated_at: str, rtype: str) -> tuple[int, int] | None:
    """Return (year, month) for the *period* the report covers.

    For weekly reports the period ≈ generation date, so year/month of the
    stamp work. For quarterly/biannual/annual reports the bot generates
    the file at the start of the next period (Jan 1 → previous year's Q4),
    so we step back one day to land in the correct period.
    """

    stamp = _parse_filename_stamp(filename)
    if stamp is None:
        try:
            stamp = datetime.fromisoformat((generated_at or "").replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            stamp = None
    if stamp is None:
        return None
    if rtype in {"quarterly", "biannual", "annual"}:
        stamp = stamp - timedelta(days=1)
    return stamp.year, stamp.month


def _system_folder_marker(year: int, month: int | None = None) -> str:
    """Tag stored in the folder's `tags` field — sentinel for auto-folders."""

    return f"__auto:{year:04d}" if month is None else f"__auto:{year:04d}-{month:02d}"


def _find_folder_by_marker(db_path: str, marker: str) -> dict[str, Any] | None:
    return app_fetch_one(
        db_path,
        "SELECT * FROM report_folders WHERE name LIKE ? OR name = ? LIMIT 1",
        (f"{marker.split(':', 1)[1]}%", marker.split(":", 1)[1]),
    )


def _ensure_year_folder(db_path: str, year: int) -> int:
    """Return id of the folder named after ``year``, creating it if missing."""

    name = f"{year:04d}"
    row = app_fetch_one(db_path, "SELECT id FROM report_folders WHERE name = ? AND parent_id IS NULL", (name,))
    if row:
        return int(row["id"])
    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO report_folders (name, parent_id, created_at, created_by)
            VALUES (?, NULL, ?, NULL)
            """,
            (name, now),
        )
        return int(cursor.lastrowid or 0)


def _ensure_month_folder(db_path: str, year: int, month: int) -> int:
    """Return id of the YYYY-MM folder under the year folder, creating both if needed."""

    parent_id = _ensure_year_folder(db_path, year)
    name = f"{year:04d}-{month:02d}"
    row = app_fetch_one(
        db_path,
        "SELECT id FROM report_folders WHERE name = ? AND parent_id = ?",
        (name, parent_id),
    )
    if row:
        return int(row["id"])
    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO report_folders (name, parent_id, created_at, created_by)
            VALUES (?, ?, ?, NULL)
            """,
            (name, parent_id, now),
        )
        return int(cursor.lastrowid or 0)


def _auto_folder_id_for(db_path: str, *, rtype: str, filename: str, generated_at: str) -> int | None:
    """Decide the auto-assigned folder id for a freshly-indexed report."""

    if rtype == "other":
        return None
    period = _period_year_month(filename, generated_at, rtype)
    if period is None:
        return None
    year, month = period
    if rtype == "weekly":
        return _ensure_month_folder(db_path, year, month)
    # quarterly / biannual / annual → land in the year folder directly.
    return _ensure_year_folder(db_path, year)


def _classify(filename: str) -> tuple[str, str]:
    match = _FILE_RE.match(filename)
    if match:
        return match.group("type"), match.group("ext")
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in {"json", "pdf"}:
        return "other", ext
    return "other", ext


def _generated_at(file_path: Path) -> str:
    try:
        ts = file_path.stat().st_mtime
    except OSError:
        ts = utc_now().timestamp()
    return isoformat_utc(datetime.fromtimestamp(ts, tz=UTC)) or ""


def sync_reports(db_path: str, report_dir: str | Path, logger: logging.Logger | None = None) -> int:
    """Walk ``report_dir`` and ensure every .json/.pdf file has a row.

    Returns the count of newly-inserted rows. Idempotent.
    """

    base = Path(report_dir)
    if not base.exists():
        return 0
    inserted = 0
    seen: set[str] = set()
    for entry in sorted(base.iterdir()):
        if not entry.is_file():
            continue
        ext = entry.suffix.lower().lstrip(".")
        if ext not in {"json", "pdf"}:
            continue
        filename = entry.name
        seen.add(filename)
        rtype, fmt = _classify(filename)
        try:
            size = entry.stat().st_size
        except OSError:
            size = 0
        existing = app_fetch_one(db_path, "SELECT id FROM reports WHERE filename = ?", (filename,))
        if existing:
            continue
        generated_at = _generated_at(entry)
        try:
            auto_folder_id = _auto_folder_id_for(
                db_path, rtype=rtype, filename=filename, generated_at=generated_at
            )
        except Exception:
            if logger:
                logger.exception("Auto-folder placement failed for %s", filename)
            auto_folder_id = None
        with app_cursor(db_path) as cursor:
            cursor.execute(
                """
                INSERT INTO reports (filename, type, format, size_bytes, generated_at, folder_id, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (filename, rtype, fmt, size, generated_at, auto_folder_id, json.dumps([])),
            )
        inserted += 1
        if logger:
            logger.debug(
                "Indexed report %s as type=%s format=%s folder_id=%s",
                filename,
                rtype,
                fmt,
                auto_folder_id,
            )
    return inserted


def reorganize_uncategorized(
    db_path: str, logger: logging.Logger | None = None
) -> int:
    """Auto-assign the year/month folder to any existing reports without one.

    Called once at startup so historical reports — indexed before the
    auto-folder feature shipped — get organized retroactively.
    """

    rows = app_fetch_all(
        db_path,
        "SELECT id, filename, type, generated_at FROM reports WHERE folder_id IS NULL",
    )
    moved = 0
    for row in rows:
        try:
            target = _auto_folder_id_for(
                db_path,
                rtype=str(row["type"]),
                filename=str(row["filename"]),
                generated_at=str(row.get("generated_at") or ""),
            )
        except Exception:
            if logger:
                logger.exception("Backfill folder failed for %s", row["filename"])
            continue
        if target is None:
            continue
        with app_cursor(db_path) as cursor:
            cursor.execute("UPDATE reports SET folder_id = ? WHERE id = ?", (target, row["id"]))
        moved += 1
    return moved


def list_reports(
    db_path: str,
    *,
    folder_id: int | None = None,
    rtype: str | None = None,
    fmt: str | None = None,
    q: str | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
) -> list[dict[str, Any]]:
    sql = ["SELECT * FROM reports WHERE 1=1"]
    params: list[Any] = []
    if folder_id is not None:
        if folder_id == 0:
            sql.append("AND folder_id IS NULL")
        else:
            sql.append("AND folder_id = ?")
            params.append(folder_id)
    if rtype:
        sql.append("AND type = ?")
        params.append(rtype)
    if fmt:
        sql.append("AND format = ?")
        params.append(fmt)
    if from_iso:
        sql.append("AND generated_at >= ?")
        params.append(from_iso)
    if to_iso:
        sql.append("AND generated_at < ?")
        params.append(to_iso)
    if q:
        sql.append("AND (filename LIKE ? OR tags LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like])
    sql.append("ORDER BY generated_at DESC, filename DESC")
    return app_fetch_all(db_path, " ".join(sql), tuple(params))


def get_report(db_path: str, report_id: int) -> dict[str, Any] | None:
    return app_fetch_one(db_path, "SELECT * FROM reports WHERE id = ?", (int(report_id),))


def update_report(
    db_path: str,
    report_id: int,
    *,
    folder_id: int | None = None,
    tags: list[str] | None = None,
    clear_folder: bool = False,
) -> dict[str, Any] | None:
    before = get_report(db_path, report_id)
    old_folder_id = _folder_id(before)
    fields: list[str] = []
    params: list[Any] = []
    if clear_folder:
        fields.append("folder_id = NULL")
    elif folder_id is not None:
        fields.append("folder_id = ?")
        params.append(folder_id)
    if tags is not None:
        fields.append("tags = ?")
        params.append(json.dumps(tags, ensure_ascii=True))
    if not fields:
        return before
    params.append(report_id)
    with app_cursor(db_path) as cursor:
        cursor.execute(f"UPDATE reports SET {', '.join(fields)} WHERE id = ?", tuple(params))
    after = get_report(db_path, report_id)
    new_folder_id = _folder_id(after)
    if old_folder_id is not None and old_folder_id != new_folder_id:
        prune_empty_folders(db_path, old_folder_id)
    return after


def _folder_id(row: dict[str, Any] | None) -> int | None:
    if not row or row.get("folder_id") is None:
        return None
    return int(row["folder_id"])


def prune_empty_folders(db_path: str, folder_id: int | None) -> list[dict[str, Any]]:
    """Delete an empty folder and keep walking upward while parents become empty."""

    deleted: list[dict[str, Any]] = []
    current_id = int(folder_id) if folder_id is not None else None
    while current_id is not None:
        folder = app_fetch_one(db_path, "SELECT * FROM report_folders WHERE id = ?", (current_id,))
        if not folder:
            break
        report_count = app_fetch_one(
            db_path,
            "SELECT COUNT(*) AS count FROM reports WHERE folder_id = ?",
            (current_id,),
        )
        child_count = app_fetch_one(
            db_path,
            "SELECT COUNT(*) AS count FROM report_folders WHERE parent_id = ?",
            (current_id,),
        )
        if int((report_count or {}).get("count") or 0) > 0:
            break
        if int((child_count or {}).get("count") or 0) > 0:
            break

        parent_id = folder.get("parent_id")
        with app_cursor(db_path) as cursor:
            cursor.execute("DELETE FROM report_folders WHERE id = ?", (current_id,))
        deleted.append(folder)
        current_id = int(parent_id) if parent_id is not None else None
    return deleted


def _report_path_candidate(report_dir: str | Path, filename: str) -> Path | None:
    base = Path(report_dir)
    candidate = base / filename
    # Reject path traversal before touching disk.
    try:
        candidate.resolve().relative_to(base.resolve())
    except ValueError:
        return None
    return candidate


def delete_report(db_path: str, report_dir: str | Path, report_id: int) -> dict[str, Any] | None:
    row = get_report(db_path, report_id)
    if not row:
        return None
    old_folder_id = _folder_id(row)

    path = _report_path_candidate(report_dir, str(row["filename"]))
    if path is None:
        raise ValueError("Unsafe report filename")

    try:
        path.unlink()
    except FileNotFoundError:
        pass

    with app_cursor(db_path) as cursor:
        cursor.execute("DELETE FROM reports WHERE id = ?", (int(report_id),))
    prune_empty_folders(db_path, old_folder_id)
    return row


def list_folders(db_path: str) -> list[dict[str, Any]]:
    return app_fetch_all(db_path, "SELECT * FROM report_folders ORDER BY name")


def create_folder(
    db_path: str, *, name: str, parent_id: int | None, created_by: int | None
) -> dict[str, Any]:
    if not name or not name.strip():
        raise ValueError("Folder name required")
    now = isoformat_utc(utc_now()) or ""
    with app_cursor(db_path) as cursor:
        cursor.execute(
            """
            INSERT INTO report_folders (name, parent_id, created_at, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (name.strip(), parent_id, now, created_by),
        )
        new_id = cursor.lastrowid
    folder = app_fetch_one(db_path, "SELECT * FROM report_folders WHERE id = ?", (new_id,))
    assert folder is not None
    return folder


def update_folder(
    db_path: str, folder_id: int, *, name: str | None = None, parent_id: int | None = None
) -> dict[str, Any] | None:
    fields: list[str] = []
    params: list[Any] = []
    if name is not None:
        if not name.strip():
            raise ValueError("Folder name cannot be empty")
        fields.append("name = ?")
        params.append(name.strip())
    if parent_id is not None:
        fields.append("parent_id = ?")
        params.append(parent_id if parent_id > 0 else None)
    if not fields:
        return app_fetch_one(db_path, "SELECT * FROM report_folders WHERE id = ?", (folder_id,))
    params.append(folder_id)
    with app_cursor(db_path) as cursor:
        cursor.execute(f"UPDATE report_folders SET {', '.join(fields)} WHERE id = ?", tuple(params))
    return app_fetch_one(db_path, "SELECT * FROM report_folders WHERE id = ?", (folder_id,))


def delete_folder(db_path: str, folder_id: int) -> None:
    with app_cursor(db_path) as cursor:
        # Reports inside it become uncategorised (FK ON DELETE SET NULL).
        cursor.execute("DELETE FROM report_folders WHERE id = ?", (folder_id,))


def search_reports_full_text(db_path: str, report_dir: str | Path, query: str) -> list[dict[str, Any]]:
    """Return reports whose JSON content contains the query string."""

    if not query or not query.strip():
        return []
    needle = query.strip().lower()
    base = Path(report_dir)
    rows = app_fetch_all(db_path, "SELECT * FROM reports WHERE format = 'json' ORDER BY generated_at DESC")
    matches: list[dict[str, Any]] = []
    for row in rows:
        path = base / row["filename"]
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if needle in content.lower():
            matches.append(row)
    return matches


def report_path_for(report_dir: str | Path, filename: str) -> Path | None:
    candidate = _report_path_candidate(report_dir, filename)
    if candidate is None:
        return None
    if not candidate.exists():
        return None
    return candidate
