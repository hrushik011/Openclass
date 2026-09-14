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

class NotificationService:
    @staticmethod
    def send_email(recipient: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        recipient = recipient.strip().lower()
        if not recipient:
            return False

        # If test allowlist is configured, enforce it
        if TEST_RECIPIENT_ALLOWLIST and recipient not in TEST_RECIPIENT_ALLOWLIST and not SIMULATION_MODE:
            logger.warning(f"Recipient {recipient} not in allowlist. Skipped.")
            return False

        if SIMULATION_MODE or not EMAIL_DELIVERY_ENABLED:
            logger.info(f"[SIMULATION EMAIL] To: {recipient} | Subject: {subject}\nBody: {body[:120]}...")
            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("email", "email_dispatch", "simulated", f"To: {recipient} | Subject: {subject}", now())
                )
            return True

        # Live SMTP dispatch
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SENDER_EMAIL
            msg["To"] = recipient
            msg.set_content(body)
            if html_body:
                msg.add_alternative(html_body, subtype="html")

            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
                server.starttls()
                if SMTP_USERNAME and SMTP_PASSWORD:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)

            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("email", "email_dispatch", "sent", f"To: {recipient} | Subject: {subject}", now())
                )
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {recipient}: {e}")
            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("email", "email_dispatch", "failed", f"To: {recipient} | Error: {str(e)}", now())
                )
            return False

    @staticmethod
    def send_sms(phone_number: str, message: str) -> bool:
        if not phone_number or not phone_number.strip():
            return False
        phone_number = phone_number.strip()

        if SIMULATION_MODE or not TWILIO_ENABLED or not TWILIO_ACCOUNT_SID:
            logger.info(f"[SIMULATION SMS] To: {phone_number} | Message: {message[:100]}...")
            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("sms", "sms_dispatch", "simulated", f"To: {phone_number} | Msg: {message}", now())
                )
            return True

        # Live Twilio dispatch
        try:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(
                body=message,
                from_=TWILIO_PHONE_NUMBER,
                to=phone_number
            )
            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("sms", "sms_dispatch", "sent", f"To: {phone_number}", now())
                )
            return True
        except Exception as e:
            logger.error(f"Failed to send SMS to {phone_number}: {e}")
            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("sms", "sms_dispatch", "failed", f"To: {phone_number} | Error: {str(e)}", now())
                )
            return False

    @classmethod
    def broadcast_teams_meeting(cls, session: dict, teams_url: str, recipients: List[dict]) -> int:
        """
        Broadcasts static MS Teams meeting link to faculty and students 15 mins before class.
        recipients list contains dicts with {'name': ..., 'email': ..., 'phone': ...}
        """
        subject_name = session.get("subject", "Class")
        batch_name = session.get("batch", "All Batches")
        start_time = session.get("start_time", "")
        class_date = session.get("class_date", "Today")
        faculty_name = session.get("faculty_name", "Faculty")

        email_subject = f"🔴 MS Teams Join Link: {subject_name} ({batch_name}) starts at {start_time}"
        email_body = (
            f"Hello,\n\n"
            f"Your upcoming class is scheduled to begin in 15 minutes.\n\n"
            f"Class Details:\n"
            f"• Subject: {subject_name}\n"
            f"• Batch: {batch_name}\n"
            f"• Date & Time: {class_date} at {start_time}\n"
            f"• Faculty: {faculty_name}\n\n"
            f"🔗 Microsoft Teams Join Link:\n"
            f"{teams_url}\n\n"
            f"Best regards,\n"
            f"Openclass Academic System"
        )
        sms_body = f"Class Alert: {subject_name} ({batch_name}) starts at {start_time}. Join MS Teams: {teams_url}"

        sent_count = 0
        for r in recipients:
            email = r.get("email")
            phone = r.get("phone")
            if email:
                if cls.send_email(email, email_subject, email_body):
                    sent_count += 1
            if phone:
                cls.send_sms(phone, sms_body)

        stamp = now()
        with connect() as db:
            db.execute(
                "INSERT INTO delivery_log (class_session_id, channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session.get("id"), "broadcast", "teams_15m_broadcast", "success", f"Dispatched to {len(recipients)} recipients", stamp)
            )
        return sent_count

    @classmethod
    def broadcast_assignment_created(cls, assignment: dict, recipients: List[dict]) -> int:
        """
        Broadcasts instant alert to all batch students when a new assignment is created.
        """
        title = assignment.get("title", "New Assignment")
        batch_id = assignment.get("batch_id", "")
        deadline = assignment.get("deadline", "")
        description = assignment.get("description", "Please review and submit on time.")

        email_subject = f"📝 New Assignment Posted: {title} (Batch: {batch_id})"
        email_body = (
            f"Hello Student,\n\n"
            f"A new assignment has been posted for your batch ({batch_id}).\n\n"
            f"Assignment Details:\n"
            f"• Title: {title}\n"
            f"• Description: {description}\n"
            f"• Due Date: {deadline}\n\n"
            f"Please log in to Openclass to submit your work before the deadline.\n\n"
            f"Thank you,\n"
            f"Openclass Academic System"
        )
        sms_body = f"New Assignment: '{title}' posted for Batch {batch_id}. Deadline: {deadline}."

        sent_count = 0
        for r in recipients:
            email = r.get("email")
            phone = r.get("phone")
            if email:
                if cls.send_email(email, email_subject, email_body):
                    sent_count += 1
            if phone:
                cls.send_sms(phone, sms_body)

        stamp = now()
        with connect() as db:
            db.execute(
                "INSERT INTO delivery_log (assignment_id, channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (assignment.get("id"), "broadcast", "assignment_creation_blast", "success", f"Sent blast to {len(recipients)} students", stamp)
            )
        return sent_count

    @classmethod
    def send_assignment_reminder(cls, assignment: dict, student: dict, reminder_type: str) -> bool:
        """
        Sends targeted reminder (24h or 2h) to a student who has not yet submitted.
        """
        title = assignment.get("title", "Assignment")
        deadline = assignment.get("deadline", "")
        student_name = student.get("name", "Student")
        student_email = student.get("email")
        student_phone = student.get("phone")

        time_label = "24 hours" if reminder_type == "24h" else "2 hours"
        email_subject = f"⚠️ Reminder: '{title}' submission due in {time_label}!"
        email_body = (
            f"Hello {student_name},\n\n"
            f"This is an automated reminder that your assignment '{title}' is due in {time_label}.\n\n"
            f"Assignment Details:\n"
            f"• Title: {title}\n"
            f"• Deadline: {deadline}\n\n"
            f"Our records indicate that your submission is still pending. Please submit your files on Openclass as soon as possible.\n\n"
            f"Best regards,\n"
            f"Openclass Academic System"
        )
        sms_body = f"Reminder: Assignment '{title}' is due in {time_label} ({deadline}). Please upload your submission."

        success = False
        if student_email:
            success = cls.send_email(student_email, email_subject, email_body)
        if student_phone:
            cls.send_sms(student_phone, sms_body)

        stamp = now()
        with connect() as db:
            db.execute(
                "INSERT INTO assignment_reminder_logs (assignment_id, student_id, reminder_type, sent_at) VALUES (?, ?, ?, ?) ON CONFLICT(assignment_id, student_id, reminder_type) DO UPDATE SET sent_at=excluded.sent_at",
                (assignment["id"], str(student["id"]), reminder_type, stamp)
            )
            db.execute(
                "INSERT INTO delivery_log (assignment_id, channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (assignment["id"], "reminder", f"reminder_{reminder_type}", "sent", f"Sent to {student_email}", stamp)
            )
        return success
