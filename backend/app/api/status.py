"""
GET /api/status -- one call the UI makes on load to show system state:
which sources are live vs stubbed, whether a reads file is uploaded,
whether email sending is configured, and the default thresholds.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/status")
async def status() -> dict:
    reads_file = Path(settings.uploads_dir) / "plate_reads.xlsx"

    now = datetime.now()
    prev = (now.replace(day=1) - timedelta(days=1))

    return {
        "sources": {
            "reads": {
                "mode": "manual upload (Security Desk export)",
                "uploaded": reads_file.exists(),
                "uploaded_at": (
                    datetime.fromtimestamp(reads_file.stat().st_mtime).isoformat(timespec="seconds")
                    if reads_file.exists() else None
                ),
                "size_bytes": reads_file.stat().st_size if reads_file.exists() else 0,
            },
            "payments": {
                "mode": "stub (test CSV)" if settings.use_stubs_payments else "live (T2 Iris)",
                "live": not settings.use_stubs_payments,
            },
            "citations": {
                "mode": "stub" if settings.use_stubs else "live (T2 Flex)",
                "live": not settings.use_stubs,
            },
            "permits": {
                "mode": "stub (test file)" if settings.use_stubs else "live (T2 Flex)",
                "live": not settings.use_stubs,
            },
        },
        "email_configured": bool(settings.smtp_username and settings.smtp_password),
        "defaults": {
            "min_visits": settings.min_visits,
            "min_hours": settings.min_hours,
            "num_winners": settings.num_winners,
        },
        "suggested_month": {"year": prev.year, "month": prev.month},
    }
