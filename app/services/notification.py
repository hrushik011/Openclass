import logging
import smtplib
from email.message import EmailMessage
from typing import List, Optional

from ..config import (
    EMAIL_DELIVERY_ENABLED,
    SENDER_EMAIL,
    SIMULATION_MODE,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SERVER,
    SMTP_USERNAME,
    TEST_RECIPIENT_ALLOWLIST,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_ENABLED,
    TWILIO_PHONE_NUMBER,
)
from ..db import connect, now

logger = logging.getLogger("openclass.notification")


def _log_delivery(channel: str, action: str, status: str, detail: str) -> None:
    try:
        with connect() as db:
            db.execute(
                "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (channel, action, status, detail, now()),
            )
    except Exception as exc:
        logger.warning("Could not write delivery log: %s", exc)


def _smtp_send(msg: EmailMessage) -> None:
    port = int(SMTP_PORT or 587)
    host = SMTP_SERVER or "smtp.gmail.com"
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=20) as server:
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return
    with smtplib.SMTP(host, port, timeout=20) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        if SMTP_USERNAME and SMTP_PASSWORD:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)


class NotificationService:
    @staticmethod
    def send_email(recipient: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        recipient = (recipient or "").strip()
        if not recipient or "@" not in recipient:
            return False

        allowlist = TEST_RECIPIENT_ALLOWLIST
        if allowlist and recipient.lower() not in allowlist:
            logger.warning("Skipping %s — not on TEST_RECIPIENT_ALLOWLIST", recipient)
            _log_delivery("email", "smtp_dispatch", "skipped_allowlist", f"To: {recipient} | Subject: {subject}")
            return False

        smtp_ready = bool(SMTP_USERNAME and SMTP_PASSWORD and (SENDER_EMAIL or SMTP_USERNAME))
        live = EMAIL_DELIVERY_ENABLED and smtp_ready and not SIMULATION_MODE
        if not live:
            logger.info("[SIMULATION EMAIL] To: %s | Subject: %s", recipient, subject)
            _log_delivery(
                "email",
                "smtp_dispatch",
                "simulated",
                f"To: {recipient} | Subject: {subject} | enabled={EMAIL_DELIVERY_ENABLED} sim={SIMULATION_MODE}",
            )
            return True

        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SENDER_EMAIL or SMTP_USERNAME
            msg["To"] = recipient
            msg.set_content(body)
            if html_body:
                msg.add_alternative(html_body, subtype="html")
            _smtp_send(msg)
            logger.info("Email sent to %s", recipient)
            _log_delivery("email", "smtp_dispatch", "sent", f"To: {recipient} | Subject: {subject}")
            return True
        except Exception as exc:
            logger.exception("Failed to send email to %s: %s", recipient, exc)
            _log_delivery("email", "smtp_dispatch", "failed", f"To: {recipient} | Error: {exc}")
            return False

    @staticmethod
    def send_sms(phone_number: str, message: str) -> bool:
        if not phone_number or not phone_number.strip():
            return False
        phone_number = phone_number.strip()

        if SIMULATION_MODE or not TWILIO_ENABLED or not TWILIO_ACCOUNT_SID:
            logger.info("[SIMULATION SMS] To: %s | Message: %s", phone_number, message[:100])
            _log_delivery("sms", "sms_dispatch", "simulated", f"To: {phone_number} | Msg: {message}")
            return True

        try:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(body=message, from_=TWILIO_PHONE_NUMBER, to=phone_number)
            _log_delivery("sms", "sms_dispatch", "sent", f"To: {phone_number}")
            return True
        except Exception as exc:
            logger.error("Failed to send SMS to %s: %s", phone_number, exc)
            _log_delivery("sms", "sms_dispatch", "failed", f"To: {phone_number} | Error: {exc}")
            return False

    @classmethod
    def broadcast_assignment_created(cls, assignment: dict, recipients: List[dict]) -> int:
        title = assignment.get("title", "New Assignment")
        batch_id = assignment.get("batch_id") or "All Batches"
        deadline = assignment.get("deadline", "")
        subject = assignment.get("subject", "Academic Course")
        faculty_name = assignment.get("faculty_name", "Course Faculty")
        description = assignment.get("description") or "Please review instructions and submit on time."
        email_subject = f"New Assignment: {title} · {batch_id}"
        email_body = (
            f"A new assignment has been posted for {batch_id}.\n\n"
            f"Title: {title}\nSubject: {subject}\nFaculty: {faculty_name}\nDeadline: {deadline}\n\n"
            f"{description}\n\nOpenclass Academic System"
        )
        sent = 0
        if not recipients:
            logger.warning("Assignment %s has no email recipients for batch %s", title, batch_id)
            _log_delivery("email", "assignment_broadcast", "no_recipients", f"{title} · {batch_id}")
            return 0
        for row in recipients:
            email = ((row or {}).get("email") or "").strip()
            if not email:
                logger.warning("Skipping roster row without email for assignment '%s': %s", title, row)
                _log_delivery("email", "assignment_broadcast", "missing_email", f"{title} · {row}")
                continue
            if cls.send_email(email, email_subject, email_body):
                sent += 1
            else:
                logger.warning("Assignment email was not delivered to %s for '%s'", email, title)
        logger.info("Assignment broadcast '%s' emailed %s/%s recipients", title, sent, len(recipients))
        return sent

    @classmethod
    def notify_faculty_direct_message(cls, faculty_email: str, thread: dict, sender_name: str, preview: str) -> bool:
        if not faculty_email:
            return False
        title = thread.get("title", "Private message")
        email_subject = f"Openclass DM: {title}"
        email_body = (
            f"You have a private message on Openclass.\n\n"
            f"From: {sender_name}\n"
            f"Thread: {title}\n\n"
            f"{preview}\n\n"
            f"Log in to Openclass → Class Threads → Private Faculty DMs to reply.\n"
        )
        return cls.send_email(faculty_email, email_subject, email_body)

    @classmethod
    def notify_batch_thread_announcement(cls, recipients: List[dict], thread: dict, poster_name: str, preview: str) -> int:
        title = thread.get("title", "Course announcement")
        batch_id = thread.get("batch_id") or "All Batches"
        subject = thread.get("subject") or "Course"
        email_subject = f"Openclass [{batch_id}] {subject}: {title}"
        email_body = (
            f"A new announcement was posted in your course thread.\n\n"
            f"Batch: {batch_id}\n"
            f"Subject: {subject}\n"
            f"From: {poster_name}\n"
            f"Thread: {title}\n\n"
            f"{preview}\n\n"
            f"Open Class Threads in Openclass to read and reply.\n"
        )
        sent = 0
        for row in recipients:
            email = (row or {}).get("email")
            if email and cls.send_email(email, email_subject, email_body):
                sent += 1
        return sent

    @classmethod
    def send_assignment_reminder(cls, assignment: dict, student: dict, reminder_tier: str) -> bool:
        email = (student or {}).get("email")
        if not email:
            return False
        title = assignment.get("title", "Assignment")
        deadline = assignment.get("deadline", "")
        email_subject = f"Reminder ({reminder_tier}): {title}"
        email_body = (
            f"This is a {reminder_tier} reminder for an upcoming assignment.\n\n"
            f"Title: {title}\n"
            f"Subject: {assignment.get('subject') or 'Course'}\n"
            f"Deadline: {deadline}\n\n"
            f"Please submit on Openclass before the deadline.\n"
        )
        return cls.send_email(email, email_subject, email_body)
