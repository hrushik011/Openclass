import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from ..db import connect, now
from ..email import (
    assignment_notice_headers,
    build_email_tags,
    prefix_subject,
    send_platform_email,
)
from .platform_notifications import (
    build_assignment_reminder_html,
    live_class_email_bundle,
    recipients_for_session,
)
from .roster import list_recipient_students, normalize_time_label

logger = logging.getLogger("openclass.reminders")
TIMEZONE = ZoneInfo("Asia/Kolkata")

MILESTONE_CREATED = "created"
MILESTONE_MIDWAY = "midway"
MILESTONE_DUE_3D = "due_3d"
MILESTONE_DUE_24H = "due_24h"
MILESTONE_DUE_12H = "due_12h"

SHORT_LIFESPAN_HOURS = 72  # < 3 days → skip midway + due_3d
_SCHEDULER_WINDOW_HOURS = 1.0


def _parse_assignment_dt(raw: Optional[str]) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            return dt.replace(tzinfo=TIMEZONE)
        return dt.astimezone(TIMEZONE)
    except Exception:
        return None


def _student_id(row: dict) -> str:
    return str(row.get("id") or row.get("email") or "").strip()


def _assignment_reminder_logged(db, assignment_id: int, student_id: str, milestone: str) -> bool:
    row = db.execute(
        """
        SELECT 1 FROM assignment_reminder_logs
        WHERE assignment_id = ? AND student_id = ? AND reminder_type = ?
        """,
        (assignment_id, student_id, milestone),
    ).fetchone()
    return bool(row)


def _log_assignment_reminder(db, assignment_id: int, student_id: str, milestone: str) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO assignment_reminder_logs (assignment_id, student_id, reminder_type, sent_at)
        VALUES (?, ?, ?, ?)
        """,
        (assignment_id, student_id, milestone, now()),
    )


def _submitted_student_ids(assignment_id: int) -> set[str]:
    with connect() as db:
        return {
            str(r[0])
            for r in db.execute(
                "SELECT student_id FROM submissions WHERE assignment_id = ?",
                (assignment_id,),
            ).fetchall()
        }


def active_assignment_milestones(assignment: dict, ref: Optional[datetime] = None) -> list[str]:
    """
    Milestones from proportional timeline (deadline − created_at).
    Short assignments (<3 days): only 24h and 12h (creation is immediate on publish).
    """
    ref = ref or datetime.now(TIMEZONE)
    deadline_dt = _parse_assignment_dt(assignment.get("deadline"))
    created_dt = _parse_assignment_dt(assignment.get("created_at"))
    if not deadline_dt or not created_dt:
        return []

    lifespan = deadline_dt - created_dt
    if lifespan.total_seconds() <= 0:
        return []

    remaining = deadline_dt - ref
    if remaining.total_seconds() <= 0:
        return []

    lifespan_h = lifespan.total_seconds() / 3600.0
    remaining_h = remaining.total_seconds() / 3600.0
    elapsed_h = (ref - created_dt).total_seconds() / 3600.0
    short = lifespan_h < SHORT_LIFESPAN_HOURS

    def near(value: float, target: float, window: float = _SCHEDULER_WINDOW_HOURS) -> bool:
        return abs(value - target) <= window

    milestones: list[str] = []

    if not short:
        midway_target = lifespan_h * 0.5
        window = max(_SCHEDULER_WINDOW_HOURS, lifespan_h * 0.03)
        if near(elapsed_h, midway_target, window):
            milestones.append(MILESTONE_MIDWAY)
        if near(remaining_h, 72, window=1.5):
            milestones.append(MILESTONE_DUE_3D)

    if near(remaining_h, 24):
        milestones.append(MILESTONE_DUE_24H)
    if near(remaining_h, 12, window=0.75):
        milestones.append(MILESTONE_DUE_12H)

    return milestones


def _milestone_subject(assignment: dict, milestone: str) -> str:
    labels = {
        MILESTONE_CREATED: "New",
        MILESTONE_MIDWAY: "Midway check-in",
        MILESTONE_DUE_3D: "3 days left",
        MILESTONE_DUE_24H: "24 hours left",
        MILESTONE_DUE_12H: "12 hours left",
    }
    tag = labels.get(milestone, milestone)
    title = assignment.get("title") or "Assignment"
    due = assignment.get("deadline") or ""
    return prefix_subject(f"[Assignment · {tag}]", f"{title} — due {due}")


def dispatch_assignment_milestone_emails(
    assignment: dict,
    milestone: str,
    recipients: list[dict],
    *,
    html_builder=None,
    subject_builder=None,
    category=None,
) -> int:
    """Send one milestone email per student; skip submitted; log once per (assignment, student, milestone)."""
    from ..email import CATEGORY_ASSIGNMENT_NEW, CATEGORY_ASSIGNMENT_REMINDER

    assignment_id = int(assignment.get("id") or 0)
    if not assignment_id:
        return 0

    category = category or (
        CATEGORY_ASSIGNMENT_NEW if milestone == MILESTONE_CREATED else CATEGORY_ASSIGNMENT_REMINDER
    )
    submitted = _submitted_student_ids(assignment_id)
    sent = 0

    if html_builder:
        html_body = html_builder(assignment)
    else:
        html_body = build_assignment_reminder_html(assignment, milestone)

    subject_line = subject_builder(assignment) if subject_builder else _milestone_subject(assignment, milestone)

    with connect() as db:
        for row in recipients or []:
            student_id = _student_id(row)
            student_email = str(row.get("email") or "").strip().lower()
            if not student_email or "@" not in student_email:
                continue
            if student_id in submitted or student_email in submitted:
                continue
            if _assignment_reminder_logged(db, assignment_id, student_id, milestone):
                continue
            try:
                response = send_platform_email(
                    student_email,
                    subject_line,
                    html_body,
                    category=category,
                    tags=build_email_tags(
                        category,
                        assignment_id=str(assignment_id),
                        milestone=milestone,
                    ),
                    headers=assignment_notice_headers(deadline_iso=str(assignment.get("deadline") or "")),
                )
                if not response:
                    logger.warning(
                        "Assignment milestone FAILED milestone=%s assignment=%s to=%s",
                        milestone,
                        assignment_id,
                        student_email,
                    )
                    continue
                _log_assignment_reminder(db, assignment_id, student_id, milestone)
                sent += 1
                logger.info(
                    "Assignment milestone SUCCESS milestone=%s assignment=%s to=%s",
                    milestone,
                    assignment_id,
                    student_email,
                )
                print(
                    f"Assignment milestone SUCCESS {milestone} assignment={assignment_id} to={student_email}",
                    flush=True,
                )
            except Exception as exc:
                logger.exception(
                    "Assignment milestone ERROR milestone=%s assignment=%s to=%s: %s",
                    milestone,
                    assignment_id,
                    student_email,
                    exc,
                )
        db.commit()
    return sent


def _session_start_dt(session: dict, ref: datetime) -> Optional[datetime]:
    weekday = str(session.get("weekday") or "").strip().lower()
    if weekday and weekday != ref.strftime("%A").lower():
        return None
    class_date = str(session.get("class_date") or "").strip()[:10]
    if class_date and class_date != ref.strftime("%Y-%m-%d"):
        return None
    start_label = normalize_time_label(session.get("start_time"))
    if not start_label or ":" not in start_label:
        return None
    hour, minute = start_label.split(":", 1)
    try:
        return ref.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
    except ValueError:
        return None


def _class_reminder_already_sent(db, session_id: int, email: str, reminder_type: str) -> bool:
    row = db.execute(
        """
        SELECT 1 FROM class_reminder_logs
        WHERE class_session_id = ? AND LOWER(recipient_email) = LOWER(?) AND reminder_type = ?
        """,
        (session_id, email, reminder_type),
    ).fetchone()
    return bool(row)


def _log_class_reminder(db, session_id: int, email: str, reminder_type: str) -> None:
    stamp = now()
    db.execute(
        """
        INSERT OR IGNORE INTO class_reminder_logs (class_session_id, recipient_email, reminder_type, sent_at)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, email.lower(), reminder_type, stamp),
    )


def _faculty_email_for_session(db, session: dict) -> Optional[str]:
    name = str(session.get("faculty_name") or "").strip()
    if not name:
        return None
    row = db.execute(
        "SELECT email FROM faculty WHERE active = 1 AND LOWER(full_name) = LOWER(?) LIMIT 1",
        (name,),
    ).fetchone()
    if row and row["email"]:
        return str(row["email"]).strip()
    row = db.execute(
        "SELECT email FROM users WHERE UPPER(role) = 'FACULTY' AND LOWER(name) = LOWER(?) LIMIT 1",
        (name,),
    ).fetchone()
    if row and row["email"]:
        return str(row["email"]).strip()
    return None


def check_and_send_class_start_reminders() -> int:
    """Email enrolled students + host ~5 minutes before live class starts (IST)."""
    total_sent = 0
    ref = datetime.now(TIMEZONE)
    window_start = timedelta(minutes=4)
    window_end = timedelta(minutes=6)

    with connect() as db:
        sessions = [dict(r) for r in db.execute(
            "SELECT * FROM class_sessions WHERE IFNULL(status, 'scheduled') = 'scheduled'"
        ).fetchall()]

        for session in sessions:
            session_id = int(session.get("id") or 0)
            if not session_id:
                continue
            if int(session.get("start_reminder_sent") or 0) == 1:
                continue

            start_dt = _session_start_dt(session, ref)
            if not start_dt:
                continue

            delta = start_dt - ref
            if delta < window_start or delta > window_end:
                continue

            recipients = recipients_for_session(session)
            faculty_email = _faculty_email_for_session(db, session)
            if faculty_email:
                recipients = list(recipients) + [{"email": faculty_email.lower(), "name": session.get("faculty_name")}]

            bundle = live_class_email_bundle(session, start_dt=start_dt)
            subject_line = bundle["subject"]
            html_body = bundle["html"]

            session_sent = 0
            for row in recipients:
                email = str((row or {}).get("email") or "").strip().lower()
                if not email or "@" not in email:
                    continue
                if _class_reminder_already_sent(db, session_id, email, "start_5m"):
                    continue
                try:
                    response = send_platform_email(
                        email,
                        subject_line,
                        html_body,
                        category=bundle["category"],
                        tags=bundle["tags"],
                        headers=bundle["headers"],
                        expires_at=bundle["expires_at"],
                    )
                    if response:
                        _log_class_reminder(db, session_id, email, "start_5m")
                        session_sent += 1
                        logger.info("Class start reminder SUCCESS session=%s to=%s", session_id, email)
                        print(f"Class start reminder SUCCESS session={session_id} to={email}", flush=True)
                    else:
                        logger.warning("Class start reminder FAILED session=%s to=%s", session_id, email)
                except Exception as exc:
                    logger.exception("Class start reminder ERROR session=%s to=%s: %s", session_id, email, exc)

            if session_sent > 0:
                db.execute(
                    "UPDATE class_sessions SET start_reminder_sent = 1, updated_at = ? WHERE id = ?",
                    (now(), session_id),
                )
                total_sent += session_sent

        db.commit()

    return total_sent


def check_and_send_assignment_reminders() -> int:
    """
    Proportional assignment timeline reminders (midway, 3d, 24h, 12h).
    Creation emails fire immediately on publish (milestone `created`).
    """
    total_reminders_sent = 0
    ref = datetime.now(TIMEZONE)

    with connect() as db:
        assignments = [dict(r) for r in db.execute("SELECT * FROM assignments").fetchall()]

    for assignment in assignments:
        assignment_id = assignment.get("id")
        milestones = active_assignment_milestones(assignment, ref)
        if not milestones:
            continue

        batch_id = assignment.get("batch_id")
        students = list_recipient_students(subject=assignment.get("subject"), batch_id=batch_id)
        if not students:
            students = list_recipient_students(subject=None, batch_id=batch_id)

        for milestone in milestones:
            total_reminders_sent += dispatch_assignment_milestone_emails(
                assignment,
                milestone,
                students,
            )

    return total_reminders_sent


def run_scheduled_email_jobs() -> dict:
    """Single tick for APScheduler: class start + assignment deadline reminders."""
    try:
        class_sent = check_and_send_class_start_reminders()
    except Exception as exc:
        logger.exception("Class reminder job failed: %s", exc)
        class_sent = 0
    try:
        assignment_sent = check_and_send_assignment_reminders()
    except Exception as exc:
        logger.exception("Assignment reminder job failed: %s", exc)
        assignment_sent = 0
    summary = {"class_start_reminders": class_sent, "assignment_reminders": assignment_sent}
    if class_sent or assignment_sent:
        logger.info("Scheduled email jobs: %s", summary)
        print(f"Scheduled email jobs: {summary}", flush=True)
    return summary
