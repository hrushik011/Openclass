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
from ..gmail_sender import send_email as gmail_send_email

logger = logging.getLogger("openclass.notification")


class NotificationService:
    @staticmethod
    def send_email(recipient: str, subject: str, body: str, html_body: Optional[str] = None) -> bool:
        recipient = recipient.strip().lower()
        if not recipient:
            return False

        # If test allowlist is configured and not simulation, enforce
        if TEST_RECIPIENT_ALLOWLIST and recipient not in TEST_RECIPIENT_ALLOWLIST and not SIMULATION_MODE:
            logger.warning(f"Recipient {recipient} not in allowlist. Skipped.")
            return False

        # Try Google credentials first if connected
        try:
            with connect() as db:
                row = db.execute("SELECT credentials_json FROM google_credentials WHERE id=1").fetchone()
            if row and row["credentials_json"]:
                msg_id = gmail_send_email(row["credentials_json"], recipient, subject, body)
                with connect() as db:
                    db.execute(
                        "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                        ("email", "gmail_api_dispatch", "sent", f"To: {recipient} | MsgId: {msg_id} | Subj: {subject}", now()),
                    )
                return True
        except Exception as e:
            logger.debug(f"Google Gmail API dispatch attempt: {e}")

        # Live SMTP dispatch
        if EMAIL_DELIVERY_ENABLED and not SIMULATION_MODE and SMTP_SERVER:
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
                        ("email", "smtp_dispatch", "sent", f"To: {recipient} | Subject: {subject}", now()),
                    )
                return True
            except Exception as e:
                logger.error(f"Failed to send email to {recipient}: {e}")

        # Simulation mode fallback: log to database & console
        logger.info(f"[SIMULATION EMAIL] To: {recipient} | Subject: {subject}\nBody: {body[:140]}...")
        with connect() as db:
            db.execute(
                "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                ("email", "email_dispatch", "simulated", f"To: {recipient} | Subject: {subject}", now()),
            )
        return True

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
                    ("sms", "sms_dispatch", "simulated", f"To: {phone_number} | Msg: {message}", now()),
                )
            return True

        try:
            from twilio.rest import Client
            client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
            client.messages.create(body=message, from_=TWILIO_PHONE_NUMBER, to=phone_number)
            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("sms", "sms_dispatch", "sent", f"To: {phone_number}", now()),
                )
            return True
        except Exception as e:
            logger.error(f"Failed to send SMS to {phone_number}: {e}")
            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("sms", "sms_dispatch", "failed", f"To: {phone_number} | Error: {str(e)}", now()),
                )
            return False

    @classmethod
    def broadcast_assignment_created(cls, assignment: dict, recipients: List[dict]) -> int:
        """
        Broadcasts formatted notification email to all enrolled students in the target batch upon creation.
        """
        title = assignment.get("title", "New Assignment")
        batch_id = assignment.get("batch_id", "")
        deadline = assignment.get("deadline", "")
        subject = assignment.get("subject", "Academic Course")
        faculty_name = assignment.get("faculty_name", "Course Faculty")
        description = assignment.get("description", "Please review instructions and submit on time.")

        email_subject = f"📝 New Assignment: {title} · {batch_id}"
        email_body = (
            f"Hello Student,\n\n"
            f"A new assignment has been posted for your batch: {batch_id}.\n\n"
            f"Assignment Details:\n"
            f"• Title: {title}\n"
            f"• Subject: {subject}\n"
            f"• Faculty: {faculty_name}\n"
            f"• Due Date: {deadline}\n\n"
            f"Description:\n{description}\n\n"
            f"Please log into OpenClass to view the guidelines and submit your files.\n\n"
            f"Best regards,\nOpenClass Academic System"
        )
        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #12111e; color: #f4f1ff; border: 1px solid rgba(138, 127, 195, 0.2); border-radius: 12px; overflow: hidden; padding: 24px;">
            <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 20px;">
                <div style="background: linear-gradient(140deg, #a78bfa, #6354d8); width: 28px; height: 28px; border-radius: 8px; display: inline-block;"></div>
                <span style="font-weight: 700; font-size: 18px; margin-left: 8px;">Openclass</span>
            </div>
            <h2 style="color: #a78bfa; margin-top: 0; font-size: 20px;">New Assignment Posted: {title}</h2>
            <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(138, 127, 195, 0.15); border-radius: 8px; padding: 16px; margin: 16px 0;">
                <p style="margin: 6px 0;"><strong>Course:</strong> {subject}</p>
                <p style="margin: 6px 0;"><strong>Target Batch:</strong> {batch_id}</p>
                <p style="margin: 6px 0;"><strong>Faculty:</strong> {faculty_name}</p>
                <p style="margin: 6px 0;"><strong>Deadline:</strong> <span style="color: #61d7da; font-weight: bold;">{deadline}</span></p>
            </div>
            <p style="color: #b3aec5; line-height: 1.5;">{description}</p>
            <div style="margin-top: 24px;">
                <a href="http://localhost:8000" style="display: inline-block; background: linear-gradient(135deg, #7160cb, #5243b6); color: #fff; padding: 11px 22px; border-radius: 8px; font-weight: 600; text-decoration: none;">Go to Assignment Portal</a>
            </div>
        </div>
        """

        sent_count = 0
        for r in recipients:
            email = r.get("email")
            phone = r.get("phone")
            if email:
                if cls.send_email(email, email_subject, email_body, html_body=html_body):
                    sent_count += 1
            if phone:
                cls.send_sms(phone, f"OpenClass: New assignment '{title}' posted for {batch_id}. Deadline: {deadline}.")

        stamp = now()
        with connect() as db:
            db.execute(
                "INSERT INTO delivery_log (assignment_id, channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (assignment.get("id"), "broadcast", "assignment_creation_blast", "success", f"Dispatched to {len(recipients)} students in {batch_id}", stamp),
            )
        return sent_count

    @classmethod
    def send_assignment_reminder(cls, assignment: dict, student: dict, reminder_type: str) -> bool:
        """
        Sends targeted reminder email to student who has not yet submitted.
        """
        title = assignment.get("title", "Assignment")
        deadline = assignment.get("deadline", "")
        subject = assignment.get("subject", "Course")
        student_name = student.get("name", "Student")
        student_email = student.get("email")
        student_phone = student.get("phone")

        time_labels = {
            "2h": "2 hours",
            "24h": "24 hours",
            "3d": "3 days",
            "7d": "7 days",
        }
        time_label = time_labels.get(reminder_type, f"{reminder_type} remaining")

        email_subject = f"⚠️ Urgent: '{title}' ({subject}) is due in {time_label}!"
        email_body = (
            f"Hello {student_name},\n\n"
            f"This is an automated reminder that your assignment '{title}' is due in {time_label}.\n\n"
            f"Assignment Details:\n"
            f"• Title: {title}\n"
            f"• Course: {subject}\n"
            f"• Deadline: {deadline}\n\n"
            f"Our records show that your submission is still pending. Please upload your files on OpenClass before the deadline.\n\n"
            f"Best regards,\nOpenClass Academic System"
        )
        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #12111e; color: #f4f1ff; border: 1px solid rgba(255, 139, 123, 0.3); border-radius: 12px; overflow: hidden; padding: 24px;">
            <h2 style="color: #ff8b7b; margin-top: 0; font-size: 20px;">⚠️ Reminder: Submission due in {time_label}</h2>
            <p>Hello <strong>{student_name}</strong>,</p>
            <p>Your assignment <strong>{title}</strong> for <strong>{subject}</strong> has not been submitted yet.</p>
            <div style="background: rgba(255, 139, 123, 0.08); border-left: 4px solid #ff8b7b; padding: 12px; margin: 16px 0;">
                <p style="margin: 0;"><strong>Final Deadline:</strong> {deadline}</p>
            </div>
            <div style="margin-top: 24px;">
                <a href="http://localhost:8000" style="display: inline-block; background: #ff8b7b; color: #12111e; padding: 11px 22px; border-radius: 8px; font-weight: 700; text-decoration: none;">Submit Assignment Now</a>
            </div>
        </div>
        """

        success = False
        if student_email:
            success = cls.send_email(student_email, email_subject, email_body, html_body=html_body)
        if student_phone:
            cls.send_sms(student_phone, f"Reminder: Assignment '{title}' is due in {time_label}. Upload now on OpenClass.")

        stamp = now()
        with connect() as db:
            db.execute(
                """INSERT INTO assignment_reminder_logs (assignment_id, student_id, reminder_type, sent_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(assignment_id, student_id, reminder_type) DO UPDATE SET sent_at=excluded.sent_at""",
                (assignment["id"], str(student["id"]), reminder_type, stamp),
            )
            db.execute(
                "INSERT INTO delivery_log (assignment_id, channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (assignment["id"], "reminder", f"reminder_{reminder_type}", "sent" if success else "failed", f"To: {student_email}", stamp),
            )
        return success
