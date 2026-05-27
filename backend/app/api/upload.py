"""
POST /api/upload/reads

Accepts a plate-reads .xlsx file from the frontend.
Saves it to the uploads directory so the Genetec stub loader can pick it up
on the next /api/analyze or /api/draw call.

This endpoint exists because Genetec plate reads still come from a manual
monthly export. Once the live Genetec API is implemented this endpoint
becomes unnecessary.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File

from app.config import settings

router = APIRouter()

_MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/upload/reads")
async def upload_reads(file: UploadFile = File(...)) -> dict:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "File must be an .xlsx spreadsheet.")

    contents = await file.read()
    if len(contents) > _MAX_SIZE_BYTES:
        raise HTTPException(413, f"File too large (max 50 MB).")

    uploads_dir = Path(settings.uploads_dir)
    uploads_dir.mkdir(parents=True, exist_ok=True)

    dest = uploads_dir / "plate_reads.xlsx"
    dest.write_bytes(contents)

    return {
        "status": "ok",
        "filename": file.filename,
        "size_bytes": len(contents),
        "stored_as": str(dest),
    }
