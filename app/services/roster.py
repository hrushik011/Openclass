"""Persistent timetable roster helpers: faculty–subject–batch mappings."""

from __future__ import annotations

import os
import re
from typing import Optional

from ..db import connect


GENERALIST_NAMES = {"priya menon"}
GENERALIST_EMAILS = {
    "priya.menon@college.edu",
    *(
        email.strip().lower()
        for email in os.getenv("GENERALIST_EMAILS", "").split(",")
        if email.strip()
    ),
}


def _clean_subject_name(raw: Optional[str]) -> str:
    if not raw:
        return ""
    cleaned = re.sub(
        r"\s+(CS-\d[A-Z0-9]*|[A-Z]{2,3}-\d[A-Z0-9]*)$",
        "",
        str(raw).strip(),
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or str(raw).strip()


def _norm(value: Optional[str]) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _strip_titles(name: str) -> str:
    return re.sub(r"^(dr\.?|prof\.?|professor|mr\.?|ms\.?|mrs\.?)\s+", "", name, flags=re.IGNORECASE).strip()


def is_generalist_user(user: Optional[dict]) -> bool:
    if not user:
        return False
    role = str(user.get("role") or "").upper()
    if role in {"ADMIN", "GENERALIST", "TEST"}:
        return True
    name = _norm(user.get("name"))
    email = _norm(user.get("email"))
    if name in GENERALIST_NAMES or _strip_titles(name).lower() in GENERALIST_NAMES:
        return True
    if email in GENERALIST_EMAILS:
        return True
    return False


def faculty_match_keys(user: Optional[dict]) -> list[str]:
    if not user:
        return []
    keys = set()
    name = _strip_titles(_norm(user.get("name")))
    if name:
        keys.add(name)
        keys.add(name.replace(".", ""))
    email = _norm(user.get("email"))
    if email:
        keys.add(email)
        local = email.split("@")[0]
        local_name = local.replace(".", " ").replace("_", " ").replace("-", " ")
        keys.add(_norm(local_name))
    return [k for k in keys if k]


def rebuild_faculty_subject_batches(db=None) -> int:
    """Rebuild mapping table from persisted class_sessions (survives logins)."""
    owns = db is None
    if owns:
        ctx = connect()
        db = ctx.__enter__()
    try:
        db.execute(
            """CREATE TABLE IF NOT EXISTS faculty_subject_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                faculty_name TEXT NOT NULL,
                subject TEXT NOT NULL,
                batch TEXT NOT NULL,
                UNIQUE(faculty_name, subject, batch)
            )"""
        )
        db.execute("DELETE FROM faculty_subject_batches")
        rows = db.execute(
            """SELECT faculty_name, subject, batch FROM class_sessions
               WHERE subject IS NOT NULL AND TRIM(subject) != ''"""
        ).fetchall()
        count = 0
        for row in rows:
            item = dict(row)
            subject = _clean_subject_name(item.get("subject"))
            batch = str(item.get("batch") or "").strip() or "All Batches"
            faculty_name = str(item.get("faculty_name") or "").strip() or "Unassigned"
            if not subject:
                continue
            db.execute(
                """INSERT OR IGNORE INTO faculty_subject_batches (faculty_name, subject, batch)
                   VALUES (?, ?, ?)""",
                (faculty_name, subject, batch),
            )
            count += 1
        return count
    finally:
        if owns:
            ctx.__exit__(None, None, None)


def _session_exists(db, item) -> bool:
    row = db.execute(
        """SELECT id FROM class_sessions
           WHERE weekday = ?
             AND start_time = ?
             AND subject = ?
             AND IFNULL(batch, '') = IFNULL(?, '')
             AND IFNULL(faculty_name, '') = IFNULL(?, '')
           LIMIT 1""",
        (
            item.weekday,
            item.start_time,
            item.subject,
            item.batch,
            item.faculty_name,
        ),
    ).fetchone()
    return bool(row)


def list_subjects_for_user(user: Optional[dict]) -> list[str]:
    generalist = is_generalist_user(user)
    keys = faculty_match_keys(user)
    with connect() as db:
        mapped = db.execute("SELECT COUNT(*) AS n FROM faculty_subject_batches").fetchone()["n"]
        if not mapped:
            rebuild_faculty_subject_batches(db)
        if generalist:
            rows = db.execute(
                """SELECT DISTINCT subject FROM faculty_subject_batches
                   ORDER BY subject COLLATE NOCASE"""
            ).fetchall()
        elif not keys:
            rows = []
        else:
            placeholders = " OR ".join(
                ["LOWER(TRIM(faculty_name)) = ? OR LOWER(TRIM(faculty_name)) LIKE ?"] * len(keys)
            )
            params = []
            for key in keys:
                params.extend([key, f"%{key}%"])
            rows = db.execute(
                f"""SELECT DISTINCT subject FROM faculty_subject_batches
                    WHERE {placeholders}
                    ORDER BY subject COLLATE NOCASE""",
                params,
            ).fetchall()
    seen = set()
    subjects = []
    for row in rows:
        name = _clean_subject_name(dict(row).get("subject"))
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            subjects.append(name)
    return subjects


def list_batches_for_subject(user: Optional[dict], subject: str) -> list[str]:
    subject = _clean_subject_name(subject)
    if not subject:
        return ["All Batches"]
    generalist = is_generalist_user(user)
    keys = faculty_match_keys(user)
    with connect() as db:
        mapped = db.execute("SELECT COUNT(*) AS n FROM faculty_subject_batches").fetchone()["n"]
        if not mapped:
            rebuild_faculty_subject_batches(db)
        params: list = [subject, f"%{subject}%"]
        sql = """SELECT DISTINCT batch FROM faculty_subject_batches
                 WHERE (subject = ? OR subject LIKE ?)"""
        if not generalist and keys:
            sql += " AND (" + " OR ".join(
                ["LOWER(TRIM(faculty_name)) = ? OR LOWER(TRIM(faculty_name)) LIKE ?"] * len(keys)
            ) + ")"
            for key in keys:
                params.extend([key, f"%{key}%"])
        sql += " ORDER BY batch COLLATE NOCASE"
        rows = db.execute(sql, params).fetchall()
    batches = []
    seen = set()
    for row in rows:
        batch = str(dict(row).get("batch") or "").strip()
        if not batch or batch.lower() == "all batches":
            continue
        key = batch.lower()
        if key not in seen:
            seen.add(key)
            batches.append(batch)
    return ["All Batches"] + batches


def roster_status() -> dict:
    with connect() as db:
        rebuild_faculty_subject_batches(db)
        sessions = db.execute("SELECT COUNT(*) AS n FROM class_sessions").fetchone()["n"]
        latest = db.execute(
            "SELECT filename, uploaded_at FROM timetables ORDER BY id DESC LIMIT 1"
        ).fetchone()
        subjects = db.execute("SELECT COUNT(DISTINCT subject) AS n FROM faculty_subject_batches").fetchone()["n"]
    return {
        "ingested": sessions > 0,
        "session_count": sessions,
        "subject_count": subjects,
        "filename": dict(latest).get("filename") if latest else None,
        "uploaded_at": dict(latest).get("uploaded_at") if latest else None,
    }
