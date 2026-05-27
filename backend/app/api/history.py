"""
GET  /api/history                        — list all draw records (newest first)
GET  /api/history/{month}                — single month draw record
GET  /api/history/{month}/missing-emails — missing-email queue for a month
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.store import csv_store

router = APIRouter()


class DrawSummary(BaseModel):
    id: int
    month: str
    drawn_at: str
    drawn_by: str
    num_winners: int
    pool_size: int
    is_redraw: bool
    winners: list[dict[str, Any]]


class MissingEmailItem(BaseModel):
    plate: str
    resolved: bool
    email: str | None


@router.get("/history", response_model=list[DrawSummary])
async def list_history() -> list[DrawSummary]:
    rows = csv_store.get_all_draws()
    rows.sort(key=lambda r: r["drawn_at"], reverse=True)
    return [_to_summary(r) for r in rows]


@router.get("/history/{month}", response_model=DrawSummary)
async def get_history(month: str) -> DrawSummary:
    row = csv_store.get_draw_by_month(month)
    if not row:
        raise HTTPException(404, f"No draw record found for {month}.")
    return _to_summary(row)


@router.get("/history/{month}/missing-emails", response_model=list[MissingEmailItem])
async def get_missing_emails(month: str) -> list[MissingEmailItem]:
    items = csv_store.get_missing_emails(month)
    return [MissingEmailItem(**item) for item in items]


def _to_summary(row: dict) -> DrawSummary:
    return DrawSummary(
        id=row["id"],
        month=row["month"],
        drawn_at=row["drawn_at"],
        drawn_by=row["drawn_by"],
        num_winners=row["num_winners"],
        pool_size=row["pool_size"],
        is_redraw=row["is_redraw"],
        winners=row["winners"],
    )
