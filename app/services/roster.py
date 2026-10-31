"""Persistent timetable roster helpers: faculty–subject–batch mappings."""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from ..db import connect

logger = logging.getLogger("openclass.roster")


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
    cleaned = str(raw).strip()
    cleaned = re.sub(
        r"\s*[\(\[]\s*(?:batch\s*)?b?\s*\d+(?:\s*of\s*\d+)?\s*[\)\]]\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s*[-–]\s*(?:batch\s*)?b?\s*\d+(?:\s*of\s*\d+)?\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+(CS-\d[A-Z0-9]*|[A-Z]{2,3}-\d[A-Z0-9]*)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" -")
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
    role = str((user or {}).get("role") or "").upper()
    if role == "STUDENT":
        return student_subscribed_subjects(user)
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


def is_all_batches(batch: Optional[str]) -> bool:
    return _norm(batch) in {"", "all batches", "all", "*"}


def extract_subject_and_batch(subject: Optional[str], batch: Optional[str] = None) -> tuple[str, str]:
    raw_subject = str(subject or "").strip()
    raw_batch = str(batch or "").strip()
    cleaned = _clean_subject_name(raw_subject)
    if raw_batch:
        return cleaned, raw_batch
    of_match = re.search(r"\b(?:batch\s*|b\s*)?(\d+)\s*(?:of|/)\s*\d+\b", raw_subject, re.IGNORECASE)
    if of_match:
        return cleaned, f"Batch {of_match.group(1)}"
    numbered = _BATCH_NUMBER_RE.search(raw_subject)
    if numbered:
        return cleaned, f"Batch {numbered.group(1)}"
    return cleaned, ""


_BATCH_NUMBER_RE = re.compile(
    r"\b(?:batch[\s\-]*|b[\s\-]*)(\d+)\b",
    re.IGNORECASE,
)
_PROGRAM_SECTION_RE = re.compile(
    r"\b([a-z]{1,6})[\s\-]*(\d+)([a-z])?\b",
    re.IGNORECASE,
)


def normalize_batch(batch_name: Optional[str]) -> str:
    """Canonical batch id: All Batches → ALL, Batch 2 / B2 / Batch-2 / B1 of 3 → B2/B1."""
    if is_all_batches(batch_name):
        return "ALL"
    text = _norm(batch_name)
    if not text:
        return ""
    of_match = re.search(r"\b(?:batch\s*|b\s*)?(\d+)\s*(?:of|/)\s*\d+\b", text)
    if of_match:
        return f"B{of_match.group(1)}"
    numbered = _BATCH_NUMBER_RE.search(text)
    if numbered:
        return f"B{numbered.group(1)}"
    program = _PROGRAM_SECTION_RE.search(text)
    if program:
        return f"B{program.group(2)}"
    compact = re.sub(r"[^a-z0-9]+", "", text)
    compact_match = re.fullmatch(r"(?:batch|b)?(\d+)", compact)
    if compact_match:
        return f"B{compact_match.group(1)}"
    return compact or text


def preferred_batch_label(batch_name: Optional[str]) -> str:
    canon = normalize_batch(batch_name)
    if canon == "ALL":
        return "All Batches"
    if re.fullmatch(r"B\d+", canon or ""):
        return f"Batch {canon[1:]}"
    return str(batch_name or "").strip()


def batch_tokens(value: Optional[str]) -> set[str]:
    """Canonical tokens for Batch 3 / B3 / B3 of 3 / Data Visualization (B3 of 3)."""
    text = _norm(value)
    tokens: set[str] = set()
    if not text:
        return tokens
    canon = normalize_batch(value)
    if canon and canon != "ALL":
        tokens.add(canon)
        if re.fullmatch(r"B\d+", canon):
            tokens.add(canon[1:])
            tokens.add(f"batch {canon[1:]}")
            tokens.add(f"b{canon[1:]}")
    for match in re.findall(r"\b(?:batch[\s\-]*|b[\s\-]*)(\d+)\b", text):
        tokens.add(f"B{match}")
        tokens.add(match)
        tokens.add(f"batch {match}")
        tokens.add(f"b{match}")
    of_match = re.findall(r"\b(\d+)\s*(?:of|/)\s*\d+\b", text)
    for match in of_match:
        tokens.add(f"B{match}")
        tokens.add(match)
    return {t for t in tokens if t}


def batches_compatible(left: Optional[str], right: Optional[str]) -> bool:
    """True when two batch labels refer to the same cohort, including B3 vs Batch 3."""
    explicit_all = {"all batches", "all", "*"}
    if _norm(left) in explicit_all or _norm(right) in explicit_all:
        return True
    a = normalize_batch(left)
    b = normalize_batch(right)
    if a == "ALL" or b == "ALL":
        return True
    if a and b and a == b:
        return True
    left_tokens = batch_tokens(left)
    right_tokens = batch_tokens(right)
    return bool(left_tokens and right_tokens and (left_tokens & right_tokens))


def subjects_compatible(left: Optional[str], right: Optional[str]) -> bool:
    a, b = _clean_subject_name(left).lower(), _clean_subject_name(right).lower()
    if not a or not b:
        return False
    return a == b or a in b or b in a


def loose_identity_match(left: Optional[str], right: Optional[str]) -> bool:
    a, b = _norm(left), _norm(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a in b or b in a):
        return True
    local_a = a.split("@")[0]
    local_b = b.split("@")[0]
    if local_a and local_b and local_a == local_b:
        return True
    return names_compatible(left, right)


def _allocation_matches_target(item: dict, subject: Optional[str], batch_id: Optional[str]) -> bool:
    combined = f"{item.get('subject') or ''} {item.get('batch') or ''}".strip()
    if subject:
        if not (
            subjects_compatible(subject, item.get("subject"))
            or subjects_compatible(subject, combined)
        ):
            return False
    if is_all_batches(batch_id):
        return True
    return (
        batches_compatible(batch_id, item.get("batch"))
        or batches_compatible(batch_id, item.get("subject"))
        or batches_compatible(batch_id, combined)
    )


def list_recipient_students(subject: Optional[str] = None, batch_id: Optional[str] = None) -> list[dict]:
    """Collect student emails from ingested Students-Testng / Batch Allocation rows."""
    with connect() as db:
        students = [
            dict(r)
            for r in db.execute(
                "SELECT id, name, email, batch_id FROM students WHERE active = 1"
            ).fetchall()
        ]
        allocations = [
            dict(r)
            for r in db.execute("SELECT roll_no, subject, batch FROM batch_allocations").fetchall()
        ]
        user_rows = [
            dict(r)
            for r in db.execute(
                "SELECT email, name, batch_id FROM users WHERE UPPER(IFNULL(role, '')) = 'STUDENT'"
            ).fetchall()
        ]

    recipients: list[dict] = []
    seen: set[str] = set()

    def add_recipient(email: Optional[str], name: Optional[str] = None, sid: Optional[str] = None):
        value = (email or "").strip().lower()
        if not value or "@" not in value or value in seen:
            return
        seen.add(value)
        recipients.append({"id": sid, "name": name or "", "email": value})

    def email_for_key(raw: Optional[str], fallback_name: Optional[str] = None) -> tuple[Optional[str], Optional[str], Optional[str]]:
        for student in students:
            if (
                loose_identity_match(raw, student.get("id"))
                or loose_identity_match(raw, student.get("email"))
                or loose_identity_match(raw, student.get("name"))
                or loose_identity_match(fallback_name, student.get("name"))
            ):
                email = (student.get("email") or "").strip()
                if email:
                    return email, student.get("name"), student.get("id")
        for row in user_rows:
            if loose_identity_match(raw, row.get("email")) or loose_identity_match(raw, row.get("name")) or loose_identity_match(fallback_name, row.get("name")):
                email = (row.get("email") or "").strip()
                if email:
                    return email, row.get("name"), None
        text = str(raw or "").strip()
        if "@" in text:
            return text, fallback_name, text
        return None, fallback_name, None

    matched_any_allocation = False
    for item in allocations:
        if not _allocation_matches_target(item, subject, batch_id):
            continue
        matched_any_allocation = True
        email, name, sid = email_for_key(item.get("roll_no"))
        add_recipient(email, name, sid)

    if not matched_any_allocation or is_all_batches(batch_id):
        for student in students:
            if subject and matched_any_allocation:
                continue
            if is_all_batches(batch_id) or batches_compatible(batch_id, student.get("batch_id")):
                add_recipient(student.get("email"), student.get("name"), student.get("id"))

    if not recipients:
        logger.warning(
            "Assignment recipient lookup returned 0 emails subject=%r batch=%r students=%s allocation_keys=%s",
            subject,
            batch_id,
            [s.get("email") or s.get("id") for s in students[:40]],
            [str(r.get("roll_no")) for r in allocations[:40]],
        )
        print(
            f"Assignment recipient lookup returned 0 emails subject={subject!r} batch={batch_id!r}",
            flush=True,
        )
    return recipients


def list_batches_for_subject(user: Optional[dict], subject: str) -> list[str]:
    subject = _clean_subject_name(subject)
    if not subject:
        return []
    generalist = is_generalist_user(user)
    role = str((user or {}).get("role") or "").upper()
    keys = faculty_match_keys(user)
    with connect() as db:
        mapped = db.execute("SELECT COUNT(*) AS n FROM faculty_subject_batches").fetchone()["n"]
        if not mapped:
            rebuild_faculty_subject_batches(db)
        params: list = [subject, f"%{subject}%"]
        sql = """SELECT DISTINCT batch FROM faculty_subject_batches
                 WHERE (subject = ? OR subject LIKE ?)"""
        if role == "FACULTY" and not generalist and keys:
            sql += " AND (" + " OR ".join(
                ["LOWER(TRIM(faculty_name)) = ? OR LOWER(TRIM(faculty_name)) LIKE ?"] * len(keys)
            ) + ")"
            for key in keys:
                params.extend([key, f"%{key}%"])
        sql += " ORDER BY batch COLLATE NOCASE"
        rows = db.execute(sql, params).fetchall()
        alloc_rows = db.execute(
            """SELECT DISTINCT batch FROM batch_allocations
               WHERE subject = ? OR subject LIKE ?""",
            (subject, f"%{subject}%"),
        ).fetchall()
        student_rows = db.execute(
            """SELECT DISTINCT batch_id AS batch FROM students
               WHERE active = 1 AND batch_id IS NOT NULL AND TRIM(batch_id) != ''"""
        ).fetchall()
    batches = []
    seen = set()

    def add_batch(raw: Optional[str]):
        batch = str(raw or "").strip()
        if not batch or is_all_batches(batch):
            return
        key = normalize_batch(batch)
        if not key or key in seen:
            return
        seen.add(key)
        batches.append(preferred_batch_label(batch))

    for row in rows:
        add_batch(dict(row).get("batch"))
    for row in alloc_rows:
        add_batch(dict(row).get("batch"))
    # Student cohort labels from the ingested roster so faculty can target live batches
    for row in student_rows:
        add_batch(dict(row).get("batch"))
    batches.sort(key=lambda item: item.lower())
    return ["All Batches"] + batches


def student_enrollments(user: Optional[dict]) -> list[dict]:
    """Exact subject+batch rows from the ingested student roster for this learner."""
    if not user:
        return []
    try:
        from ..timetable_engine import subscriptions_for_user
        engine_subs = subscriptions_for_user(user)
        if engine_subs:
            return engine_subs
    except Exception:
        pass
    email = (user.get("email") or "").strip().lower()
    roll = str(user.get("roll_no") or user.get("roster_id") or user.get("id") or "").strip()
    enrollments = []
    seen = set()
    with connect() as db:
        linked = find_ingested_student(
            db,
            email=email,
            name=user.get("name"),
            roll_no=roll,
            log_miss=False,
        )
        keys = identity_keys(
            email,
            user.get("name"),
            roll,
            (linked or {}).get("id"),
            (linked or {}).get("email"),
            (linked or {}).get("name"),
        )
        if not keys:
            return []
        compact_keys = {compact_identity(k) for k in keys if compact_identity(k)}
        rows = db.execute(
            "SELECT roll_no, subject, batch FROM batch_allocations WHERE TRIM(IFNULL(subject, '')) != ''"
        ).fetchall()
        matched_rows = []
        for row in rows:
            item = dict(row)
            roll_value = str(item.get("roll_no") or "")
            if roll_value in keys or roll_value.lower() in keys:
                matched_rows.append(item)
                continue
            if compact_identity(roll_value) in compact_keys:
                matched_rows.append(item)
                continue
            if loose_identity_match(email, roll_value) or loose_identity_match(user.get("name"), roll_value):
                matched_rows.append(item)
                continue
            if linked and (
                loose_identity_match(linked.get("id"), roll_value)
                or loose_identity_match(linked.get("email"), roll_value)
                or loose_identity_match(linked.get("name"), roll_value)
            ):
                matched_rows.append(item)
        if not linked and not matched_rows:
            _log_student_lookup_miss(email, roll, user.get("name"), db)
        if not matched_rows:
            alloc_keys = sorted({str(dict(r).get("roll_no") or "") for r in rows})[:80]
            message = (
                "Student allocation query returned 0 rows for "
                f"email={email!r} roll={roll!r} name={user.get('name')!r} "
                f"lookup_keys={sorted(list(keys))[:40]} available_allocation_keys={alloc_keys}"
            )
            print(message, flush=True)
            logger.warning(message)
        for item in matched_rows:
            subject, batch = extract_subject_and_batch(item.get("subject"), item.get("batch"))
            if not subject:
                continue
            marker = (subject.lower(), normalize_batch(batch) or "")
            if marker in seen:
                continue
            seen.add(marker)
            enrollments.append({"subject": subject, "batch": batch, "raw": item.get("subject")})
    return enrollments


def list_student_class_sessions(user: Optional[dict], sessions: Optional[list[dict]] = None) -> list[dict]:
    """Return timetable rows that match this student's elective/batch allocations."""
    enrollments = student_enrollments(user)
    with connect() as db:
        rows = sessions if sessions is not None else [dict(r) for r in db.execute(
            "SELECT * FROM class_sessions ORDER BY class_date, weekday, start_time"
        ).fetchall()]
        all_sessions = [dict(r) if not isinstance(r, dict) else r for r in rows]
    matched = [row for row in all_sessions if enrollment_matches_session(row, user, enrollments)]
    if not matched and enrollments:
        subjects = sorted({(s.get("subject"), s.get("batch")) for s in all_sessions})
        message = (
            "Student timetable matched 0 lectures despite enrollments "
            f"email={(user or {}).get('email')!r} roll={(user or {}).get('roll_no')!r} "
            f"enrollments={enrollments} available_sessions={list(subjects)[:40]}"
        )
        print(message, flush=True)
        logger.warning(message)
    return matched


def student_subscribed_subjects(user: Optional[dict]) -> list[str]:
    seen = set()
    subjects = []
    for item in student_enrollments(user):
        name = item.get("subject") or ""
        key = name.lower()
        if name and key not in seen:
            seen.add(key)
            subjects.append(name)
    return subjects


def enrollment_matches_session(session: dict, user: Optional[dict], enrollments: Optional[list[dict]] = None) -> bool:
    enrollments = enrollments if enrollments is not None else student_enrollments(user)
    if not enrollments:
        return False
    session_subject, session_batch = extract_subject_and_batch(session.get("subject"), session.get("batch"))
    session_label = f"{session.get('subject') or ''} {session.get('batch') or ''}"
    for item in enrollments:
        enroll_subject, enroll_batch = extract_subject_and_batch(item.get("subject"), item.get("batch") or item.get("raw"))
        if not enroll_subject:
            continue
        if not subjects_compatible(session_subject, enroll_subject) and not subjects_compatible(session_label, enroll_subject):
            continue
        if _norm(session_batch) in {"all batches", "all", "*"}:
            return True
        if not session_batch or not enroll_batch:
            return True
        if batches_compatible(session_batch, enroll_batch) or batches_compatible(session_label, enroll_batch):
            return True
    return False


def session_visible_to_user(session: dict, user: Optional[dict], enrollments: Optional[list[dict]] = None) -> bool:
    if not user:
        return True
    role = str(user.get("role") or "").upper()
    if is_generalist_user(user) or role in {"ADMIN", "GENERALIST", "TEST"}:
        return True
    if role == "STUDENT":
        return enrollment_matches_session(session, user, enrollments)
    if role == "FACULTY":
        keys = faculty_match_keys(user)
        faculty_name = _norm(session.get("faculty_name"))
        if any(key in faculty_name or faculty_name == key for key in keys):
            return True
        allowed = {s.lower() for s in list_subjects_for_user(user)}
        return _clean_subject_name(session.get("subject")).lower() in allowed
    return True


def assignment_visible_to_student(assignment: dict, user: Optional[dict]) -> bool:
    if not user:
        return True
    enrollments = student_enrollments(user)
    subject = assignment.get("subject")
    batch = assignment.get("batch_id") or user.get("batch_id")
    if enrollments:
        return any(
            (not subject or subjects_compatible(subject, item.get("subject")) or subjects_compatible(subject, item.get("raw")))
            and (
                is_all_batches(batch)
                or not str(item.get("batch") or "").strip()
                or batches_compatible(batch, item.get("batch"))
                or batches_compatible(batch, item.get("raw"))
            )
            for item in enrollments
        )
    return False


def note_visible_to_student(note: dict, user: Optional[dict]) -> bool:
    if not user:
        return True
    enrollments = student_enrollments(user)
    if not enrollments:
        return False
    return any(
        subjects_compatible(note.get("subject"), item.get("subject"))
        and (
            is_all_batches(note.get("specialization"))
            or batches_compatible(note.get("specialization"), item.get("batch") or user.get("batch_id"))
        )
        for item in enrollments
    )


def listed_roster_batches() -> list[dict]:
    with connect() as db:
        mapped = db.execute("SELECT COUNT(*) AS n FROM faculty_subject_batches").fetchone()["n"]
        if not mapped:
            rebuild_faculty_subject_batches(db)
        student_rows = db.execute(
            """SELECT batch_id as name, count(*) as learner_count
               FROM students
               WHERE active = 1 AND batch_id IS NOT NULL AND TRIM(batch_id) != ''
               GROUP BY batch_id"""
        ).fetchall()
        roster_rows = db.execute(
            """SELECT batch, GROUP_CONCAT(DISTINCT subject) AS subjects, COUNT(*) AS slots
               FROM faculty_subject_batches
               GROUP BY batch"""
        ).fetchall()
    by_name: dict[str, dict] = {}
    for row in student_rows:
        item = dict(row)
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = normalize_batch(name) or name.lower()
        entry = by_name.setdefault(
            key,
            {"name": preferred_batch_label(name), "learner_count": 0, "subject": ""},
        )
        entry["learner_count"] = (entry.get("learner_count") or 0) + (item.get("learner_count") or 0)
    for row in roster_rows:
        item = dict(row)
        name = str(item.get("batch") or "").strip()
        if not name or is_all_batches(name):
            continue
        key = normalize_batch(name) or name.lower()
        entry = by_name.setdefault(
            key,
            {"name": preferred_batch_label(name), "learner_count": 0, "subject": ""},
        )
        subjects = item.get("subjects") or entry.get("subject") or ""
        entry["subject"] = subjects
    return sorted(by_name.values(), key=lambda item: str(item["name"]).lower())


ROLL_TOKEN = re.compile(r"(imdr[\s._-]*\d{4,}[\s._-]*\d+)", re.IGNORECASE)


def _person_name_key(value: Optional[str]) -> str:
    tokens = re.findall(r"[a-z0-9]+", _norm(value))
    return " ".join(sorted(tokens))


def _name_tokens(value: Optional[str]) -> list[str]:
    skip = {"mr", "ms", "mrs", "miss", "dr", "prof"}
    return [t for t in re.findall(r"[a-z]+", _norm(value)) if t not in skip and len(t) > 1]


def names_compatible(left: Optional[str], right: Optional[str]) -> bool:
    a = _name_tokens(left)
    b = _name_tokens(right)
    if not a or not b:
        return False
    sa, sb = set(a), set(b)
    if sa == sb or sa <= sb or sb <= sa:
        return True
    return a[-1] == b[-1] and (a[0] == b[0] or a[0][0] == b[0][0])


def compact_identity(value: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").strip().lower())


def extract_roll_token(value: Optional[str]) -> str:
    text = str(value or "").strip()
    match = ROLL_TOKEN.search(text)
    if match:
        return re.sub(r"[^A-Z0-9]", "", match.group(1).upper())
    compact = compact_identity(text)
    if compact.startswith("imdr") and len(compact) >= 10:
        return compact.upper()
    return ""


def identity_keys(*values: Optional[str]) -> set[str]:
    keys: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if not text or text.lower() in {"none", "null"}:
            continue
        keys.add(text)
        keys.add(text.lower())
        local = text.split("@")[0].strip()
        if local:
            keys.add(local)
            keys.add(local.lower())
        compact = compact_identity(text)
        if compact:
            keys.add(compact)
            dm = re.search(r"(dm\d{5,})", compact)
            if dm:
                keys.add(dm.group(1))
            digits = re.sub(r"\D", "", compact)
            if len(digits) >= 6:
                keys.add(digits)
                keys.add(digits[-7:])
        roll = extract_roll_token(text)
        if roll:
            keys.add(roll)
            keys.add(roll.lower())
            if len(roll) > 4:
                keys.add(f"{roll[:-3]}-{roll[-3:]}")
    return {k for k in keys if k and len(k) > 1}


def _row_identity_keys(row: dict) -> set[str]:
    return identity_keys(row.get("id"), row.get("email"), row.get("name"), row.get("roll_no"))


def _log_student_lookup_miss(email: Optional[str], roll: Optional[str], name: Optional[str], db) -> None:
    students = [dict(r) for r in db.execute("SELECT id, email, name FROM students WHERE active = 1").fetchall()]
    alloc_keys = [
        str(r["roll_no"])
        for r in db.execute("SELECT DISTINCT roll_no FROM batch_allocations LIMIT 80").fetchall()
    ]
    message = (
        "Student lookup returned 0 rows for "
        f"email={email!r} roll={roll!r} name={name!r}. "
        f"Available student ids={[s.get('id') for s in students[:50]]} "
        f"emails={[s.get('email') for s in students[:50]]} "
        f"allocation_keys={alloc_keys}"
    )
    print(message, flush=True)
    logger.warning(message)


def find_ingested_student(
    db,
    email: Optional[str] = None,
    name: Optional[str] = None,
    roll_no: Optional[str] = None,
    log_miss: bool = False,
) -> Optional[dict]:
    lookup_keys = identity_keys(email, name, roll_no)
    email_n = (email or "").strip().lower()
    email_local = email_n.split("@")[0] if email_n else ""
    roll = str(roll_no or "").strip()
    rows = [dict(r) for r in db.execute("SELECT * FROM students WHERE active = 1").fetchall()]

    for item in rows:
        item_email = str(item.get("email") or "").strip().lower()
        if email_n and item_email == email_n:
            return item
        if email_n and item_email and len(email_n) >= 6 and (email_n in item_email or item_email in email_n):
            return item
        if email_n and loose_identity_match(email_n, item.get("name")):
            return item
    for item in rows:
        item_email = str(item.get("email") or "").strip().lower()
        item_local = item_email.split("@")[0] if item_email else ""
        if email_local and item_local and email_local == item_local:
            return item
    for item in rows:
        row_keys = _row_identity_keys(item)
        if lookup_keys & row_keys:
            return item
        if roll and str(item.get("id") or "").strip().lower() == roll.lower():
            return item
    if name:
        for item in rows:
            if names_compatible(name, item.get("name")) or loose_identity_match(name, item.get("name")):
                return item
            if loose_identity_match(name, item.get("email")) or loose_identity_match(name, item.get("id")):
                return item
    if log_miss:
        _log_student_lookup_miss(email, roll, name, db)
    return None


def persist_student_roster(db, students: list[dict], stamp: Optional[str] = None) -> int:
    """Upsert ingested Students-Testng (or similar) rows into students + users."""
    from ..db import now as db_now

    stamp = stamp or db_now()
    saved = 0
    for item in students:
        name = str(item.get("name") or "").strip()
        email = str(item.get("email") or "").strip().lower()
        batch = str(item.get("batch") or "").strip()
        phone = str(item.get("phone") or "").strip()
        roll = str(item.get("roll_no") or "").strip()
        if not name and not email and not roll:
            continue
        if not name:
            name = (email.split("@")[0] if email else roll).replace(".", " ").replace("-", " ").title()
        existing = find_ingested_student(db, email=email, name=name, roll_no=roll)
        student_id = (existing or {}).get("id") or roll or email or f"std-{name.lower().replace(' ', '-')}"
        if existing:
            db.execute(
                """UPDATE students
                   SET name = ?, email = COALESCE(NULLIF(?, ''), email), phone = COALESCE(NULLIF(?, ''), phone),
                       batch_id = COALESCE(NULLIF(?, ''), batch_id), active = 1, updated_at = ?
                   WHERE id = ?""",
                (name, email, phone, batch, stamp, existing["id"]),
            )
            student_id = existing["id"]
        else:
            db.execute(
                """INSERT INTO students (id, name, email, phone, batch_id, active, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     name=excluded.name,
                     email=COALESCE(excluded.email, students.email),
                     phone=COALESCE(excluded.phone, students.phone),
                     batch_id=COALESCE(excluded.batch_id, students.batch_id),
                     updated_at=excluded.updated_at""",
                (student_id, name, email or None, phone or None, batch or None, stamp),
            )
        if email:
            db.execute(
                """INSERT INTO users (email, name, role, phone, batch_id, active, created_at, updated_at)
                   VALUES (?, ?, 'STUDENT', ?, ?, 1, ?, ?)
                   ON CONFLICT(email) DO UPDATE SET
                     name=excluded.name,
                     role='STUDENT',
                     batch_id=CASE WHEN excluded.batch_id IS NOT NULL AND excluded.batch_id != '' THEN excluded.batch_id ELSE users.batch_id END,
                     phone=COALESCE(excluded.phone, users.phone),
                     updated_at=excluded.updated_at""",
                (email, name, phone or None, batch or None, stamp, stamp),
            )
        enrollments = list(item.get("enrollments") or [])
        if item.get("subject"):
            enrollments.append({"subject": item.get("subject"), "batch": batch})
        for enrollment in enrollments:
            raw_subject = enrollment.get("subject") if isinstance(enrollment, dict) else enrollment
            raw_batch = enrollment.get("batch") if isinstance(enrollment, dict) else batch
            subject, enroll_batch = extract_subject_and_batch(raw_subject, raw_batch)
            if not enroll_batch:
                enroll_batch = str(raw_batch or batch or "").strip()
            if not subject:
                continue
            if not enroll_batch:
                enroll_batch = str(raw_subject or "").strip()
            if not subject:
                continue
            for key in identity_keys(student_id, email, roll, name):
                if not key or len(key) < 3:
                    continue
                db.execute(
                    """INSERT OR IGNORE INTO batch_allocations (roll_no, subject, batch)
                       VALUES (?, ?, ?)""",
                    (key, subject, enroll_batch),
                )
        saved += 1
    return saved


def apply_ingested_student_profile(db, user: dict) -> dict:
    """Copy batch/name from the ingested student roster onto the signed-in user."""
    if not user or str(user.get("role") or "").upper() != "STUDENT":
        return user
    match = find_ingested_student(
        db,
        email=user.get("email"),
        name=user.get("name"),
        roll_no=str(user.get("roll_no") or user.get("id") or ""),
        log_miss=False,
    )
    try:
        from ..timetable_engine import resolve_student
        engine = resolve_student(
            roll_no=str(user.get("roll_no") or (match or {}).get("id") or ""),
            email=user.get("email"),
            name=user.get("name"),
        )
        if engine:
            if engine.get("name"):
                user["name"] = engine["name"]
            if engine.get("roll_no"):
                user["roll_no"] = engine["roll_no"]
                user["roster_id"] = engine["roll_no"]
            if not match:
                match = {
                    "id": engine.get("roll_no"),
                    "name": engine.get("name"),
                    "email": engine.get("email"),
                    "batch_id": user.get("batch_id"),
                }
    except Exception:
        pass
    if not match:
        return user
    batch = (match.get("batch_id") or "").strip()
    name = (match.get("name") or "").strip()
    user["roll_no"] = match.get("id")
    user["roster_id"] = match.get("id")
    changed = False
    if batch and batch != (user.get("batch_id") or ""):
        user["batch_id"] = batch
        changed = True
    if name and name != (user.get("name") or ""):
        user["name"] = name
        changed = True
    if changed and user.get("id") is not None:
        from ..db import now as db_now

        stamp = db_now()
        db.execute(
            "UPDATE users SET batch_id = COALESCE(?, batch_id), name = COALESCE(?, name), updated_at = ? WHERE id = ?",
            (batch or None, name or None, stamp, user["id"]),
        )
    return user


def faculty_for_student(user: Optional[dict]) -> list[dict]:
    """Faculty who teach this student's enrolled subject+batch slots."""
    if not user:
        return []
    with connect() as db:
        sessions = [dict(r) for r in db.execute("SELECT subject, batch, faculty_name FROM class_sessions").fetchall()]
        faculty_rows = [dict(r) for r in db.execute("SELECT * FROM faculty WHERE active = 1").fetchall()]
    names = []
    seen = set()
    enrollments = student_enrollments(user)
    for session in sessions:
        if not enrollment_matches_session(session, user, enrollments):
            continue
        raw = str(session.get("faculty_name") or "").strip()
        if not raw:
            continue
        key = _norm(_strip_titles(raw))
        if key in seen:
            continue
        seen.add(key)
        names.append(raw)
    people = []
    for name in names:
        key = _norm(_strip_titles(name))
        match = next(
            (
                row
                for row in faculty_rows
                if _norm(_strip_titles(row.get("full_name") or "")) == key
                or key in _norm(row.get("full_name") or "")
            ),
            None,
        )
        people.append(
            {
                "id": (match or {}).get("id"),
                "full_name": (match or {}).get("full_name") or name,
                "email": (match or {}).get("email") or "",
                "subjects": sorted(
                    {
                        _clean_subject_name(s.get("subject"))
                        for s in sessions
                        if _norm(s.get("faculty_name")) == _norm(name) and enrollment_matches_session(s, user, enrollments)
                    }
                ),
            }
        )
    people.sort(key=lambda item: str(item.get("full_name") or "").lower())
    return people


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
