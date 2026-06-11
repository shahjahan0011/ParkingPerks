from fastapi import APIRouter

from app.api import analyze, draw, history, ingest, status, upload

api_router = APIRouter(prefix="/api")
api_router.include_router(status.router,  tags=["status"])
api_router.include_router(ingest.router,  tags=["ingest"])
api_router.include_router(upload.router,  tags=["upload"])
api_router.include_router(analyze.router, tags=["analyze"])
api_router.include_router(draw.router,    tags=["draw"])
api_router.include_router(history.router, tags=["history"])
