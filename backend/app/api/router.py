from fastapi import APIRouter

from app.api import analyze, draw, history, upload

api_router = APIRouter(prefix="/api")
api_router.include_router(analyze.router, tags=["analyze"])
api_router.include_router(draw.router,    tags=["draw"])
api_router.include_router(history.router, tags=["history"])
api_router.include_router(upload.router,  tags=["upload"])
