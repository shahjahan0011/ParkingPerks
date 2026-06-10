"""
POST /api/analyze

Pulls data from all sources for a given month, runs the qualification
pipeline, and returns the qualifier list + processing summary.
Does NOT run the draw - that is a separate step requiring manager intent.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.core.qualify import run_qualification
from app.core.sources import SourceError, fetch_all_sources
from app.store import csv_store

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
    summary: dict[str, Any]
    missing_emails: list[str]
    warnings: list[str]


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if not (1 <= req.month <= 12):
        raise HTTPException(400, "month must be 1-12")
    if req.year < 2020:
        raise HTTPException(400, "year looks wrong")
    if req.min_visits < 1 or req.min_hours <= 0:
        raise HTTPException(400, "min_visits/min_hours must be positive")

    try:
        reads, payments, citations, permits = await fetch_all_sources(req.year, req.month)
    except SourceError as exc:
        raise HTTPException(422, f"[{exc.source}] {exc}") from exc

    qualifiers, summary = run_qualification(
        reads, payments, citations, permits,
        min_visits=req.min_visits,
        min_hours=req.min_hours,
    )

    month_str = f"{req.year}-{req.month:02d}"

    csv_store.append_audit(
        action="analyze",
        month=month_str,
        actor=req.actor,
        details={"summary": summary},
    )

    return AnalyzeResponse(
        month=month_str,
        qualifiers=[QualifierOut(**q) for q in qualifiers],
        summary=summary,
        missing_emails=summary.get("missing_emails", []),
        warnings=_build_warnings(summary, req),
    )


def _build_warnings(summary: dict, req: AnalyzeRequest) -> list[str]:
    """Sanity flags for things staff should notice before drawing."""
    warnings: list[str] = []

    coverage = summary.get("coverage_days", 0)
    if coverage and coverage < 25:
        warnings.append(
            f"The plate reads file only covers {coverage} day(s) of the month. "
            "A full month should be ~28-31 days -- check that the Security "
            "Desk export covered the whole month."
        )

    if req.min_visits != settings.min_visits or req.min_hours != settings.min_hours:
        warnings.append(
            f"Non-default thresholds in use (visits={req.min_visits}, "
            f"hours={req.min_hours}). Defaults are visits={settings.min_visits}, "
            f"hours={settings.min_hours}."
        )

    if summary.get("citation_plates", 0) == 0:
        warnings.append(
            "Zero citations were found this month. If that seems unlikely, "
            "verify the citations query before drawing."
        )

    if summary.get("stage2_payment", 0) == 0:
        warnings.append(
            "No payment-track qualifiers at all. If the month had normal "
            "traffic this may indicate a payments/plate-matching problem."
        )

    return warnings
