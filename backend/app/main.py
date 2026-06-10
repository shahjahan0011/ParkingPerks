"""
Parking Perks -- FastAPI application entry point.

Run locally:
  cd backend
  python -m uvicorn app.main:app

Then open http://localhost:8000  (the full staff UI is served at /).
API docs: http://localhost:8000/docs

NOTE: There is intentionally NO automatic monthly draw. The workflow
requires a staff member to export the plate reads report from Security Desk
and upload it first, so the draw is always human-triggered from the UI.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.router import api_router

app = FastAPI(
    title="Parking Perks API",
    description="UBC Okanagan Parking Services -- monthly qualifier draw",
    version="2.0.0",
)

app.include_router(api_router)

_STATIC_DIR = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}

