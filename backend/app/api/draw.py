"""
POST /api/draw               -- run the cryptographic monthly draw
POST /api/draw/resolve-email -- manager supplies a missing email for a winner

The draw re-fetches all sources and re-runs qualification at draw time (the
saved pool is exactly what was drawn from -- no stale data). It accepts the
same min_visits/min_hours as /api/analyze so the drawn pool always matches
the pool the staff member just reviewed.
"""

from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core.draw import secure_draw
from app.core.qualify import run_qualification
from app.core.sources import SourceError, fetch_all_sources
from app.email.notify import send_winner_notifications
from app.store import csv_store

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_WINNERS = 50


class DrawRequest(BaseModel):
    year: int
    month: int
    num_winners: int = settings.num_winners
    min_visits: int = settings.min_visits
    min_hours: float = settings.min_hours
    actor: str
    manager_code: str | None = None


class WinnerOut(BaseModel):
    plate: str
    name: str
    email: str | None
    permit_number: str | None
    track: str


class DrawResponse(BaseModel):
    month: str
    drawn_at: str
    winners: list[WinnerOut]
    pool_size: int
    is_redraw: bool
    missing_emails: list[str]
    email_status: str


class ResolveEmailRequest(BaseModel):
    month: str
    plate: str
    email: str
    actor: str


@router.post("/draw", response_model=DrawResponse)
async def draw(req: DrawRequest) -> DrawResponse:
    if not (1 <= req.month <= 12):
        raise HTTPException(400, "month must be 1-12")
    if not (1 <= req.num_winners <= _MAX_WINNERS):
        raise HTTPException(400, f"num_winners must be 1-{_MAX_WINNERS}")
    if not req.actor.strip():
        raise HTTPException(400, "actor (your name) is required for the audit log")

    month_str = f"{req.year}-{req.month:02d}"

    existing = csv_store.get_draw_by_month(month_str)
    if existing:
        _verify_manager_code(req.manager_code)

    try:
        reads, payments, citations, permits = await fetch_all_sources(req.year, req.month)
    except SourceError as exc:
        raise HTTPException(422, f"[{exc.source}] {exc}") from exc

    qualifiers, summary = run_qualification(
        reads, payments, citations, permits,
        min_visits=req.min_visits,
        min_hours=req.min_hours,
    )

    if not qualifiers:
        raise HTTPException(422, f"No qualifiers found for {month_str}.")
    if req.num_winners > len(qualifiers):
        raise HTTPException(
            422,
            f"Requested {req.num_winners} winners but only {len(qualifiers)} qualifiers.",
        )

    winners = secure_draw(qualifiers, req.num_winners)
    drawn_at = datetime.now(timezone.utc)

    # Persist FIRST -- a draw must never be lost because an email failed.
    csv_store.save_draw(
        month=month_str,
        drawn_at=drawn_at,
        drawn_by=req.actor,
        num_winners=req.num_winners,
        pool_size=len(qualifiers),
        is_redraw=bool(existing),
        winners=winners,
    )

    csv_store.append_audit(
        action="redraw" if existing else "draw",
        month=month_str,
        actor=req.actor,
        details={
            "winners": [w["plate"] for w in winners],
            "pool_size": len(qualifiers),
            "min_visits": req.min_visits,
            "min_hours": req.min_hours,
        },
    )

    missing = [w["plate"] for w in winners if not w.get("email")]
    for plate in missing:
        csv_store.add_missing_email(month_str, plate)

    email_status = "skipped: SMTP not configured"
    if missing:
        email_status = (
            f"held: {len(missing)} winner(s) have no email on file -- "
            "resolve below, then emails go out"
        )
    elif settings.smtp_username and settings.smtp_password:
        try:
            await send_winner_notifications(winners, month_str)
            email_status = f"sent to {len(winners)} winner(s)"
        except Exception as exc:
            logger.exception("Winner notification emails failed")
            email_status = f"FAILED to send ({exc}) -- the draw is saved; notify winners manually"

    return DrawResponse(
        month=month_str,
        drawn_at=drawn_at.isoformat(),
        winners=[WinnerOut(**w) for w in winners],
        pool_size=len(qualifiers),
        is_redraw=bool(existing),
        missing_emails=missing,
        email_status=email_status,
    )


@router.post("/draw/resolve-email")
async def resolve_email(req: ResolveEmailRequest) -> dict:
    """Manager supplies a missing email for a payment-track winner."""
    if "@" not in req.email or "." not in req.email.split("@")[-1]:
        raise HTTPException(400, "That doesn't look like a valid email address.")

    resolved = csv_store.resolve_missing_email(
        month=req.month,
        plate=req.plate,
        email=req.email,
        resolved_by=req.actor,
    )
    if not resolved:
        raise HTTPException(404, "No unresolved missing-email entry for that plate/month.")

    csv_store.append_audit(
        action="email_resolved",
        month=req.month,
        actor=req.actor,
        details={"plate": req.plate, "email": req.email},
    )

    email_status = "pending"
    if not csv_store.has_unresolved_missing_emails(req.month):
        draw_row = csv_store.get_draw_by_month(req.month)
        if draw_row and settings.smtp_username and settings.smtp_password:
            resolved_map = csv_store.get_resolved_email_map(req.month)
            enriched = [
                {**w, "email": resolved_map.get(w["plate"], w.get("email"))}
                for w in draw_row["winners"]
            ]
            try:
                await send_winner_notifications(enriched, req.month)
                email_status = "all winner emails sent"
            except Exception as exc:
                logger.exception("Winner notification emails failed")
                email_status = f"FAILED to send ({exc}) -- notify winners manually"
        elif draw_row:
            email_status = "all emails resolved; SMTP not configured, notify manually"

    return {"status": "resolved", "plate": req.plate, "email_status": email_status}


def _verify_manager_code(code: str | None) -> None:
    if not code:
        raise HTTPException(
            403, "This month has already been drawn. Manager code required to redraw."
        )
    if not hmac.compare_digest(code, settings.manager_code):
        raise HTTPException(403, "Invalid manager code.")
