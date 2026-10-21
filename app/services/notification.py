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
        # 🛠️ OVERRIDE RECIPIENT FOR LOCAL TESTING:
        recipient = "hrushikgandhi@gmail.com"
        print(f"📧 [TESTING] Forcing email dispatch to: {recipient}")

        if not EMAIL_DELIVERY_ENABLED or SIMULATION_MODE:
            print("ℹ️ Email delivery disabled or in simulation mode.")
            return False

        # Live SMTP dispatch directly via SSL (Port 465)
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = SENDER_EMAIL or SMTP_USERNAME
            msg["To"] = recipient
            msg.set_content(body)
            if html_body:
                msg.add_alternative(html_body, subtype="html")

            print(f"🚀 Connecting securely to SMTP server {SMTP_SERVER}:{SMTP_PORT} as {SMTP_USERNAME}...")
            
            # Using SMTP_SSL for port 465
            with smtplib.SMTP_SSL(SMTP_SERVER, int(SMTP_PORT), timeout=10) as server:
                if SMTP_USERNAME and SMTP_PASSWORD:
                    server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.send_message(msg)

            print(f"✅ Email successfully sent to {recipient}!")
            
            with connect() as db:
                db.execute(
                    "INSERT INTO delivery_log (channel, action, status, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("email", "smtp_dispatch", "sent", f"To: {recipient} | Subject: {subject}", now()),
                )
            return True
        except Exception as e:
            print(f"❌ CRITICAL SMTP ERROR: {e}")
            logger.error(f"Failed to send email to {recipient}: {e}")
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