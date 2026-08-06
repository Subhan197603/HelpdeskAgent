"""Administration shell reads: real counts, safe status metadata, audit history."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from apps.api.app.admin.repository import AdminRepository
from apps.api.app.admin.schemas import (
    AdminOverviewResponse,
    AuditEventListResponse,
    AuditEventSummary,
    DependencyStatusItem,
    SecurityEventListResponse,
    SecurityEventSummary,
    SystemStatusResponse,
)
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.core.settings import Settings
from apps.api.app.db.migration_guard import inspect_revision
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.infrastructure.health import ApplicationResources, HealthProbe

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_VERSIONS_PATH = _REPOSITORY_ROOT / "apps" / "api" / "alembic" / "versions"


def application_migration_head(versions_path: Path = _VERSIONS_PATH) -> str | None:
    """The single head of the application's linear migration chain.

    Derived from revision files rather than the database: the runtime role has
    no read grant on the alembic version table, and every environment runs
    migrations to head before serving traffic.
    """
    down_revisions: dict[str, str | None] = {}
    for path in sorted(versions_path.glob("*.py")):
        info, _ = inspect_revision(path, _REPOSITORY_ROOT)
        if info.revision:
            down_revisions[info.revision] = info.down_revision
    parents = {parent for parent in down_revisions.values() if parent is not None}
    heads = [revision for revision in down_revisions if revision not in parents]
    return heads[0] if len(heads) == 1 else None


async def _probe(probe: HealthProbe, name: str, *, required: bool) -> DependencyStatusItem:
    try:
        healthy = await probe.check()
    except Exception:  # noqa: BLE001 - a failing probe is an unhealthy dependency
        healthy = False
    return DependencyStatusItem(
        name=name, status="healthy" if healthy else "unhealthy", required=required
    )


class AdminService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        settings: Settings,
        resources: ApplicationResources,
    ) -> None:
        self._factory = factory
        self._settings = settings
        self._resources = resources
        self._migration_head = application_migration_head()

    async def overview(self, context: RequestContext) -> AdminOverviewResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            counts = await AdminRepository(uow.session).overview(tenant_id)
            await uow.commit()
        return AdminOverviewResponse(
            active_users=counts.active_users,
            support_groups=counts.support_groups,
            open_tickets=counts.open_tickets,
            published_knowledge_documents=counts.published_knowledge_documents,
        )

    async def system_status(self, context: RequestContext) -> SystemStatusResponse:
        self._tenant(context)
        checks = [
            _probe(self._resources.database, "postgresql", required=True),
            _probe(self._resources.redis, "redis", required=True),
        ]
        if self._settings.object_storage_enabled:
            checks.append(_probe(self._resources.object_storage, "object_storage", required=True))
        checks.append(
            _probe(self._resources.clamav, "clamav", required=self._settings.clamav_required)
        )
        dependencies = list(await asyncio.gather(*checks))
        if not self._settings.object_storage_enabled:
            dependencies.append(
                DependencyStatusItem(name="object_storage", status="disabled", required=False)
            )
        return SystemStatusResponse(
            app_version=self._settings.app_version,
            environment=self._settings.app_env.value,
            migration_head=self._migration_head,
            oidc_enabled=self._settings.oidc_enabled,
            developer_identity_enabled=self._settings.developer_identity_enabled,
            ai_globally_enabled=self._settings.ai_globally_enabled,
            object_storage_enabled=self._settings.object_storage_enabled,
            clamav_required=self._settings.clamav_required,
            metrics_endpoint_enabled=self._settings.metrics_endpoint_enabled,
            rls_enabled=self._settings.rls_enabled,
            retrieval_embedding_provider=self._settings.retrieval_embedding_provider,
            dependencies=dependencies,
        )

    async def audit_events(
        self,
        context: RequestContext,
        *,
        resource_type: str | None,
        action_code: str | None,
        outcome_code: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        limit: int,
        offset: int,
    ) -> AuditEventListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).audit_events(
                tenant_id,
                resource_type=resource_type,
                action_code=action_code,
                outcome_code=outcome_code,
                occurred_from=occurred_from,
                occurred_to=occurred_to,
                limit=limit + 1,
                offset=offset,
            )
            await uow.commit()
        return AuditEventListResponse(
            items=[
                AuditEventSummary(
                    id=row.id,
                    actor_id=row.actor_id,
                    actor_type=row.actor_type,
                    action_code=row.action_code,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    outcome_code=row.outcome_code,
                    failure_reason=row.failure_reason,
                    change_summary=row.change_summary,
                    correlation_id=row.correlation_id,
                    request_id=row.request_id,
                    occurred_at=row.occurred_at,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def security_events(
        self,
        context: RequestContext,
        *,
        event_type: str | None,
        decision_code: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        limit: int,
        offset: int,
    ) -> SecurityEventListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).security_events(
                tenant_id,
                event_type=event_type,
                decision_code=decision_code,
                occurred_from=occurred_from,
                occurred_to=occurred_to,
                limit=limit + 1,
                offset=offset,
            )
            await uow.commit()
        return SecurityEventListResponse(
            items=[
                SecurityEventSummary(
                    id=row.id,
                    event_type=row.event_type,
                    decision_code=row.decision_code,
                    user_id=row.user_id,
                    resource_type=row.resource_type,
                    resource_id=row.resource_id,
                    details=row.details,
                    occurred_at=row.occurred_at,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    def _tenant(self, context: RequestContext) -> UUID:
        if context.tenant_id is None:
            raise AuthorizationError("Authenticated administrator identity is required.")
        return context.tenant_id
