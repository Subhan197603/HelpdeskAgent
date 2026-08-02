"""Top-level API routing."""

from fastapi import APIRouter

from apps.api.app.api.health import router as health_router
from apps.api.app.catalog.api import router as catalogue_router
from apps.api.app.identity.api import router as identity_router
from apps.api.app.queues.api import router as queues_router
from apps.api.app.routing.api import router as routing_router
from apps.api.app.tickets.api import router as tickets_router
from apps.api.app.workflows.api import router as workflows_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(identity_router)
api_router.include_router(catalogue_router)
api_router.include_router(tickets_router)
api_router.include_router(workflows_router)
api_router.include_router(routing_router)
api_router.include_router(queues_router)
