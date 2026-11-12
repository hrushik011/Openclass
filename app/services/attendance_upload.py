"""Parse faculty CSV/Excel attendance rolls and upsert subject-wise aggregates."""

from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from ..db import connect, now

_STUDENT_ALIASES = {
    "student_id",
    "student id",
    "studentid",
    "roll_no",
    "roll no",
    "roll",
    "id",
    "enrollment",
    "enrolment",
    "usn",
}
_SUBJECT_ALIASES = {
    "subject",
    "subject_code",
    "subject code",
    "course",
    "course code",
    "paper",
    "paper_code",
    "paper code",
}
_ATTENDED_ALIASES = {
    "classes_attended",
    "classes attended",
    "attended",
    "present",
    "classes_present",
    "classes present",
    "attendance",
}
_TOTAL_ALIASES = {
    "total_classes",
    "total classes",
    "total",
    "classes_held",
    "classes held",
    "held",
    "conducted",
    "max",
}
_BATCH_ALIASES = {"batch", "batch_id", "section", "division"}
_NAME_ALIASES = {"student_name", "student name", "name"}


def _norm_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s_\-]+", " ", text)
    return text


def _pick_column(columns: list[str], aliases: set[str]) -> Optional[str]:
    for col in columns:
        if _norm_header(col) in aliases:
            return col
    for col in columns:
        n = _norm_header(col)
        if any(a in n for a in aliases):
            return col
    return None


def _to_int(value: Any) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    if isinstance(value, str):
        value = value.strip().replace("%", "")
        if not value:
            return 0
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _load_frame(path: Path, raw_bytes: Optional[bytes] = None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        if raw_bytes is not None:
            return pd.read_excel(BytesIO(raw_bytes), engine="openpyxl")
        return pd.read_excel(path, engine="openpyxl")
    if suffix == ".csv":
        if raw_bytes is not None:
            return pd.read_csv(BytesIO(raw_bytes))
        return pd.read_csv(path)
    raise ValueError("Upload a .csv or .xlsx attendance file")


def parse_attendance_upload(path: Path, raw_bytes: Optional[bytes] = None) -> list[dict]:
    df = _load_frame(path, raw_bytes=raw_bytes)
    if df.empty:
        return []
    df.columns = [str(c).strip() for c in df.columns]
    cols = list(df.columns)
    col_sid = _pick_column(cols, _STUDENT_ALIASES)
    col_subj = _pick_column(cols, _SUBJECT_ALIASES)
    col_att = _pick_column(cols, _ATTENDED_ALIASES)
    col_tot = _pick_column(cols, _TOTAL_ALIASES)
    if not col_sid or not col_subj or not col_att or not col_tot:
        raise ValueError(
            "Required columns missing. Include student ID, subject code, classes attended, and total classes held."
        )
    col_batch = _pick_column(cols, _BATCH_ALIASES)
    col_name = _pick_column(cols, _NAME_ALIASES)

    rows: list[dict] = []
    for _, row in df.iterrows():
        student_id = str(row.get(col_sid) or "").strip()
        subject = str(row.get(col_subj) or "").strip()
        if not student_id or not subject or student_id.lower() in {"nan", "none"}:
            continue
        attended = _to_int(row.get(col_att))
        total = _to_int(row.get(col_tot))
        if total < attended:
            total = attended
        batch_id = str(row.get(col_batch) or "").strip() if col_batch else ""
        student_name = str(row.get(col_name) or "").strip() if col_name else ""
        rows.append(
            {
                "student_id": student_id,
                "subject": subject,
                "classes_attended": attended,
                "total_classes": total,
                "batch_id": batch_id,
                "student_name": student_name,
            }
        )
    return rows


def apply_attendance_rows(rows: list[dict], *, uploaded_by: str = "faculty") -> dict:
    stamp = now()
    updated = 0
    skipped = 0
    with connect() as db:
        for row in rows:
            sid = row["student_id"]
            subj = row["subject"]
            if not sid or not subj:
                skipped += 1
                continue
            student_row = db.execute(
                "SELECT id, name, batch_id FROM students WHERE id = ? OR email = ? LIMIT 1",
                (sid, sid),
            ).fetchone()
            canonical_id = sid
            student_name = row.get("student_name") or ""
            batch_id = row.get("batch_id") or ""
            if student_row:
                student_row = dict(student_row)
                canonical_id = str(student_row["id"])
                if not student_name:
                    student_name = student_row.get("name") or ""
                if not batch_id:
                    batch_id = student_row.get("batch_id") or ""

            db.execute(
                """INSERT INTO student_subject_attendance (
                       student_id, student_name, batch_id, subject,
                       classes_attended, total_classes, uploaded_by, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(student_id, subject) DO UPDATE SET
                       student_name = excluded.student_name,
                       batch_id = excluded.batch_id,
                       classes_attended = excluded.classes_attended,
                       total_classes = excluded.total_classes,
                       uploaded_by = excluded.uploaded_by,
                       updated_at = excluded.updated_at""",
                (
                    canonical_id,
                    student_name or f"Student {canonical_id}",
                    batch_id or "",
                    subj,
                    int(row["classes_attended"]),
                    int(row["total_classes"]),
                    uploaded_by,
                    stamp,
                ),
            )
            updated += 1
    return {"updated": updated, "skipped": skipped, "rows_parsed": len(rows)}


def fetch_subject_snapshots(db, student_ids: set[str]) -> list[dict]:
    if not student_ids:
        return []
    placeholders = ",".join("?" for _ in student_ids)
    rows = db.execute(
        f"SELECT * FROM student_subject_attendance WHERE student_id IN ({placeholders})",
        tuple(student_ids),
    ).fetchall()
    return [dict(r) for r in rows]
