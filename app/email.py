import logging
import os
from datetime import datetime, timedelta
from email.utils import format_datetime
from typing import Any, Mapping, Optional
from zoneinfo import ZoneInfo

import resend

logger = logging.getLogger("openclass.email")

PLATFORM_FROM = "Openclass Updates <updates@useopenclass.in>"
IST = ZoneInfo("Asia/Kolkata")

_resend_key = os.getenv("RESEND_API_KEY")
if _resend_key:
    resend.api_key = _resend_key

# Resend tag `category` values for inbox filtering / analytics
CATEGORY_LIVE_CLASS = "live_class_alert"
CATEGORY_CLASS_SCHEDULED = "class_scheduled"
CATEGORY_ASSIGNMENT_NEW = "assignment_published"
CATEGORY_ASSIGNMENT_REMINDER = "assignment_reminder"
CATEGORY_ANNOUNCEMENT = "announcement"
CATEGORY_TEST = "test"


def _format_mail_date(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return format_datetime(dt, usegmt=False)


def build_email_tags(category: str, **extra: str) -> list[dict[str, str]]:
    tags = [{"name": "category", "value": category}, {"name": "source", "value": "openclass"}]
    for key, value in extra.items():
        text = str(value or "").strip()
        if text:
            tags.append({"name": str(key)[:40], "value": text[:80]})
    return tags


def live_class_alert_headers(*, expires_at: Optional[datetime] = None) -> dict[str, str]:
    """Short-lived meeting notice — helps clients treat mail as time-sensitive."""
    exp = expires_at or (datetime.now(IST) + timedelta(hours=2))
    return {
        "Auto-Submitted": "auto-generated",
        "X-Auto-Response-Suppress": "All",
        "Precedence": "bulk",
        "Expires": _format_mail_date(exp),
        "X-Openclass-Notice": "live-class-alert",
    }


def assignment_notice_headers(*, deadline_iso: Optional[str] = None) -> dict[str, str]:
    headers = {
        "X-Openclass-Notice": "assignment",
        "Auto-Submitted": "auto-generated",
    }
    if deadline_iso:
        headers["X-Openclass-Deadline"] = str(deadline_iso)[:80]
    return headers


def prefix_subject(label: str, subject: str) -> str:
    text = str(subject or "").strip()
    prefix = str(label or "").strip()
    if not prefix:
        return text or "Openclass update"
    if text.upper().startswith(prefix.upper()):
        return text
    return f"{prefix} {text}"


def send_platform_email(
    to_email: str,
    subject: str,
    html_content: str,
    *,
    category: Optional[str] = None,
    tags: Optional[list[dict[str, str]]] = None,
    headers: Optional[Mapping[str, str]] = None,
    expires_at: Optional[datetime] = None,
) -> Optional[Any]:
    """Send one HTML message through Resend with optional tags and retention headers."""
    recipient = str(to_email or "").strip()
    if not recipient or "@" not in recipient:
        logger.warning("send_platform_email skipped: invalid recipient %r", to_email)
        print(f"send_platform_email skipped: invalid recipient {to_email!r}", flush=True)
        return None

    if not resend.api_key:
        logger.error("send_platform_email aborted: RESEND_API_KEY is not configured")
        print("send_platform_email aborted: RESEND_API_KEY is not configured", flush=True)
        return None

    merged_headers: dict[str, str] = {}
    if headers:
        merged_headers.update({str(k): str(v) for k, v in headers.items() if v is not None})
    if expires_at and "Expires" not in merged_headers:
        merged_headers["Expires"] = _format_mail_date(expires_at)

    merged_tags = list(tags or [])
    if category and not any(t.get("name") == "category" for t in merged_tags):
        merged_tags = build_email_tags(category) + merged_tags

    params: dict[str, Any] = {
        "from": PLATFORM_FROM,
        "to": [recipient],
        "subject": str(subject or "Openclass update").strip() or "Openclass update",
        "html": html_content or "<p>Openclass notification</p>",
    }
    if merged_tags:
        params["tags"] = merged_tags
    if merged_headers:
        params["headers"] = merged_headers

    meta = {
        "category": category,
        "tags": merged_tags,
        "headers": list(merged_headers.keys()),
    }
    logger.info(
        "Resend dispatch start to=%s subject=%r category=%s headers=%s",
        recipient,
        params["subject"],
        category,
        meta["headers"],
    )
    print(
        f"Resend dispatch start to={recipient} subject={params['subject']!r} "
        f"category={category!r} headers={meta['headers']}",
        flush=True,
    )
    try:
        response = resend.Emails.send(params)
        logger.info("Resend dispatch success to=%s response=%s", recipient, response)
        print(f"Resend dispatch success to={recipient} response={response}", flush=True)
        return response
    except Exception as exc:
        logger.exception("Resend dispatch failed to=%s error=%s", recipient, exc)
        print(f"Resend dispatch failed to={recipient} error={exc}", flush=True)
        return None
