"""Administration shell reads: real counts, safe status metadata, audit history."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from uuid import UUID

from apps.api.app.admin.repository import AdminRepository, SecurityEventRow, TicketViewRow
from apps.api.app.admin.schemas import (
    AdminExternalIdentityItem,
    AdminOverviewResponse,
    AdminPermissionGroup,
    AdminQueueDetailResponse,
    AdminQueueListResponse,
    AdminQueueMemberItem,
    AdminQueueSummary,
    AdminRoleAssignmentItem,
    AdminRoleDetailResponse,
    AdminRoleListResponse,
    AdminRoleSummary,
    AdminTicketViewListResponse,
    AdminTicketViewSummary,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserMembershipItem,
    AdminUserRoleItem,
    AdminUserSummary,
    AuditEventListResponse,
    AuditEventSummary,
    DependencyStatusItem,
    SecurityEventListResponse,
    SecurityEventSummary,
    SystemStatusResponse,
)
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, NotFoundError
from apps.api.app.core.settings import Settings
from apps.api.app.db.migration_guard import inspect_revision
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import ROLE_PERMISSIONS, Permission
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


_JIT_SUBJECT_PREFIX = "oidc:"
_RECENT_SECURITY_EVENT_LIMIT = 10
_PERMISSION_DOMAINS: tuple[tuple[str, str], ...] = (
    ("ADMIN_", "Administration"),
    ("AUDIT_", "Administration"),
    ("SYSTEM_", "Administration"),
    ("AI_", "AI"),
    ("APPROVAL_", "Approvals"),
    ("ATTACHMENT_", "Attachments"),
    ("CATALOG_", "Catalogue"),
    ("IDENTITY_", "Identity"),
    ("KNOWLEDGE_", "Knowledge"),
    ("NOTIFICATION_", "Notifications"),
    ("PROJECT_", "Projects"),
    ("TICKET_", "Tickets"),
)


def permission_domain(permission_code: str) -> str:
    for prefix, domain in _PERMISSION_DOMAINS:
        if permission_code.startswith(prefix):
            return domain
    return "Other"


def grouped_permissions(role_code: str) -> list[AdminPermissionGroup]:
    groups: dict[str, list[str]] = {}
    for permission in ROLE_PERMISSIONS.get(role_code, frozenset()):
        groups.setdefault(permission_domain(permission.value), []).append(permission.value)
    return [
        AdminPermissionGroup(domain=domain, permission_codes=sorted(codes))
        for domain, codes in sorted(groups.items())
    ]


def effective_permission_codes(role_codes: list[str]) -> list[str]:
    permissions = {Permission.IDENTITY_SELF_READ.value}
    for role_code in role_codes:
        permissions.update(
            permission.value for permission in ROLE_PERMISSIONS.get(role_code, frozenset())
        )
    return sorted(permissions)


def _security_event_summary(row: SecurityEventRow) -> SecurityEventSummary:
    return SecurityEventSummary(
        id=row.id,
        event_type=row.event_type,
        decision_code=row.decision_code,
        user_id=row.user_id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        details=row.details,
        occurred_at=row.occurred_at,
    )


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

    async def users(
        self,
        context: RequestContext,
        *,
        search: str | None,
        active: bool | None,
        role_code: str | None,
        support_group_id: UUID | None,
        provider_code: str | None,
        limit: int,
        offset: int,
    ) -> AdminUserListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).users(
                tenant_id,
                search=search,
                active=active,
                role_code=role_code,
                support_group_id=support_group_id,
                provider_code=provider_code,
                limit=limit + 1,
                offset=offset,
            )
            await uow.commit()
        return AdminUserListResponse(
            items=[
                AdminUserSummary(
                    user_id=row.user_id,
                    display_name=row.display_name,
                    email_address=row.email_address,
                    active_flag=row.active_flag,
                    business_unit_name=row.business_unit_name,
                    role_codes=list(row.role_codes),
                    support_group_names=list(row.support_group_names),
                    identity_provider_codes=list(row.identity_provider_codes),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def user_detail(self, context: RequestContext, user_id: UUID) -> AdminUserDetailResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            profile = await repository.user_profile(tenant_id, user_id)
            if profile is None:
                raise NotFoundError("User not found.")
            roles = await repository.user_roles(tenant_id, user_id)
            memberships = await repository.user_memberships(tenant_id, user_id)
            events = await repository.user_security_events(
                tenant_id, user_id, limit=_RECENT_SECURITY_EVENT_LIMIT
            )
            await uow.commit()
        role_codes = sorted({role.role_code for role in roles})
        return AdminUserDetailResponse(
            user_id=profile.user_id,
            display_name=profile.display_name,
            email_address=profile.email_address,
            active_flag=profile.active_flag,
            business_unit_name=profile.business_unit_name,
            locale_code=profile.locale_code,
            timezone_name=profile.timezone_name,
            provisioning=(
                "JIT"
                if profile.external_subject.startswith(_JIT_SUBJECT_PREFIX)
                else "PRE_PROVISIONED"
            ),
            oidc_linked=bool(profile.external_identities),
            roles=[
                AdminUserRoleItem(
                    role_code=role.role_code,
                    role_name=role.role_name,
                    active_flag=role.active_flag,
                    valid_from=role.valid_from,
                    valid_to=role.valid_to,
                )
                for role in roles
            ],
            effective_permission_codes=effective_permission_codes(role_codes),
            memberships=[
                AdminUserMembershipItem(
                    support_group_id=membership.support_group_id,
                    group_name=membership.group_name,
                    member_role=membership.member_role,
                    active_flag=membership.active_flag,
                    joined_at=membership.joined_at,
                )
                for membership in memberships
            ],
            external_identities=[
                AdminExternalIdentityItem(
                    provider_code=identity.provider_code,
                    active_flag=identity.active_flag,
                    last_authenticated_at=identity.last_authenticated_at,
                )
                for identity in profile.external_identities
            ],
            recent_security_events=[_security_event_summary(row) for row in events],
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    async def roles(
        self, context: RequestContext, *, search: str | None, limit: int, offset: int
    ) -> AdminRoleListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).roles(
                tenant_id, search=search, limit=limit + 1, offset=offset
            )
            await uow.commit()
        return AdminRoleListResponse(
            items=[
                AdminRoleSummary(
                    role_code=row.role_code,
                    role_name=row.role_name,
                    description=row.description,
                    system_role_flag=row.system_role_flag,
                    active_flag=row.active_flag,
                    permission_count=len(ROLE_PERMISSIONS.get(row.role_code, frozenset())),
                    assigned_user_count=row.assigned_user_count,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def role_detail(
        self, context: RequestContext, role_code: str, *, limit: int, offset: int
    ) -> AdminRoleDetailResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            role = await repository.role(role_code)
            if role is None:
                raise NotFoundError("Role not found.")
            assignments = await repository.role_assignments(
                tenant_id, role_code, limit=limit + 1, offset=offset
            )
            await uow.commit()
        return AdminRoleDetailResponse(
            role_code=role.role_code,
            role_name=role.role_name,
            description=role.description,
            system_role_flag=role.system_role_flag,
            active_flag=role.active_flag,
            permission_groups=grouped_permissions(role.role_code),
            assignments=[
                AdminRoleAssignmentItem(
                    user_id=assignment.user_id,
                    display_name=assignment.display_name,
                    email_address=assignment.email_address,
                    active_flag=assignment.active_flag,
                    valid_from=assignment.valid_from,
                    valid_to=assignment.valid_to,
                )
                for assignment in assignments[:limit]
            ],
            assignments_has_more=len(assignments) > limit,
        )

    async def queues(
        self,
        context: RequestContext,
        *,
        search: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> AdminQueueListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).queues(
                tenant_id, search=search, active=active, limit=limit + 1, offset=offset
            )
            await uow.commit()
        return AdminQueueListResponse(
            items=[
                AdminQueueSummary(
                    support_group_id=row.support_group_id,
                    group_code=row.group_code,
                    group_name=row.group_name,
                    contact_email=row.contact_email,
                    assignment_method=row.assignment_method,
                    active_flag=row.active_flag,
                    member_count=row.member_count,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def queue_detail(
        self, context: RequestContext, support_group_id: UUID
    ) -> AdminQueueDetailResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            queue = await repository.queue(tenant_id, support_group_id)
            if queue is None:
                raise NotFoundError("Queue not found.")
            members = await repository.queue_members(tenant_id, support_group_id)
            views = await repository.ticket_views(
                tenant_id, owner_group_id=support_group_id, limit=100, offset=0
            )
            await uow.commit()
        return AdminQueueDetailResponse(
            support_group_id=queue.support_group_id,
            group_code=queue.group_code,
            group_name=queue.group_name,
            contact_email=queue.contact_email,
            assignment_method=queue.assignment_method,
            active_flag=queue.active_flag,
            manager_display_name=queue.manager_display_name,
            members=[
                AdminQueueMemberItem(
                    user_id=member.user_id,
                    display_name=member.display_name,
                    member_role=member.member_role,
                    active_flag=member.active_flag,
                    joined_at=member.joined_at,
                )
                for member in members
            ],
            ticket_views=[self._ticket_view(row) for row in views],
            created_at=queue.created_at,
            updated_at=queue.updated_at,
        )

    async def ticket_views(
        self, context: RequestContext, *, limit: int, offset: int
    ) -> AdminTicketViewListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).ticket_views(
                tenant_id, owner_group_id=None, limit=limit + 1, offset=offset
            )
            await uow.commit()
        return AdminTicketViewListResponse(
            items=[self._ticket_view(row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )

    @staticmethod
    def _ticket_view(row: TicketViewRow) -> AdminTicketViewSummary:
        return AdminTicketViewSummary(
            queue_id=row.queue_id,
            queue_name=row.queue_name,
            description=row.description,
            project_code=row.project_code,
            visibility=row.visibility,
            display_order=row.display_order,
            version_status=row.version_status,
            active_flag=row.active_flag,
        )

    def _tenant(self, context: RequestContext) -> UUID:
        if context.tenant_id is None:
            raise AuthorizationError("Authenticated administrator identity is required.")
        return context.tenant_id
