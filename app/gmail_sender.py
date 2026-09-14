"""Gmail API sender. All recipients are checked by the caller before this runs."""
import base64
from email.message import EmailMessage

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

def credentials_from_json(payload: str) -> Credentials:
    credentials = Credentials.from_authorized_user_info(__import__("json").loads(payload))
    if not credentials.valid and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials.valid:
        raise RuntimeError("Google sign-in has expired. Connect Google again.")
    return credentials

def send_email(credentials_json: str, recipient: str, subject: str, body: str) -> str:
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    session = AuthorizedSession(credentials_from_json(credentials_json))
    response = session.post(GMAIL_SEND_URL, json={"raw": raw}, timeout=20)
    response.raise_for_status()
    return response.json()["id"]
