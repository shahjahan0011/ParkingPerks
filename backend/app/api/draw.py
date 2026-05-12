"""
POST /api/draw

Runs the cryptographic draw on a qualifier pool.
A month can only be drawn once. Re-drawing requires the manager code.

POST /api/draw/resolve-email
Lets the manager supply a missing email for a payment-track winner.
"""

from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.draw import secure_draw
from app.core.qualify import run_qualification
from app.db.database import get_db
from app.db.models import AuditLog, DrawHistory, MissingEmailQueue
from app.email.notify import send_winner_notifications
from app.integrations.genetec import GenetecClient
from app.integrations.t2_flex import T2FlexClient
from app.integrations.t2_iris import T2IrisClient

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
async def draw(req: DrawRequest, db: AsyncSession = Depends(get_db)) -> DrawResponse:
    if not (1 <= req.month <= 12):
        raise HTTPException(400, "month must be 1–12")

    month_str = f"{req.year}-{req.month:02d}"

    existing = await db.scalar(
        select(DrawHistory).where(DrawHistory.month == month_str).limit(1)
    )

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

    record = DrawHistory(
        month=month_str,
        drawn_at=drawn_at,
        drawn_by=req.actor,
        num_winners=req.num_winners,
        winners=winners,
        pool_size=len(qualifiers),
        is_redraw=bool(existing),
        summary=summary,
    )
    db.add(record)

    db.add(AuditLog(
        action="redraw" if existing else "draw",
        month=month_str,
        actor=req.actor,
        details={"winners": [w["plate"] for w in winners], "pool_size": len(qualifiers)},
    ))

    missing = [w["plate"] for w in winners if not w.get("email")]
    for plate in missing:
        db.add(MissingEmailQueue(month=month_str, plate=plate))

    await db.commit()

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
async def resolve_email(req: ResolveEmailRequest, db: AsyncSession = Depends(get_db)) -> dict:
    """Manager supplies a missing email for a payment-track winner."""
    entry = await db.scalar(
        select(MissingEmailQueue).where(
            MissingEmailQueue.month == req.month,
            MissingEmailQueue.plate == req.plate,
            MissingEmailQueue.resolved == False,  # noqa: E712
        )
    )
    if not entry:
        raise HTTPException(404, "No unresolved missing-email entry for that plate/month.")

    entry.email = req.email
    entry.resolved = True
    entry.resolved_by = req.actor
    entry.resolved_at = datetime.now(timezone.utc)

    db.add(AuditLog(
        action="email_resolved",
        month=req.month,
        actor=req.actor,
        details={"plate": req.plate, "email": req.email},
    ))

    await db.commit()

    remaining = await db.scalar(
        select(MissingEmailQueue).where(
            MissingEmailQueue.month == req.month,
            MissingEmailQueue.resolved == False,  # noqa: E712
        )
    )

    if not remaining:
        history = await db.scalar(
            select(DrawHistory).where(DrawHistory.month == req.month).order_by(DrawHistory.id.desc())
        )
        if history:
            enriched = _enrich_winners_with_resolved_emails(
                history.winners, await _load_resolved_emails(db, req.month)
            )
            await send_winner_notifications(enriched, req.month)

    return {"status": "resolved", "plate": req.plate}


def _verify_manager_code(code: str | None) -> None:
    if not code:
        raise HTTPException(403, "This month has already been drawn. Manager code required to redraw.")
    if not hmac.compare_digest(code, settings.manager_code):
        raise HTTPException(403, "Invalid manager code.")


def _enrich_winners_with_resolved_emails(
    winners: list[dict], resolved: dict[str, str]
) -> list[dict]:
    return [{**w, "email": resolved.get(w["plate"], w.get("email"))} for w in winners]


async def _load_resolved_emails(db: AsyncSession, month: str) -> dict[str, str]:
    result = await db.execute(
        select(MissingEmailQueue).where(
            MissingEmailQueue.month == month,
            MissingEmailQueue.resolved == True,  # noqa: E712
        )
    )
    return {row.plate: row.email for row in result.scalars()}
