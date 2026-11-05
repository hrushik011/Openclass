import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from ..db import connect, now
from ..email import (
    CATEGORY_ASSIGNMENT_REMINDER,
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
    Scan assignments and send deadline reminder emails (2h / 24h / 3d / 7d tiers).
    Uses send_platform_email and assignment_reminder_logs for deduplication.
    """
    total_reminders_sent = 0
    ref = datetime.now(TIMEZONE)

    with connect() as db:
        assignments = [dict(r) for r in db.execute("SELECT * FROM assignments").fetchall()]

    for assignment in assignments:
        deadline_str = assignment.get("deadline")
        if not deadline_str:
            continue

        try:
            deadline_clean = deadline_str.replace("Z", "+00:00")
            deadline_dt = datetime.fromisoformat(deadline_clean)
            if deadline_dt.tzinfo is None:
                deadline_dt = deadline_dt.replace(tzinfo=TIMEZONE)
            else:
                deadline_dt = deadline_dt.astimezone(TIMEZONE)
        except Exception as exc:
            logger.error(
                "Invalid deadline for assignment %s: %s (%s)",
                assignment.get("id"),
                deadline_str,
                exc,
            )
            continue

        diff = deadline_dt - ref
        total_hours = diff.total_seconds() / 3600.0
        if total_hours <= 0:
            continue

        reminder_tier = None
        if total_hours <= 2.5:
            reminder_tier = "2h"
        elif total_hours <= 25.0 and total_hours > 20.0:
            reminder_tier = "24h"
        elif total_hours <= 73.0 and total_hours > 68.0:
            reminder_tier = "3d"
        elif total_hours <= 169.0 and total_hours > 164.0:
            reminder_tier = "7d"

        if not reminder_tier:
            continue

        assignment_id = assignment.get("id")
        batch_id = assignment.get("batch_id")
        students = list_recipient_students(subject=assignment.get("subject"), batch_id=batch_id)
        if not students:
            students = list_recipient_students(subject=None, batch_id=batch_id)

        with connect() as db:
            submitted_ids = {
                str(r[0])
                for r in db.execute(
                    "SELECT student_id FROM submissions WHERE assignment_id = ?",
                    (assignment_id,),
                ).fetchall()
            }

        students = [
            s for s in students
            if str(s.get("id") or s.get("email") or "") not in submitted_ids
        ]

        subject_line = prefix_subject(
            f"[Assignment Reminder {reminder_tier}]",
            f"{assignment.get('title') or 'Assignment'} — due {assignment.get('deadline') or ''}",
        )
        html_body = build_assignment_reminder_html(assignment, reminder_tier)
        ctx = f"assignment:reminder:{assignment_id}:{reminder_tier}"

        for student in students:
            student_id = str(student.get("id") or student.get("email") or "")
            student_email = str(student.get("email") or "").strip().lower()
            if not student_email or "@" not in student_email:
                continue

            with connect() as db:
                logged = db.execute(
                    """
                    SELECT 1 FROM assignment_reminder_logs
                    WHERE assignment_id = ? AND student_id = ? AND reminder_type = ?
                    """,
                    (assignment_id, student_id, reminder_tier),
                ).fetchone()
                if logged:
                    continue

            try:
                response = send_platform_email(
                    student_email,
                    subject_line,
                    html_body,
                    category=CATEGORY_ASSIGNMENT_REMINDER,
                    tags=build_email_tags(
                        CATEGORY_ASSIGNMENT_REMINDER,
                        assignment_id=str(assignment_id),
                        tier=reminder_tier,
                    ),
                    headers=assignment_notice_headers(deadline_iso=str(assignment.get("deadline") or "")),
                )
                if not response:
                    logger.warning(
                        "Assignment reminder FAILED tier=%s assignment=%s to=%s",
                        reminder_tier,
                        assignment_id,
                        student_email,
                    )
                    continue
                with connect() as db:
                    db.execute(
                        """
                        INSERT OR IGNORE INTO assignment_reminder_logs
                        (assignment_id, student_id, reminder_type, sent_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (assignment_id, student_id, reminder_tier, now()),
                    )
                    db.commit()
                total_reminders_sent += 1
                logger.info(
                    "Assignment reminder SUCCESS tier=%s assignment=%s to=%s",
                    reminder_tier,
                    assignment_id,
                    student_email,
                )
                print(
                    f"Assignment reminder SUCCESS tier={reminder_tier} assignment={assignment_id} to={student_email}",
                    flush=True,
                )
            except Exception as exc:
                logger.exception(
                    "Assignment reminder ERROR tier=%s assignment=%s to=%s: %s",
                    reminder_tier,
                    assignment_id,
                    student_email,
                    exc,
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
