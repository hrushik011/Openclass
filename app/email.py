"""Openclass platform email delivery via Resend."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import resend

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("openclass.email")

PLATFORM_FROM = "Openclass Updates <updates@useopenclass.in>"


def _configure_resend() -> bool:
    key = (os.getenv("RESEND_API_KEY") or "").strip()
    if key:
        resend.api_key = key
        return True
    return False


_configure_resend()


def send_platform_email(to_email: str, subject: str, html_content: str) -> Optional[Any]:
    """Send one HTML message through Resend. Returns API response dict or None on failure."""
    recipient = str(to_email or "").strip()
    if not recipient or "@" not in recipient:
        logger.warning("send_platform_email skipped: invalid recipient %r", to_email)
        print(f"send_platform_email skipped: invalid recipient {to_email!r}", flush=True)
        return None

    if not _configure_resend():
        logger.error("send_platform_email aborted: RESEND_API_KEY is not configured")
        print("send_platform_email aborted: RESEND_API_KEY is not configured", flush=True)
        return None

    params = {
        "from": PLATFORM_FROM,
        "to": [recipient],
        "subject": str(subject or "Openclass update").strip() or "Openclass update",
        "html": html_content or "<p>Openclass notification</p>",
    }
    logger.info("Resend dispatch start to=%s subject=%r from=%s", recipient, params["subject"], PLATFORM_FROM)
    print(
        f"Resend dispatch start to={recipient} subject={params['subject']!r} from={PLATFORM_FROM}",
        flush=True,
    )
    try:
        response = resend.Emails.send(params)
        logger.info("Resend dispatch success to=%s response=%s", recipient, response)
        print(f"Resend dispatch success to={recipient} response={response}", flush=True)
        return response
    except Exception as exc:
        logger.exception("Resend dispatch failed to=%s: %s", recipient, exc)
        print(f"Resend dispatch failed to={recipient}: {exc}", flush=True)
        return None


__all__ = ["send_platform_email", "PLATFORM_FROM"]
