"""
Winner notification emails via UBC SMTP (Exchange).

Sends one email per winner. If the winner has no email (payment-track
without a permit record), the draw endpoint queues them in MissingEmailQueue
instead of calling this function.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings


async def send_winner_notifications(winners: list[dict], month_label: str) -> None:
    """Send congratulatory emails to all winners that have an email address."""
    for winner in winners:
        email = winner.get("email")
        if not email:
            continue
        # smtplib is synchronous blocking I/O — run it in a thread so we
        # don't block the asyncio event loop.
        await asyncio.to_thread(
            _send,
            to=email,
            subject=f"Congratulations — Parking Perks Winner ({month_label})",
            body=_build_body(winner, month_label),
        )


def _build_body(winner: dict, month_label: str) -> str:
    name = winner.get("name") or "Parking Perks Participant"
    track = winner.get("track", "")
    track_msg = (
        "as a UBC parking permit holder"
        if track == "permit"
        else "for consistently parking on campus this month"
    )

    return f"""\
Dear {name},

Congratulations! You have been selected as a Parking Perks winner for {month_label}.

You qualified {track_msg}.

A member of the UBC Parking Services team will be in touch shortly with
details about your prize.

Thank you for being a valued member of the UBC Okanagan community.

Best regards,
UBC Okanagan Parking Services
{settings.email_from}
"""


def _send(to: str, subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{settings.email_from_name} <{settings.email_from}>"
    msg["To"]      = to

    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(settings.email_from, [to], msg.as_string())
