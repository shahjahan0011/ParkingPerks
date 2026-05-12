"""
GET  /api/history           — list all draw records
GET  /api/history/{month}   — single month draw record
GET  /api/history/{month}/missing-emails — unresolved missing emails for a month
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import DrawHistory, MissingEmailQueue

router = APIRouter()


class DrawSummary(BaseModel):
    id: int
    month: str
    drawn_at: str
    drawn_by: str
    num_winners: int
    pool_size: int
    is_redraw: bool
    winners: list[dict]


class MissingEmailItem(BaseModel):
    plate: str
    resolved: bool
    email: str | None


@router.get("/history", response_model=list[DrawSummary])
async def list_history(db: AsyncSession = Depends(get_db)) -> list[DrawSummary]:
    result = await db.execute(select(DrawHistory).order_by(DrawHistory.drawn_at.desc()))
    return [_to_summary(row) for row in result.scalars()]


@router.get("/history/{month}", response_model=DrawSummary)
async def get_history(month: str, db: AsyncSession = Depends(get_db)) -> DrawSummary:
    row = await db.scalar(
        select(DrawHistory).where(DrawHistory.month == month).order_by(DrawHistory.id.desc())
    )
    if not row:
        raise HTTPException(404, f"No draw record found for {month}.")
    return _to_summary(row)


@router.get("/history/{month}/missing-emails", response_model=list[MissingEmailItem])
async def get_missing_emails(month: str, db: AsyncSession = Depends(get_db)) -> list[MissingEmailItem]:
    result = await db.execute(
        select(MissingEmailQueue).where(MissingEmailQueue.month == month)
    )
    return [
        MissingEmailItem(plate=r.plate, resolved=r.resolved, email=r.email)
        for r in result.scalars()
    ]


def _to_summary(row: DrawHistory) -> DrawSummary:
    return DrawSummary(
        id=row.id,
        month=row.month,
        drawn_at=row.drawn_at.isoformat(),
        drawn_by=row.drawn_by,
        num_winners=row.num_winners,
        pool_size=row.pool_size,
        is_redraw=row.is_redraw,
        winners=row.winners,
    )
