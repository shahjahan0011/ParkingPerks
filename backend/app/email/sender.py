"""
Pluggable email sending. Backend chosen by EMAIL_BACKEND in .env:

    gmail -- Gmail API with an OAuth2 refresh token (no password stored).
             Needs GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN,
             GMAIL_SENDER. One-time setup: python gmail_auth_setup.py
    smtp  -- classic SMTP (UBC Exchange), SMTP_USERNAME/SMTP_PASSWORD.
    none  -- sending disabled; send_email() raises EmailNotConfigured.

The Gmail path uses plain HTTPS (httpx) -- no Google SDK:
    1. POST https://oauth2.googleapis.com/token   refresh -> access token
    2. POST gmail/v1/users/me/messages/send       {"raw": base64url(MIME)}
"""

from __future__ import annotations

import base64
import logging
import smtplib
from email.message import EmailMessage

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class EmailNotConfigured(RuntimeError):
    pass


def email_is_configured() -> bool:
    if settings.email_backend == "gmail":
        return bool(settings.gmail_client_id and settings.gmail_client_secret
                    and settings.gmail_refresh_token and settings.gmail_sender)
    if settings.email_backend == "smtp":
        return bool(settings.smtp_username and settings.smtp_password)
    return False


def send_email(
    to: list[str],
    subject: str,
    body: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    """Synchronous send (callers wrap in asyncio.to_thread if needed).
    attachments = [(filename, content_bytes, mime_type)]."""
    if not email_is_configured():
        raise EmailNotConfigured(
            f"EMAIL_BACKEND={settings.email_backend!r} is not fully configured in .env"
        )

    msg = _build_message(to, subject, body, attachments or [])

    if settings.email_backend == "gmail":
        _send_gmail(msg)
    else:
        _send_smtp(msg, to)

    logger.info("Email sent to %s: %s", ", ".join(to), subject)


def _build_message(
    to: list[str], subject: str, body: str,
    attachments: list[tuple[str, bytes, str]],
) -> EmailMessage:
    msg = EmailMessage()
    sender = (settings.gmail_sender if settings.email_backend == "gmail"
              else settings.email_from)
    msg["From"] = f"{settings.email_from_name} <{sender}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)

    for filename, content, mime in attachments:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(content, maintype=maintype, subtype=subtype or "octet-stream",
                           filename=filename)
    return msg


# ---------------------------------------------------------------------------
# Gmail backend
# ---------------------------------------------------------------------------

def _gmail_access_token() -> str:
    resp = httpx.post(_GOOGLE_TOKEN_URL, data={
        "client_id": settings.gmail_client_id,
        "client_secret": settings.gmail_client_secret,
        "refresh_token": settings.gmail_refresh_token,
        "grant_type": "refresh_token",
    }, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Gmail token refresh failed ({resp.status_code}): {resp.text[:300]}. "
            "If this says 'invalid_grant', re-run gmail_auth_setup.py to get a "
            "fresh refresh token."
        )
    return resp.json()["access_token"]


def _send_gmail(msg: EmailMessage) -> None:
    token = _gmail_access_token()
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    resp = httpx.post(
        _GMAIL_SEND_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={"raw": raw},
        timeout=60,
    )
    if resp.status_code not in (200, 202):
        raise RuntimeError(
            f"Gmail send failed ({resp.status_code}): {resp.text[:300]}"
        )


# ---------------------------------------------------------------------------
# SMTP backend
# ---------------------------------------------------------------------------

def _send_smtp(msg: EmailMessage, to: list[str]) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg, from_addr=settings.email_from, to_addrs=to)
