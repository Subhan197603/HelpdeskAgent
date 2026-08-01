"""FastAPI application factory and ASGI entry point."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.api.app.api.router import api_router
from apps.api.app.core.logging import configure_logging
from apps.api.app.core.middleware import RequestContextMiddleware
from apps.api.app.core.problem_details import install_exception_handlers
from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.infrastructure.clamav_health import ClamAVHealthProbe
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.infrastructure.object_storage_health import ObjectStorageHealthProbe
from apps.api.app.infrastructure.redis_health import RedisHealthProbe

ResourceFactory = Callable[[Settings], ApplicationResources]


def create_resources(settings: Settings) -> ApplicationResources:
    return ApplicationResources(
        database=Database(settings),
        redis=RedisHealthProbe(settings.redis_url.get_secret_value()),
        object_storage=ObjectStorageHealthProbe(settings.object_storage_endpoint),
        clamav=ClamAVHealthProbe(settings.clamav_host, settings.clamav_port),
    )


def create_app(
    settings: Settings | None = None, *, resource_factory: ResourceFactory = create_resources
) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings)
    resources = resource_factory(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await resources.close()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Foundation API for the Fusion AI Helpdesk modular monolith.",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_tags=[{"name": "health", "description": "Process and dependency health."}],
    )
    app.state.settings = settings
    app.state.resources = resources
    install_exception_handlers(app)
    app.include_router(api_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Content-Type", "X-Correlation-ID"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    return app


app = create_app()
