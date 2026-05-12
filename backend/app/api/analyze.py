"""
POST /api/analyze

Pulls data from all three systems for a given month, runs the
qualification pipeline, and returns the qualifier list + processing summary.
Does NOT run the draw — that is a separate step requiring manager intent.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.qualify import run_qualification
from app.db.database import get_db
from app.db.models import AuditLog
from app.integrations.genetec import GenetecClient
from app.integrations.t2_flex import T2FlexClient
from app.integrations.t2_iris import T2IrisClient

router = APIRouter()


class AnalyzeRequest(BaseModel):
    year: int
    month: int
    min_visits: int = settings.min_visits
    min_hours: float = settings.min_hours
    actor: str = "system"


class QualifierOut(BaseModel):
    plate: str
    name: str
    email: str | None
    permit_number: str | None
    qualifying_days: int | None
    avg_hours: float | None
    track: str


class AnalyzeResponse(BaseModel):
    month: str
    qualifiers: list[QualifierOut]
    summary: dict
    missing_emails: list[str]


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest, db: AsyncSession = Depends(get_db)) -> AnalyzeResponse:
    if not (1 <= req.month <= 12):
        raise HTTPException(400, "month must be 1–12")
    if req.year < 2020:
        raise HTTPException(400, "year looks wrong")

    reads     = await GenetecClient().fetch_reads(req.year, req.month)
    payments  = await T2IrisClient().fetch_payments(req.year, req.month)
    citations = await T2FlexClient().fetch_citations(req.year, req.month)
    permits   = await T2FlexClient().fetch_permits()

    qualifiers, summary = run_qualification(
        reads, payments, citations, permits,
        min_visits=req.min_visits,
        min_hours=req.min_hours,
    )

    month_str = f"{req.year}-{req.month:02d}"

    db.add(AuditLog(
        action="analyze",
        month=month_str,
        actor=req.actor,
        details={"summary": summary},
    ))
    await db.commit()

    return AnalyzeResponse(
        month=month_str,
        qualifiers=[QualifierOut(**q) for q in qualifiers],
        summary=summary,
        missing_emails=summary.get("missing_emails", []),
    )
