"""Top-level API routing."""

from fastapi import APIRouter

from apps.api.app.api.health import router as health_router
from apps.api.app.identity.api import router as identity_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(identity_router)
