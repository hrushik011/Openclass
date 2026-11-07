"""Event-driven and scheduled emails via Resend (send_platform_email)."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

from ..email import (
    CATEGORY_ASSIGNMENT_NEW,
    CATEGORY_ASSIGNMENT_REMINDER,
    CATEGORY_CLASS_SCHEDULED,
    CATEGORY_LIVE_CLASS,
    assignment_notice_headers,
    build_email_tags,
    live_class_alert_headers,
    prefix_subject,
    send_platform_email,
)
from .roster import list_recipient_students, normalize_time_label

logger = logging.getLogger("openclass.platform_notifications")
IST = ZoneInfo("Asia/Kolkata")


def _deadline_highlight_html(deadline_raw: str, *, urgent: bool = False) -> str:
    deadline = html.escape(str(deadline_raw or "See Openclass portal"))
    bg = "#fef3c7" if urgent else "#ede9fe"
    border = "#f59e0b" if urgent else "#7c3aed"
    label = "Submit before" if not urgent else "Deadline approaching — submit before"
    return (
        f'<div style="margin:16px 0;padding:14px 16px;background:{bg};'
        f'border-left:4px solid {border};border-radius:8px;">'
        f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.04em;color:#475569;">{label}</div>'
        f'<div style="font-size:18px;font-weight:800;color:#0f172a;margin-top:6px;">{deadline}</div>'
        f'<div style="font-size:11px;color:#64748b;margin-top:4px;">Track this date in your calendar or task reminders.</div>'
        f"</div>"
    )


def send_platform_email_to_roster(
    recipients: list[dict],
    subject: str,
    html_content: str,
    *,
    context: str = "notification",
    category: Optional[str] = None,
    tags: Optional[list[dict[str, str]]] = None,
    headers: Optional[Mapping[str, str]] = None,
    expires_at: Optional[datetime] = None,
) -> int:
    """Send to each unique roster email with per-recipient success/failure logging."""
    targets = sorted({
        str((row or {}).get("email") or "").strip().lower()
        for row in (recipients or [])
        if str((row or {}).get("email") or "").strip()
    })
    logger.info("Platform email roster (%s) targets: %s", context, targets)
    print(f"Platform email roster ({context}) targets: {targets}", flush=True)

    sent = 0
    seen: set[str] = set()
    for row in recipients or []:
        email = str((row or {}).get("email") or "").strip()
        key = email.lower()
        name = str((row or {}).get("name") or "").strip()
        if not email or "@" not in email or key in seen:
            continue
        seen.add(key)
        try:
            response = send_platform_email(
                email,
                subject,
                html_content,
                category=category,
                tags=tags,
                headers=headers,
                expires_at=expires_at,
            )
            if response:
                sent += 1
                logger.info("Platform email SUCCESS context=%s to=%s name=%r", context, email, name)
                print(f"Platform email SUCCESS ({context}) to={email}", flush=True)
            else:
                logger.warning("Platform email FAILED context=%s to=%s (no response)", context, email)
                print(f"Platform email FAILED ({context}) to={email}", flush=True)
        except Exception as exc:
            logger.exception("Platform email ERROR context=%s to=%s: %s", context, email, exc)
            print(f"Platform email ERROR ({context}) to={email}: {exc}", flush=True)
    logger.info("Platform email roster (%s) sent %s/%s", context, sent, len(seen))
    return sent


def recipients_for_session(session: dict) -> list[dict]:
    subject = session.get("subject")
    batch = session.get("batch")
    recipients = list_recipient_students(subject, batch)
    if not recipients and batch:
        recipients = list_recipient_students(subject=None, batch_id=batch)
    return recipients


def _faculty_recipient(session: dict, faculty_email: Optional[str] = None) -> Optional[dict]:
    email = str(faculty_email or "").strip()
    if email and "@" in email:
        return {"email": email.lower(), "name": session.get("faculty_name") or "Faculty"}
    return None


def build_assignment_published_html(assignment: dict) -> str:
    title = html.escape(str(assignment.get("title") or "Assignment"))
    subj = html.escape(str(assignment.get("subject") or ""))
    batch = html.escape(str(assignment.get("batch_id") or ""))
    deadline_raw = str(assignment.get("deadline") or "")
    faculty = html.escape(str(assignment.get("faculty_name") or ""))
    desc = html.escape(str(assignment.get("description") or "Please review the instructions and submit on time."))
    return (
        f"<p>A new assignment was published in <strong>Openclass</strong>.</p>"
        f"<p><strong>{title}</strong></p>"
        f"<p>Subject: {subj}<br>Batch: {batch}<br>Faculty: {faculty}</p>"
        f"{_deadline_highlight_html(deadline_raw)}"
        f"<p>{desc}</p>"
    )


def build_class_scheduled_html(session: dict, meet_url: Optional[str] = None) -> str:
    subj = html.escape(str(session.get("subject") or "Class"))
    batch = html.escape(str(session.get("batch") or "All Batches"))
    when_date = html.escape(str(session.get("class_date") or session.get("weekday") or "Scheduled"))
    start = html.escape(normalize_time_label(session.get("start_time") or "") or "—")
    end = html.escape(normalize_time_label(session.get("end_time") or "") or "")
    faculty = html.escape(str(session.get("faculty_name") or "Course faculty"))
    link = html.escape(str(meet_url or session.get("google_meet_url") or ""))
    link_block = (
        f'<p><a href="{link}">Join Google Meet</a></p>' if link else "<p>Meeting link will be shared in Openclass.</p>"
    )
    time_line = f"{start}" + (f" – {end}" if end and end != "—" else "")
    return (
        f"<p>A live class session was scheduled in <strong>Openclass</strong>.</p>"
        f"<p><strong>{subj}</strong> · {batch}</p>"
        f"<p>When: {when_date} at {time_line}<br>Faculty: {faculty}</p>"
        f"{link_block}"
        f'<p style="font-size:11px;color:#64748b;">This notice remains useful until the session ends.</p>'
    )


def build_class_start_reminder_html(session: dict, meet_url: Optional[str] = None) -> str:
    subj = html.escape(str(session.get("subject") or "Class"))
    start = html.escape(normalize_time_label(session.get("start_time") or "") or "soon")
    faculty = html.escape(str(session.get("faculty_name") or "Faculty"))
    link = html.escape(str(meet_url or session.get("google_meet_url") or ""))
    link_block = f'<p><strong><a href="{link}">Join now — Google Meet</a></strong></p>' if link else ""
    return (
        f'<p style="font-size:12px;color:#b45309;font-weight:700;">⏱ Time-sensitive — valid for this session only</p>'
        f"<p>Your class <strong>{subj}</strong> starts in about <strong>5 minutes</strong> ({start} IST).</p>"
        f"<p>Host: {faculty}</p>"
        f"{link_block}"
    )


def build_assignment_reminder_html(assignment: dict, milestone: str) -> str:
    title = html.escape(str(assignment.get("title") or "Assignment"))
    deadline_raw = str(assignment.get("deadline") or "")
    subj = html.escape(str(assignment.get("subject") or ""))
    label = html.escape(_milestone_display_label(milestone))
    urgent = milestone in {"due_24h", "due_12h"}
    return (
        f"<p><strong>{label}</strong> — assignment timeline update in <strong>Openclass</strong>.</p>"
        f"<p><strong>{title}</strong></p>"
        f"<p>Subject: {subj}</p>"
        f"{_deadline_highlight_html(deadline_raw, urgent=urgent)}"
        f"<p>Please submit before the deadline shown above.</p>"
    )


def _milestone_display_label(milestone: str) -> str:
    labels = {
        "created": "New assignment published",
        "midway": "Midway check-in (~50% of time elapsed)",
        "due_3d": "3 days remaining",
        "due_24h": "24 hours remaining",
        "due_12h": "12 hours remaining",
    }
    return labels.get(milestone, milestone.replace("_", " ").title())


def notify_assignment_published(assignment: dict) -> int:
    from .reminders import dispatch_assignment_milestone_emails, MILESTONE_CREATED

    recipients = list_recipient_students(assignment.get("subject"), assignment.get("batch_id"))
    if not recipients:
        recipients = list_recipient_students(subject=None, batch_id=assignment.get("batch_id"))
    return dispatch_assignment_milestone_emails(
        assignment,
        MILESTONE_CREATED,
        recipients,
        html_builder=build_assignment_published_html,
        subject_builder=lambda a: prefix_subject(
            "[Assignment]",
            f"New: {a.get('title') or 'Assignment'} — due {a.get('deadline') or 'TBD'}",
        ),
        category=CATEGORY_ASSIGNMENT_NEW,
    )


def notify_class_session_published(session: dict, faculty_email: Optional[str] = None) -> int:
    recipients = recipients_for_session(session)
    fac = _faculty_recipient(session, faculty_email)
    if fac:
        recipients = list(recipients) + [fac]
    subject_line = prefix_subject(
        "[Class Scheduled]",
        f"{session.get('subject') or 'Live session'} · {session.get('class_date') or session.get('weekday') or ''} "
        f"{normalize_time_label(session.get('start_time') or '')}",
    )
    html_body = build_class_scheduled_html(session)
    ctx = f"class:published:{session.get('id')}"
    expires = datetime.now(IST) + timedelta(days=1)
    return send_platform_email_to_roster(
        recipients,
        subject_line,
        html_body,
        context=ctx,
        category=CATEGORY_CLASS_SCHEDULED,
        tags=build_email_tags(CATEGORY_CLASS_SCHEDULED, session_id=str(session.get("id") or "")),
        headers=assignment_notice_headers(),
        expires_at=expires,
    )


def live_class_email_bundle(session: dict, *, start_dt: Optional[datetime] = None) -> dict[str, Any]:
    """Subject, headers, tags, and expiry for ~5-minute class alerts."""
    raw_subj = str(session.get("subject") or "Class")
    start_label = normalize_time_label(session.get("start_time") or "") or "soon"
    subject_line = prefix_subject(
        "[Live Class Alert]",
        f"{raw_subj} starts in 5 min ({start_label} IST)",
    )
    expires = (start_dt or datetime.now(IST)) + timedelta(hours=2)
    return {
        "subject": subject_line,
        "html": build_class_start_reminder_html(session),
        "category": CATEGORY_LIVE_CLASS,
        "tags": build_email_tags(
            CATEGORY_LIVE_CLASS,
            session_id=str(session.get("id") or ""),
            subject=raw_subj[:80],
        ),
        "headers": live_class_alert_headers(expires_at=expires),
        "expires_at": expires,
    }
