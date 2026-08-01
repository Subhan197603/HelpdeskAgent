"""Process and dependency health endpoints."""

import asyncio
import time
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from apps.api.app.core.context import RequestContext
from apps.api.app.core.settings import Settings
from apps.api.app.dependencies.request_context import get_request_context
from apps.api.app.infrastructure.health import ApplicationResources, HealthProbe

router = APIRouter(tags=["health"])


class DependencyHealth(BaseModel):
    status: Literal["healthy", "unhealthy", "disabled"]
    required: bool
    duration_ms: float


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    service: str
    environment: str
    version: str
    dependencies: dict[str, DependencyHealth]
    duration_ms: float
    correlation_id: str


async def _check(probe: HealthProbe, *, required: bool) -> DependencyHealth:
    started = time.perf_counter()
    healthy = await probe.check()
    return DependencyHealth(
        status="healthy" if healthy else "unhealthy",
        required=required,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
    )


@router.get("/health/live", response_model=HealthResponse)
async def liveness(
    request: Request, context: Annotated[RequestContext, Depends(get_request_context)]
) -> HealthResponse:
    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        environment=settings.app_env.value,
        version=settings.app_version,
        dependencies={},
        duration_ms=0.0,
        correlation_id=context.correlation_id,
    )


@router.get("/api/v1/health", response_model=HealthResponse)
@router.get("/health/ready", response_model=HealthResponse)
async def readiness(
    request: Request,
    response: Response,
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> HealthResponse:
    started = time.perf_counter()
    settings: Settings = request.app.state.settings
    resources: ApplicationResources = request.app.state.resources
    names: list[str] = ["postgresql", "redis"]
    checks = [
        _check(resources.database, required=True),
        _check(resources.redis, required=True),
    ]
    if settings.object_storage_enabled:
        names.append("object_storage")
        checks.append(_check(resources.object_storage, required=True))
    if settings.clamav_required:
        names.append("clamav")
        checks.append(_check(resources.clamav, required=True))
    else:
        names.append("clamav")
        checks.append(_check(resources.clamav, required=False))

    results = dict(zip(names, await asyncio.gather(*checks), strict=True))
    healthy = all(item.status == "healthy" for item in results.values() if item.required)
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="healthy" if healthy else "unhealthy",
        service=settings.app_name,
        environment=settings.app_env.value,
        version=settings.app_version,
        dependencies=results,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        correlation_id=context.correlation_id,
    )
