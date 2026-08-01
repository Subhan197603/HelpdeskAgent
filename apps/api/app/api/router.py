"""Top-level API routing."""

from fastapi import APIRouter

from apps.api.app.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
