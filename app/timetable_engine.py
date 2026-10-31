"""Two-file Openclass timetable engine.

Master Data.xlsx  →  Students-Testng (identity) + Batch Allocation (subscriptions)
Time Table.xlsx   →  Sheet1 weekly lecture stream (Monday–Saturday)

Student views are the intersection of active batch subscriptions and timetable events.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from .config import ROOT
from .services.roster import (
    batches_compatible,
    extract_subject_and_batch,
    identity_keys,
    names_compatible,
    normalize_batch,
    subjects_compatible,
)

logger = logging.getLogger("openclass.timetable_engine")

STORE_PATH = ROOT / "data" / "timetable_engine.json"
TIMEZONE = ZoneInfo("Asia/Kolkata")
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]

TIME_RE = re.compile(
    r"^\s*(\d{1,2}(?:[:.]\d{2})?)\s*(?:-|–|to)\s*(\d{1,2}(?:[:.]\d{2})?)\s*$",
    re.IGNORECASE,
)
ENTRY_RE = re.compile(r"^\s*\d+\)\s*(.+?)\s*$")
BATCH_RE = re.compile(r"(?:-|–)?\s*(?:Batch|B)\s*(\d+)(?:\s*of\s*\d+)?\s*$", re.IGNORECASE)
ELECTIVE_HEADER_RE = re.compile(
    r"^(.*?)\s*[\(\[]\s*((?:batch\s*)?b?\s*\d+(?:\s*of\s*\d+)?)\s*[\)\]]\s*$",
    re.IGNORECASE,
)
ROLL_RE = re.compile(r"(imdr[\s._-]*\d{4,}[\s._-]*\d+)", re.IGNORECASE)

IDENTITY_HINTS = {
    "name", "student name", "full name", "student", "learner",
    "roll", "roll no", "roll number", "rollno", "id", "student id",
    "email", "e mail", "mail", "mailid", "mail id", "student email",
    "sr", "sr no", "s no", "serial",
}
STUDENT_SHEET_HINTS = ("student", "testng", "roster", "learners")
ALLOCATION_SHEET_HINTS = ("allocation", "elective", "batch alloc")
SKIP_ELECTIVE_HEADERS = {
    "sr", "sr no", "serial", "gender", "program", "programme", "semester",
    "year", "status", "remarks", "phone", "mobile",
}


def _header_key(value) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value or "").strip())
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _compact(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def _clock(value: str) -> str:
    value = str(value or "").strip().replace(".", ":")
    return value if ":" in value else f"{value}:00"


def _is_active_mark(value) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) != 0.0
    text = str(value).strip().lower()
    if not text or text in {"-", "na", "n/a", "no", "n", "0", "0.0", "false", "none"}:
        return False
    return True


def _parse_elective_header(title: str) -> tuple[str, str]:
    text = str(title or "").strip()
    match = ELECTIVE_HEADER_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    match = re.match(
        r"^(.*?)\s*[-–]\s*((?:batch\s*)?b?\s*\d+(?:\s*of\s*\d+)?)\s*$",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return text, ""


def _empty_store() -> dict:
    return {
        "students": [],
        "subscriptions": [],
        "events": [],
        "master_filename": "",
        "timetable_filename": "",
        "updated_at": "",
    }


def load_store() -> dict:
    if not STORE_PATH.exists():
        return _empty_store()
    try:
        return {**_empty_store(), **json.loads(STORE_PATH.read_text())}
    except Exception as exc:
        logger.warning("Could not read timetable engine store: %s", exc)
        return _empty_store()


def save_store(store: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    store["updated_at"] = datetime.now(TIMEZONE).isoformat()
    STORE_PATH.write_text(json.dumps(store, indent=2, default=str))


def _excel_sheets(path) -> dict[str, pd.DataFrame]:
    book = pd.read_excel(path, sheet_name=None, header=None, dtype=object, engine="openpyxl")
    return {str(name): frame for name, frame in (book or {}).items()}


def _pick_sheet(sheets: dict[str, pd.DataFrame], hints: tuple[str, ...]) -> Optional[tuple[str, pd.DataFrame]]:
    for name, frame in sheets.items():
        title = name.lower()
        if any(hint in title for hint in hints):
            return name, frame
    return None


def _frame_as_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Promote the first non-empty row that looks like headers."""
    working = frame.copy()
    working = working.dropna(how="all").dropna(axis=1, how="all")
    if working.empty:
        return working
    header_idx = None
    for idx, row in working.iterrows():
        values = [_header_key(v) for v in row.tolist() if str(v or "").strip()]
        if any(key in {"name", "roll no", "rollno", "mailid", "mail id", "email"} for key in values):
            header_idx = idx
            break
        if len(values) >= 3:
            header_idx = idx
            break
    if header_idx is None:
        header_idx = working.index[0]
    headers = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(working.loc[header_idx].tolist())]
    data = working.loc[working.index > header_idx].copy()
    data.columns = headers
    return data.reset_index(drop=True)


def parse_students_testng(path) -> list[dict]:
    sheets = _excel_sheets(path)
    picked = _pick_sheet(sheets, STUDENT_SHEET_HINTS)
    if not picked:
        return []
    table = _frame_as_table(picked[1])
    if table.empty:
        return []
    colmap = {_header_key(col): col for col in table.columns}
    name_col = next((colmap[k] for k in colmap if k in {"name", "student name", "full name", "student"}), None)
    roll_col = next((colmap[k] for k in colmap if "roll" in k or k in {"student id", "prn"}), None)
    mail_col = next((colmap[k] for k in colmap if k in {"email", "mail", "mailid", "mail id", "student email"} or "mail" in k), None)
    people = []
    for _, row in table.iterrows():
        name = str(row.get(name_col) or "").strip() if name_col else ""
        roll = str(row.get(roll_col) or "").strip() if roll_col else ""
        email = str(row.get(mail_col) or "").strip().lower() if mail_col else ""
        if email in {"nan", "none"}:
            email = ""
        if roll in {"nan", "none"}:
            roll = ""
        if name in {"nan", "none"}:
            name = ""
        match = ROLL_RE.search(f"{roll} {email} {name}")
        if match:
            roll = re.sub(r"\s+", "", match.group(1))
        if not name and not email and not roll:
            continue
        people.append({
            "name": name,
            "roll_no": roll,
            "email": email,
            "sheet": picked[0],
        })
    return people


def parse_batch_allocation_matrix(path) -> list[dict]:
    """Wide matrix: one row per roll, elective columns marked 1.0 / Batch 2 / B3 of 3."""
    sheets = _excel_sheets(path)
    picked = _pick_sheet(sheets, ALLOCATION_SHEET_HINTS)
    if not picked:
        return []
    table = _frame_as_table(picked[1])
    if table.empty:
        return []
    colmap = {_header_key(col): col for col in table.columns}
    roll_col = next((colmap[k] for k in colmap if "roll" in k or k in {"student id", "id"}), None)
    name_col = next((colmap[k] for k in colmap if k in {"name", "student name", "full name", "student"}), None)
    mail_col = next((colmap[k] for k in colmap if "mail" in k or k == "email"), None)
    elective_cols = [
        col for col in table.columns
        if _header_key(col) not in IDENTITY_HINTS and _header_key(col) not in SKIP_ELECTIVE_HEADERS
    ]
    people = []
    for _, row in table.iterrows():
        roll = str(row.get(roll_col) or "").strip() if roll_col else ""
        name = str(row.get(name_col) or "").strip() if name_col else ""
        email = str(row.get(mail_col) or "").strip().lower() if mail_col else ""
        if roll in {"nan", "none"}:
            roll = ""
        if name in {"nan", "none"}:
            name = ""
        if email in {"nan", "none"}:
            email = ""
        match = ROLL_RE.search(f"{roll} {email} {name}")
        if match:
            roll = re.sub(r"\s+", "", match.group(1))
        if not roll and not name and not email:
            continue
        enrollments = []
        for col in elective_cols:
            value = row.get(col)
            if not _is_active_mark(value):
                continue
            header_subject, header_batch = _parse_elective_header(str(col))
            cell_text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()
            cell_subject, cell_batch = _parse_elective_header(cell_text)
            if cell_batch and cell_subject and cell_subject.lower() not in {"1", "1.0", "yes", "true"}:
                subject, batch = cell_subject, cell_batch
            elif re.search(r"batch|\bb\s*\d+\b", cell_text, re.IGNORECASE) and cell_text.lower() not in {"1", "1.0"}:
                subject, batch = header_subject or str(col), cell_text
            else:
                subject, batch = header_subject or str(col), header_batch
            subject, batch = extract_subject_and_batch(subject, batch)
            if not subject:
                continue
            enrollments.append({
                "subject": subject,
                "batch": batch,
                "column": str(col),
                "raw": str(col),
            })
        people.append({
            "name": name,
            "roll_no": roll,
            "email": email,
            "sheet": picked[0],
            "enrollments": enrollments,
        })
    return people


def parse_time_table_sheet(path, sheet_name: str = "Sheet1") -> list[dict]:
    sheets = _excel_sheets(path)
    frame = None
    for name, candidate in sheets.items():
        if name.strip().lower() == sheet_name.strip().lower():
            frame = candidate
            break
    if frame is None:
        for name, candidate in sheets.items():
            if not any(hint in name.lower() for hint in STUDENT_SHEET_HINTS + ALLOCATION_SHEET_HINTS):
                frame = candidate
                break
    if frame is None:
        return []

    header_row = None
    day_cols: dict[str, int] = {}
    for idx, row in frame.iterrows():
        values = [str(v or "").strip() for v in row.tolist()]
        found = {}
        for col_i, value in enumerate(values):
            key = value.lower()
            for day in DAYS:
                if key.startswith(day.lower()):
                    found[day] = col_i
        if len(found) >= 3:
            header_row = idx
            day_cols = found
            break
    if not day_cols:
        # Fallback: first two columns are time, next six are Mon–Sat.
        day_cols = {day: i + 1 for i, day in enumerate(DAYS)}

    events = []
    start_at = header_row + 1 if header_row is not None else 0
    for _, row in frame.iloc[start_at:].iterrows():
        values = list(row.tolist())
        time_idx = None
        match = None
        scan_limit = min(3, len(values))
        for i in range(scan_limit):
            raw = str(values[i] or "").replace(".", ":").strip()
            match = TIME_RE.match(raw)
            if match:
                time_idx = i
                break
        if match is None or time_idx is None:
            continue
        start_time = _clock(match.group(1).replace(".", ":"))
        end_time = _clock(match.group(2).replace(".", ":"))
        for day, col_i in day_cols.items():
            if col_i >= len(values):
                continue
            cell = values[col_i]
            if cell is None or (isinstance(cell, float) and pd.isna(cell)):
                continue
            lines = [line.strip() for line in str(cell).splitlines() if line.strip()]
            if not lines:
                continue
            parsed_any = False
            for i, line in enumerate(lines):
                entry = ENTRY_RE.match(line)
                if not entry:
                    continue
                parsed_any = True
                course = entry.group(1)
                batch_match = BATCH_RE.search(course)
                faculty = lines[i + 1] if i + 1 < len(lines) and not ENTRY_RE.match(lines[i + 1]) else None
                subject = BATCH_RE.sub("", course).strip()
                batch = f"Batch {batch_match.group(1)}" if batch_match is not None else None
                subject, batch = extract_subject_and_batch(subject, batch)
                events.append({
                    "weekday": day,
                    "start_time": start_time,
                    "end_time": end_time,
                    "subject": subject,
                    "batch": batch,
                    "faculty_name": faculty,
                    "raw": line,
                })
            if parsed_any:
                continue
            joined = " | ".join(lines)
            subject, batch = extract_subject_and_batch(joined, None)
            if not subject:
                continue
            faculty = lines[1] if len(lines) > 1 else None
            events.append({
                "weekday": day,
                "start_time": start_time,
                "end_time": end_time,
                "subject": subject,
                "batch": batch,
                "faculty_name": faculty,
                "raw": joined,
            })
    return events


def ingest_master_data(path, filename: str = "") -> dict:
    identities = parse_students_testng(path)
    allocations = parse_batch_allocation_matrix(path)
    by_key: dict[str, dict] = {}

    def upsert(person: dict):
        roll = str(person.get("roll_no") or "").strip()
        email = str(person.get("email") or "").strip().lower()
        name = str(person.get("name") or "").strip()
        key = _compact(roll) or email or name.lower()
        if not key:
            return
        entry = by_key.setdefault(key, {
            "name": name,
            "roll_no": roll,
            "email": email,
            "enrollments": [],
        })
        if name and not entry.get("name"):
            entry["name"] = name
        if email and not entry.get("email"):
            entry["email"] = email
        if roll and not entry.get("roll_no"):
            entry["roll_no"] = roll
        for item in person.get("enrollments") or []:
            marker = (str(item.get("subject") or "").lower(), normalize_batch(item.get("batch")))
            existing = {(str(e.get("subject") or "").lower(), normalize_batch(e.get("batch"))) for e in entry["enrollments"]}
            if marker in existing or not item.get("subject"):
                continue
            entry["enrollments"].append(item)

    for person in identities:
        upsert(person)
    for person in allocations:
        upsert(person)

    if not by_key:
        return load_store()

    students = []
    subscriptions = []
    for entry in by_key.values():
        students.append({
            "name": entry.get("name") or "",
            "roll_no": entry.get("roll_no") or "",
            "email": entry.get("email") or "",
        })
        for item in entry.get("enrollments") or []:
            subscriptions.append({
                "roll_no": entry.get("roll_no") or "",
                "email": entry.get("email") or "",
                "name": entry.get("name") or "",
                "subject": item.get("subject"),
                "batch": item.get("batch"),
                "column": item.get("column") or item.get("raw") or "",
                "raw": item.get("raw") or item.get("subject"),
            })

    store = load_store()
    store["students"] = students
    store["subscriptions"] = subscriptions
    store["master_filename"] = filename or store.get("master_filename") or Path(str(path)).name
    save_store(store)
    logger.info(
        "Master data ingested: %s students, %s subscriptions from %s",
        len(students),
        len(subscriptions),
        store["master_filename"],
    )
    return store


def ingest_time_table(path, filename: str = "") -> dict:
    events = parse_time_table_sheet(path, "Sheet1")
    if not events:
        return load_store()
    store = load_store()
    store["events"] = events
    store["timetable_filename"] = filename or store.get("timetable_filename") or Path(str(path)).name
    save_store(store)
    logger.info("Time table ingested: %s events from %s", len(events), store["timetable_filename"])
    return store


def _student_keys(student: dict) -> set[str]:
    return identity_keys(student.get("roll_no"), student.get("email"), student.get("name"), student.get("id"))


def resolve_student(roll_no: Optional[str] = None, email: Optional[str] = None, name: Optional[str] = None) -> Optional[dict]:
    store = load_store()
    students = store.get("students") or []
    lookup = identity_keys(roll_no, email, name)
    email_n = (email or "").strip().lower()
    roll_n = str(roll_no or "").strip()
    for student in students:
        keys = _student_keys(student)
        if lookup & keys:
            return student
        if email_n and str(student.get("email") or "").strip().lower() == email_n:
            return student
        if roll_n and _compact(student.get("roll_no")) == _compact(roll_n):
            return student
    if name:
        for student in students:
            if names_compatible(name, student.get("name")):
                return student
    return None


def subscriptions_for_student(roll_no: Optional[str] = None, email: Optional[str] = None, name: Optional[str] = None) -> list[dict]:
    store = load_store()
    student = resolve_student(roll_no=roll_no, email=email, name=name)
    keys = identity_keys(
        roll_no,
        email,
        name,
        (student or {}).get("roll_no"),
        (student or {}).get("email"),
        (student or {}).get("name"),
    )
    compact_keys = {_compact(k) for k in keys if _compact(k)}
    matched = []
    seen = set()
    for item in store.get("subscriptions") or []:
        token = str(item.get("roll_no") or item.get("email") or item.get("name") or "")
        if token not in keys and token.lower() not in keys and _compact(token) not in compact_keys:
            if student and not (
                names_compatible(student.get("name"), item.get("name"))
                or _compact(student.get("roll_no")) == _compact(item.get("roll_no"))
                or (student.get("email") and student.get("email") == (item.get("email") or "").lower())
            ):
                continue
            if not student:
                continue
        subject, batch = extract_subject_and_batch(item.get("subject"), item.get("batch"))
        if not subject or not batch:
            continue
        marker = (subject.lower(), normalize_batch(batch))
        if marker in seen:
            continue
        seen.add(marker)
        matched.append({
            "subject": subject,
            "batch": batch,
            "raw": item.get("raw") or item.get("column") or subject,
            "roll_no": item.get("roll_no") or (student or {}).get("roll_no"),
            "email": item.get("email") or (student or {}).get("email"),
        })
    return matched


def subscriptions_for_user(user: Optional[dict]) -> list[dict]:
    if not user:
        return []
    return subscriptions_for_student(
        roll_no=str(user.get("roll_no") or user.get("roster_id") or ""),
        email=user.get("email"),
        name=user.get("name"),
    )


def event_matches_subscriptions(event: dict, subscriptions: list[dict]) -> bool:
    if not subscriptions:
        return False
    session_subject, session_batch = extract_subject_and_batch(event.get("subject"), event.get("batch"))
    session_label = f"{event.get('subject') or ''} {event.get('batch') or ''}"
    for item in subscriptions:
        if not subjects_compatible(session_subject, item.get("subject")) and not subjects_compatible(session_label, item.get("subject")):
            continue
        if str(session_batch or "").strip().lower() in {"all batches", "all", "*"}:
            return True
        if item.get("batch") and (
            batches_compatible(session_batch, item.get("batch"))
            or batches_compatible(session_label, item.get("batch"))
        ):
            return True
    return False


def filter_events(events: list[dict], subscriptions: list[dict]) -> list[dict]:
    return [dict(event) for event in events if event_matches_subscriptions(event, subscriptions)]


def enrolled_week(roll_no: Optional[str] = None, email: Optional[str] = None, name: Optional[str] = None, events: Optional[list[dict]] = None) -> list[dict]:
    """Your Enrolled Week: Monday–Saturday minus unallocated / phantom batches."""
    subscriptions = subscriptions_for_student(roll_no=roll_no, email=email, name=name)
    source = events if events is not None else (load_store().get("events") or [])
    matched = filter_events(source, subscriptions)
    weekday_rank = {day.lower(): i for i, day in enumerate(DAYS)}
    matched.sort(key=lambda item: (
        weekday_rank.get(str(item.get("weekday") or "").lower(), 99),
        str(item.get("start_time") or ""),
    ))
    return matched


def todays_rhythm(roll_no: Optional[str] = None, email: Optional[str] = None, name: Optional[str] = None, events: Optional[list[dict]] = None, weekday: Optional[str] = None) -> list[dict]:
    """Today's Rhythm: only lectures matching this student's active batch subscriptions."""
    today = (weekday or datetime.now(TIMEZONE).strftime("%A")).strip().lower()
    week = enrolled_week(roll_no=roll_no, email=email, name=name, events=events)
    return [item for item in week if str(item.get("weekday") or "").strip().lower() == today]


def roster_people_for_persist() -> list[dict]:
    store = load_store()
    by_key: dict[str, dict] = {}
    for student in store.get("students") or []:
        key = _compact(student.get("roll_no")) or (student.get("email") or "").lower() or (student.get("name") or "").lower()
        if not key:
            continue
        by_key[key] = {
            "name": student.get("name") or "",
            "email": student.get("email") or "",
            "roll_no": student.get("roll_no") or "",
            "enrollments": [],
        }
    for item in store.get("subscriptions") or []:
        key = _compact(item.get("roll_no")) or (item.get("email") or "").lower() or (item.get("name") or "").lower()
        entry = by_key.setdefault(key, {
            "name": item.get("name") or "",
            "email": item.get("email") or "",
            "roll_no": item.get("roll_no") or "",
            "enrollments": [],
        })
        entry["enrollments"].append({
            "subject": item.get("subject"),
            "batch": item.get("batch"),
        })
    return list(by_key.values())
