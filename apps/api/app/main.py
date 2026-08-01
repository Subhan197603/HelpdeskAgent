"""FastAPI application factory and ASGI entry point."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.api.app.api.router import api_router
from apps.api.app.catalog.service import CatalogueMetrics, CatalogueService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.logging import configure_logging
from apps.api.app.core.middleware import RequestContextMiddleware
from apps.api.app.core.problem_details import install_exception_handlers
from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.identity.oidc import AuthenticationMetrics, OidcProviderClient, OidcTokenValidator
from apps.api.app.identity.oidc_service import OidcIdentityService
from apps.api.app.identity.service import DeveloperIdentityService
from apps.api.app.infrastructure.clamav_health import ClamAVHealthProbe
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.infrastructure.object_storage_health import ObjectStorageHealthProbe
from apps.api.app.infrastructure.redis_health import RedisHealthProbe
from apps.api.app.tickets.service import TicketMetrics, TicketService

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
    authentication_metrics = AuthenticationMetrics()
    oidc_provider = (
        OidcProviderClient(settings, authentication_metrics) if settings.oidc_enabled else None
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            if oidc_provider is not None:
                await oidc_provider.close()
            await resources.close()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Foundation API for the Fusion AI Helpdesk modular monolith.",
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_tags=[
            {"name": "health", "description": "Process and dependency health."},
            {"name": "identity", "description": "Authenticated caller identity."},
            {
                "name": "catalogue",
                "description": "Published service catalogue and request forms.",
            },
            {"name": "tickets", "description": "Ticket drafts and confirmed submissions."},
        ],
    )
    app.state.settings = settings
    app.state.resources = resources
    app.state.authentication_metrics = authentication_metrics
    app.state.catalogue_metrics = CatalogueMetrics()
    app.state.ticket_metrics = TicketMetrics()

    def unit_of_work_factory(context: RequestContext) -> SqlAlchemyUnitOfWork:
        database = cast(Database, resources.database)
        return SqlAlchemyUnitOfWork(
            database.session_factory,
            context,
            rls_enabled=settings.rls_enabled,
        )

    app.state.developer_identity_service = DeveloperIdentityService(
        unit_of_work_factory, rls_enabled=settings.rls_enabled
    )
    app.state.oidc_provider = oidc_provider
    app.state.oidc_identity_service = (
        OidcIdentityService(
            settings,
            OidcTokenValidator(settings, oidc_provider, authentication_metrics),
            unit_of_work_factory,
            authentication_metrics,
        )
        if oidc_provider is not None
        else None
    )
    app.state.authorization_service = AuthorizationService()
    app.state.catalogue_service = CatalogueService(
        unit_of_work_factory,
        app.state.authorization_service,
        app.state.catalogue_metrics,
    )
    app.state.ticket_service = TicketService(
        unit_of_work_factory, app.state.authorization_service, app.state.ticket_metrics
    )
    install_exception_handlers(app)
    app.include_router(api_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-Correlation-ID",
            "Idempotency-Key",
            "If-Match",
            *(["Authorization"] if settings.oidc_enabled else []),
            *([settings.developer_identity_header] if settings.developer_identity_enabled else []),
        ],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)
    return app


app = create_app()
