"""
Winner notification emails (used by MANUAL draws from the web UI only --
the automated monthly run emails the manager, never the winners).

Routed through the pluggable sender (gmail / smtp -- see sender.py).
"""

from __future__ import annotations

import asyncio

from app.config import settings
from app.email.sender import send_email


async def send_winner_notifications(winners: list[dict], month_label: str) -> None:
    """Send congratulatory emails to all winners that have an email address."""
    for winner in winners:
        email = winner.get("email")
        if not email:
            continue
        await asyncio.to_thread(
            send_email,
            to=[email],
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
