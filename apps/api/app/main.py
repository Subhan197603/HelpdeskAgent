"""FastAPI application factory and ASGI entry point."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.api.app.admin.service import AdminService
from apps.api.app.ai.governance_service import AIGovernanceService
from apps.api.app.ai.registry import ProviderRegistry
from apps.api.app.ai.resilience import CircuitBreaker, ResilientProviderExecutor
from apps.api.app.ai.service import AIGateway
from apps.api.app.analyst_copilot.service import AnalystCopilotService, CopilotMetrics
from apps.api.app.api.router import api_router
from apps.api.app.approvals.service import ApprovalService
from apps.api.app.attachments.clamav import ClamAVScanner
from apps.api.app.attachments.service import AttachmentService
from apps.api.app.attachments.storage import S3ObjectStorage
from apps.api.app.catalog.service import CatalogueMetrics, CatalogueService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.logging import configure_logging
from apps.api.app.core.middleware import RequestContextMiddleware
from apps.api.app.core.problem_details import install_exception_handlers
from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.employee_agent.service import EmployeeAgentService
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.identity.oidc import AuthenticationMetrics, OidcProviderClient, OidcTokenValidator
from apps.api.app.identity.oidc_service import OidcIdentityService
from apps.api.app.identity.service import DeveloperIdentityService
from apps.api.app.infrastructure.clamav_health import ClamAVHealthProbe
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.infrastructure.object_storage_health import ObjectStorageHealthProbe
from apps.api.app.infrastructure.redis_health import RedisHealthProbe
from apps.api.app.ingestion.service import IngestionService
from apps.api.app.knowledge.corpus_publication_service import CorpusPublicationService
from apps.api.app.knowledge.corpus_validation_service import CorpusValidationService
from apps.api.app.knowledge.document_service import KnowledgeDocumentService
from apps.api.app.knowledge.reader_service import KnowledgeReaderService
from apps.api.app.knowledge.retrieval_analytics_service import RetrievalAnalyticsService
from apps.api.app.knowledge.service import KnowledgeSourceService
from apps.api.app.notifications.service import NotificationService
from apps.api.app.queues.service import QueueService
from apps.api.app.reporting.service import DashboardService
from apps.api.app.retrieval.providers import (
    DeterministicQueryEmbeddingProvider,
    HttpQueryEmbeddingProvider,
    HttpRerankingProvider,
    QueryEmbeddingProvider,
    RerankingProvider,
)
from apps.api.app.retrieval.service import RetrievalService
from apps.api.app.routing.service import RoutingService
from apps.api.app.tickets.service import TicketMetrics, TicketService
from apps.api.app.workflows.service import WorkflowService

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
            {"name": "workflows", "description": "Deterministic ticket transitions."},
            {"name": "routing", "description": "Deterministic routing and assignment."},
            {"name": "queues", "description": "Analyst queues and immutable activity."},
            {"name": "attachments", "description": "Quarantined and protected ticket files."},
            {"name": "approvals", "description": "Assigned approval decisions."},
            {"name": "notifications", "description": "User notification inbox."},
            {"name": "knowledge-admin", "description": "Governed knowledge sources."},
            {
                "name": "knowledge-ingestion",
                "description": "Governed document acquisition and quarantine.",
            },
            {
                "name": "knowledge-publication",
                "description": "Human-reviewed knowledge corpus publication.",
            },
            {
                "name": "knowledge-evidence",
                "description": "Authorized hybrid retrieval with canonical evidence.",
            },
            {
                "name": "knowledge-articles",
                "description": "Persona-authorized reading of published knowledge articles.",
            },
            {
                "name": "employee-assistant",
                "description": "Authorized retrieval-first employee helpdesk conversations.",
            },
            {
                "name": "analyst-copilot",
                "description": "Analyst-only ticket analysis with authorized evidence.",
            },
            {
                "name": "ai-oversight",
                "description": "Administrator AI usage metrics and evaluation datasets.",
            },
            {
                "name": "ai-governance",
                "description": "Secret-free AI policy, usage, and operational visibility.",
            },
            {
                "name": "administration",
                "description": "Read-only administration overview, status, and audit history.",
            },
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
    app.state.workflow_service = WorkflowService(
        unit_of_work_factory, app.state.authorization_service, app.state.ticket_service
    )
    app.state.approval_service = ApprovalService(
        unit_of_work_factory, app.state.authorization_service
    )
    app.state.notification_service = NotificationService(
        unit_of_work_factory, app.state.authorization_service
    )
    app.state.knowledge_source_service = KnowledgeSourceService(
        unit_of_work_factory, app.state.authorization_service, settings
    )
    app.state.knowledge_document_service = KnowledgeDocumentService(
        unit_of_work_factory, app.state.authorization_service, settings
    )
    app.state.corpus_validation_service = CorpusValidationService(
        unit_of_work_factory, app.state.authorization_service
    )
    app.state.corpus_publication_service = CorpusPublicationService(
        unit_of_work_factory, app.state.authorization_service
    )
    app.state.retrieval_analytics_service = RetrievalAnalyticsService(
        unit_of_work_factory, app.state.authorization_service, settings
    )
    app.state.knowledge_reader_service = KnowledgeReaderService(
        unit_of_work_factory, app.state.authorization_service, settings
    )
    app.state.admin_service = AdminService(unit_of_work_factory, settings, resources)
    app.state.retrieval_service = RetrievalService(
        unit_of_work_factory,
        app.state.authorization_service,
        settings,
        _embedding_provider(settings),
        _reranking_provider(settings),
    )
    circuit_breaker = CircuitBreaker(
        settings.ai_circuit_failure_threshold,
        settings.ai_circuit_recovery_seconds,
    )
    app.state.ai_gateway = AIGateway(
        unit_of_work_factory,
        settings,
        ProviderRegistry(settings),
        ResilientProviderExecutor(
            timeout_seconds=settings.ai_provider_timeout_seconds,
            maximum_attempts=settings.ai_provider_max_attempts,
            circuit_breaker=circuit_breaker,
        ),
    )
    app.state.ai_governance_service = AIGovernanceService(
        unit_of_work_factory, settings, circuit_breaker
    )
    app.state.employee_agent_service = EmployeeAgentService(
        unit_of_work_factory,
        app.state.authorization_service,
        app.state.retrieval_service,
        app.state.ai_gateway,
        settings,
        app.state.ticket_service,
    )
    app.state.ingestion_service = IngestionService(
        unit_of_work_factory,
        app.state.authorization_service,
        S3ObjectStorage(settings),
        settings,
    )
    app.state.routing_service = RoutingService(
        unit_of_work_factory, app.state.authorization_service, app.state.ticket_service
    )
    app.state.queue_service = QueueService(unit_of_work_factory, app.state.authorization_service)
    app.state.dashboard_service = DashboardService(
        unit_of_work_factory, app.state.authorization_service, app.state.queue_service
    )
    app.state.copilot_metrics = CopilotMetrics()
    app.state.analyst_copilot_service = AnalystCopilotService(
        unit_of_work_factory,
        app.state.authorization_service,
        app.state.ticket_service,
        app.state.queue_service,
        app.state.retrieval_service,
        app.state.ai_gateway,
        app.state.workflow_service,
        app.state.copilot_metrics,
    )
    app.state.attachment_service = AttachmentService(
        unit_of_work_factory,
        app.state.authorization_service,
        S3ObjectStorage(settings),
        ClamAVScanner(settings),
        settings,
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


def _embedding_provider(settings: Settings) -> QueryEmbeddingProvider:
    if settings.retrieval_embedding_provider == "http":
        assert settings.retrieval_embedding_endpoint is not None
        assert settings.retrieval_embedding_api_key is not None
        return HttpQueryEmbeddingProvider(
            settings.retrieval_embedding_endpoint,
            settings.retrieval_embedding_api_key.get_secret_value(),
            settings.retrieval_embedding_model_code,
            settings.retrieval_provider_timeout_seconds,
        )
    return DeterministicQueryEmbeddingProvider(settings.retrieval_embedding_model_code)


def _reranking_provider(settings: Settings) -> RerankingProvider | None:
    if not settings.retrieval_reranker_enabled:
        return None
    assert settings.retrieval_reranker_endpoint is not None
    assert settings.retrieval_reranker_api_key is not None
    return HttpRerankingProvider(
        settings.retrieval_reranker_endpoint,
        settings.retrieval_reranker_api_key.get_secret_value(),
        settings.retrieval_reranker_model_code,
        settings.retrieval_provider_timeout_seconds,
    )


app = create_app()
