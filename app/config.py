import os
from pathlib import Path
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

APP_MODE = os.getenv("APP_MODE", "development").lower()
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "data" / "classroomflow.db")))
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(ROOT / "uploads")))

# Session & Security
APP_SESSION_SECRET = os.getenv("APP_SESSION_SECRET", "super-secret-key-change-me")

# Domain Restriction
ALLOWED_EMAIL_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "college.edu").lower()

# JWT Settings for Internal Session
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "openclass-secret-jwt-key-for-auth-2026")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "1440"))  # 24 hours

# Google OAuth & Google Meet Settings
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/auth/google/callback")
GOOGLE_OAUTH_CONFIGURED = os.getenv("GOOGLE_OAUTH_CONFIGURED", "").lower() in ("true", "1") or bool(
    GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET
)
MEET_CREATION_ALLOWED = os.getenv("MEET_CREATION_ALLOWED", "true").lower() in ("true", "1", "yes")

# Microsoft Entra ID (MS Office 365 OAuth)
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")
AZURE_TENANT_ID = (os.getenv("AZURE_TENANT_ID") or "").strip()
_MS_TENANT_RAW = (os.getenv("MS_TENANT_ID") or "").strip()
# Prefer AZURE_TENANT_ID so authorize/token never fall back to /common when a tenant is set.
MS_TENANT_ID = AZURE_TENANT_ID or _MS_TENANT_RAW or "common"
MS_REDIRECT_URI = os.getenv("MS_REDIRECT_URI", "http://localhost:8000/auth/microsoft/callback")


def microsoft_oauth_tenant() -> str:
    """Tenant segment for login.microsoftonline.com/{tenant}/oauth2/v2.0/*."""
    azure = (os.getenv("AZURE_TENANT_ID") or "").strip()
    if azure:
        return azure
    ms_tenant = (os.getenv("MS_TENANT_ID") or "").strip()
    return ms_tenant or "common"

# Email / SMTP Settings & Allowlist
EMAIL_DELIVERY_ALLOWED = os.getenv("EMAIL_DELIVERY_ALLOWED", "false").lower() in ("true", "1", "yes")
EMAIL_DELIVERY_ENABLED = os.getenv("EMAIL_DELIVERY_ENABLED", "false").lower() in ("true", "1", "yes") or EMAIL_DELIVERY_ALLOWED
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SENDER_EMAIL = (
    os.getenv("SENDER_EMAIL")
    or os.getenv("SMTP_FROM_EMAIL")
    or os.getenv("SMTP_USERNAME")
    or "notifications@college.edu"
)
TEST_RECIPIENT_ALLOWLIST = [
    email.strip().lower()
    for email in os.getenv("TEST_RECIPIENT_ALLOWLIST", "").split(",")
    if email.strip()
]

# Twilio SMS Settings
TWILIO_ENABLED = os.getenv("TWILIO_ENABLED", "false").lower() in ("true", "1", "yes")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")

# Simulation Mode (for testing without live network calls)
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")