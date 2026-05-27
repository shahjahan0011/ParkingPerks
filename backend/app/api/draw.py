"""
POST /api/draw          — run the cryptographic monthly draw
POST /api/draw/resolve-email — manager supplies a missing email for a winner
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core.draw import secure_draw
from app.core.qualify import run_qualification
from app.email.notify import send_winner_notifications
from app.integrations.genetec import GenetecClient
from app.integrations.t2_flex import T2FlexClient
from app.integrations.t2_iris import T2IrisClient
from app.store import csv_store

router = APIRouter()


class DrawRequest(BaseModel):
    year: int
    month: int
    num_winners: int = settings.num_winners
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


class ResolveEmailRequest(BaseModel):
    month: str
    plate: str
    email: str
    actor: str


@router.post("/draw", response_model=DrawResponse)
async def draw(req: DrawRequest) -> DrawResponse:
    if not (1 <= req.month <= 12):
        raise HTTPException(400, "month must be 1–12")

    month_str = f"{req.year}-{req.month:02d}"

    existing = csv_store.get_draw_by_month(month_str)
    if existing:
        _verify_manager_code(req.manager_code)

    reads     = await GenetecClient().fetch_reads(req.year, req.month)
    payments  = await T2IrisClient().fetch_payments(req.year, req.month)
    citations = await T2FlexClient().fetch_citations(req.year, req.month)
    permits   = await T2FlexClient().fetch_permits()

    qualifiers, summary = run_qualification(reads, payments, citations, permits)

    if not qualifiers:
        raise HTTPException(422, f"No qualifiers found for {month_str}.")
    if req.num_winners > len(qualifiers):
        raise HTTPException(
            422,
            f"Requested {req.num_winners} winners but only {len(qualifiers)} qualifiers.",
        )

    winners = secure_draw(qualifiers, req.num_winners)
    drawn_at = datetime.now(timezone.utc)

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
        details={"winners": [w["plate"] for w in winners], "pool_size": len(qualifiers)},
    )

    missing = [w["plate"] for w in winners if not w.get("email")]
    for plate in missing:
        csv_store.add_missing_email(month_str, plate)

    if not missing:
        await send_winner_notifications(winners, month_str)

    return DrawResponse(
        month=month_str,
        drawn_at=drawn_at.isoformat(),
        winners=[WinnerOut(**w) for w in winners],
        pool_size=len(qualifiers),
        is_redraw=bool(existing),
        missing_emails=missing,
    )


@router.post("/draw/resolve-email")
async def resolve_email(req: ResolveEmailRequest) -> dict:
    """Manager supplies a missing email for a payment-track winner."""
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

    if not csv_store.has_unresolved_missing_emails(req.month):
        draw = csv_store.get_draw_by_month(req.month)
        if draw:
            resolved_map = csv_store.get_resolved_email_map(req.month)
            enriched = [
                {**w, "email": resolved_map.get(w["plate"], w.get("email"))}
                for w in draw["winners"]
            ]
            await send_winner_notifications(enriched, req.month)

    return {"status": "resolved", "plate": req.plate}


def _verify_manager_code(code: str | None) -> None:
    if not code:
        raise HTTPException(
            403, "This month has already been drawn. Manager code required to redraw."
        )
    if not hmac.compare_digest(code, settings.manager_code):
        raise HTTPException(403, "Invalid manager code.")
