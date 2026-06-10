"""
POST   /api/upload/reads  -- upload the monthly Security Desk reads export
GET    /api/upload/reads  -- info about the currently uploaded file
DELETE /api/upload/reads  -- remove the uploaded file

The upload is parsed immediately and the response reports how many reads it
contains and which calendar months it covers, so the person uploading sees
right away if they exported the wrong month from Security Desk.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.integrations.genetec import ReadsFileError, inspect_reads_file

router = APIRouter()

_MAX_SIZE_BYTES = 200 * 1024 * 1024  # full-month exports run ~60-70 MB


def _dest() -> Path:
    return Path(settings.uploads_dir) / "plate_reads.xlsx"


def _meta_path() -> Path:
    return Path(settings.uploads_dir) / "plate_reads.meta.json"


def _save_meta(dest: Path, info) -> None:
    st = dest.stat()
    _meta_path().write_text(json.dumps({
        "size": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "total_reads": info.total_rows,
        "date_min": info.date_min,
        "date_max": info.date_max,
        "months_covered": info.months_covered,
    }))


def _load_meta(dest: Path) -> dict | None:
    """Return cached stats if they belong to the current file (so the UI's
    info call never re-parses a 60 MB export)."""
    try:
        meta = json.loads(_meta_path().read_text())
        st = dest.stat()
        if meta.get("size") == st.st_size and meta.get("mtime_ns") == st.st_mtime_ns:
            return meta
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


@router.post("/upload/reads")
async def upload_reads(file: UploadFile = File(...)) -> dict:
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(
            400,
            "File must be an .xlsx spreadsheet (the Security Desk reads export).",
        )

    contents = await file.read()
    if len(contents) > _MAX_SIZE_BYTES:
        raise HTTPException(413, "File too large (max 200 MB).")
    if not contents:
        raise HTTPException(400, "Uploaded file is empty.")

    dest = _dest()
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp name first so a failed upload can't clobber a good file.
    tmp = dest.with_suffix(".uploading")
    tmp.write_bytes(contents)

    try:
        # Parsing a 60 MB export takes a while -- keep the event loop free.
        info = await asyncio.to_thread(inspect_reads_file, tmp)
    except ReadsFileError as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise HTTPException(422, f"Could not parse the file: {exc}") from exc

    tmp.replace(dest)
    _save_meta(dest, info)

    return {
        "status": "ok",
        "filename": file.filename,
        "size_bytes": len(contents),
        "total_reads": info.total_rows,
        "date_min": info.date_min,
        "date_max": info.date_max,
        "months_covered": info.months_covered,
    }


@router.get("/upload/reads")
async def reads_info() -> dict:
    dest = _dest()
    if not dest.exists():
        return {"uploaded": False}

    meta = _load_meta(dest)
    if meta is None:
        # File exists but stats are stale (e.g. server restarted mid-upload).
        try:
            info = await asyncio.to_thread(inspect_reads_file, dest)
        except Exception as exc:
            return {"uploaded": True, "error": f"Stored file unreadable: {exc}"}
        _save_meta(dest, info)
        meta = _load_meta(dest)

    return {
        "uploaded": True,
        "size_bytes": dest.stat().st_size,
        "total_reads": meta["total_reads"],
        "date_min": meta["date_min"],
        "date_max": meta["date_max"],
        "months_covered": meta["months_covered"],
    }


@router.delete("/upload/reads")
async def delete_reads() -> dict:
    dest = _dest()
    if dest.exists():
        dest.unlink()
    _meta_path().unlink(missing_ok=True)
    return {"status": "deleted"}
