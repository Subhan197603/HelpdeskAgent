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
    AdminQueueMemberChangeResponse,
    AdminQueueMemberItem,
    AdminQueueMemberRequest,
    AdminQueueSummary,
    AdminRoleAssignmentChangeResponse,
    AdminRoleAssignmentItem,
    AdminRoleAssignRequest,
    AdminRoleDetailResponse,
    AdminRoleListResponse,
    AdminRoleSummary,
    AdminTicketViewListResponse,
    AdminTicketViewSummary,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserMembershipItem,
    AdminUserRoleItem,
    AdminUserStatusRequest,
    AdminUserStatusResponse,
    AdminUserSummary,
    AuditEventListResponse,
    AuditEventSummary,
    DependencyStatusItem,
    SecurityEventListResponse,
    SecurityEventSummary,
    SystemStatusResponse,
)
from apps.api.app.audit.security_events import SecurityEvent, SecurityEventService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    NotFoundError,
)
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


_ADMIN_ROLE_CODE = "PLATFORM_ADMIN"
# Granting is blocked only when the target role carries privileged permissions the
# caller does not hold. A full-subset rule would break legitimate grants in the flat
# permission model (for example TICKET_READ_ALL does not literally contain
# TICKET_READ_GROUP), so the boundary tracks the permissions that confer
# administrative or governance power.
_PRIVILEGED_GRANT_PERMISSIONS = frozenset(
    {
        Permission.ADMIN_IDENTITY_READ,
        Permission.ADMIN_IDENTITY_WRITE,
        Permission.AUDIT_EVENT_READ,
        Permission.SYSTEM_HEALTH_READ,
        Permission.AI_OVERSIGHT,
        Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL,
        Permission.KNOWLEDGE_ACQUISITION_PERMISSION_MANAGE,
    }
)
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

    async def set_user_status(
        self, context: RequestContext, user_id: UUID, payload: AdminUserStatusRequest
    ) -> AdminUserStatusResponse:
        tenant_id = self._tenant(context)
        await self._forbid_self_mutation(context, user_id, resource_type="user")
        try:
            async with self._factory(context) as uow:
                repository = AdminRepository(uow.session)
                await repository.lock_tenant_identity(tenant_id)
                user = await repository.user_for_update(tenant_id, user_id)
                if user is None:
                    raise NotFoundError("User not found.")
                if user.active_flag == payload.active:
                    await uow.commit()
                    return AdminUserStatusResponse(
                        user_id=user_id,
                        active_flag=user.active_flag,
                        updated_at=user.updated_at,
                        changed=False,
                    )
                if user.updated_at != payload.expected_updated_at:
                    raise ConcurrencyError(
                        "The user was modified by someone else. Reload and try again."
                    )
                if not payload.active:
                    await self._require_surviving_administrator(repository, tenant_id, user_id)
                updated_at = await repository.set_user_active(
                    tenant_id, user_id, active=payload.active
                )
                await repository.record_admin_action(
                    tenant_id,
                    actor_id=context.user_id,
                    action_code=(
                        "ADMIN_USER_REACTIVATED" if payload.active else "ADMIN_USER_DEACTIVATED"
                    ),
                    resource_type="USER",
                    resource_id=str(user_id),
                    change_summary={
                        "active_flag": {"from": user.active_flag, "to": payload.active}
                    },
                )
                await uow.commit()
                return AdminUserStatusResponse(
                    user_id=user_id,
                    active_flag=payload.active,
                    updated_at=updated_at,
                    changed=True,
                )
        except ConflictError:
            await self._record_security_denial(
                context, "LAST_ADMIN_PROTECTION_TRIGGERED", "user", str(user_id)
            )
            raise

    async def assign_role(
        self, context: RequestContext, user_id: UUID, payload: AdminRoleAssignRequest
    ) -> AdminRoleAssignmentChangeResponse:
        tenant_id = self._tenant(context)
        await self._forbid_self_mutation(context, user_id, resource_type="user_role")
        role_code = payload.role_code
        try:
            async with self._factory(context) as uow:
                repository = AdminRepository(uow.session)
                await repository.lock_tenant_identity(tenant_id)
                user = await repository.user_for_update(tenant_id, user_id)
                if user is None:
                    raise NotFoundError("User not found.")
                granted_permissions = ROLE_PERMISSIONS.get(role_code)
                if granted_permissions is None or not await repository.active_role_definition(
                    role_code
                ):
                    raise NotFoundError("Role not found.")
                caller_permissions: set[Permission] = set()
                for caller_role in context.roles:
                    caller_permissions.update(ROLE_PERMISSIONS.get(caller_role, frozenset()))
                privileged_grants = granted_permissions & _PRIVILEGED_GRANT_PERMISSIONS
                if not privileged_grants <= caller_permissions:
                    raise AuthorizationError(
                        "A role granting privileged permissions beyond your own cannot be assigned."
                    )
                existing = await repository.active_role_assignment(tenant_id, user_id, role_code)
                if existing is not None:
                    await uow.commit()
                    return AdminRoleAssignmentChangeResponse(
                        user_id=user_id, role_code=role_code, valid_from=existing, changed=False
                    )
                valid_from = await repository.insert_role_assignment(
                    tenant_id, user_id, role_code, granted_by=context.user_id
                )
                await repository.record_admin_action(
                    tenant_id,
                    actor_id=context.user_id,
                    action_code="ADMIN_ROLE_ASSIGNED",
                    resource_type="USER_ROLE",
                    resource_id=f"{user_id}:{role_code}",
                    change_summary={"user_id": str(user_id), "role_code": role_code},
                )
                await uow.commit()
                return AdminRoleAssignmentChangeResponse(
                    user_id=user_id, role_code=role_code, valid_from=valid_from, changed=True
                )
        except AuthorizationError:
            await self._record_security_denial(
                context, "ADMIN_ROLE_GRANT_BOUNDARY_BLOCKED", "user_role", role_code
            )
            raise

    async def remove_role(
        self, context: RequestContext, user_id: UUID, role_code: str
    ) -> AdminRoleAssignmentChangeResponse:
        tenant_id = self._tenant(context)
        await self._forbid_self_mutation(context, user_id, resource_type="user_role")
        try:
            async with self._factory(context) as uow:
                repository = AdminRepository(uow.session)
                await repository.lock_tenant_identity(tenant_id)
                user = await repository.user_for_update(tenant_id, user_id)
                if user is None:
                    raise NotFoundError("User not found.")
                if role_code == _ADMIN_ROLE_CODE:
                    assigned = await repository.active_role_assignment(
                        tenant_id, user_id, role_code
                    )
                    if assigned is not None:
                        await self._require_surviving_administrator(repository, tenant_id, user_id)
                closed = await repository.close_role_assignments(tenant_id, user_id, role_code)
                changed = closed > 0
                if changed:
                    await repository.record_admin_action(
                        tenant_id,
                        actor_id=context.user_id,
                        action_code="ADMIN_ROLE_REMOVED",
                        resource_type="USER_ROLE",
                        resource_id=f"{user_id}:{role_code}",
                        change_summary={"user_id": str(user_id), "role_code": role_code},
                    )
                await uow.commit()
                return AdminRoleAssignmentChangeResponse(
                    user_id=user_id, role_code=role_code, valid_from=None, changed=changed
                )
        except ConflictError:
            await self._record_security_denial(
                context, "LAST_ADMIN_PROTECTION_TRIGGERED", "user_role", str(user_id)
            )
            raise

    async def add_queue_member(
        self, context: RequestContext, support_group_id: UUID, payload: AdminQueueMemberRequest
    ) -> AdminQueueMemberChangeResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            queue = await repository.queue_reference(tenant_id, support_group_id)
            if queue is None:
                raise NotFoundError("Queue not found.")
            user = await repository.user_for_update(tenant_id, payload.user_id)
            if user is None:
                raise NotFoundError("User not found.")
            existing = await repository.membership_for_update(support_group_id, payload.user_id)
            if (
                existing is not None
                and existing.active_flag
                and existing.member_role == payload.member_role
            ):
                await uow.commit()
                return AdminQueueMemberChangeResponse(
                    support_group_id=support_group_id,
                    user_id=payload.user_id,
                    member_role=payload.member_role,
                    changed=False,
                )
            await repository.upsert_queue_member(
                support_group_id, payload.user_id, member_role=payload.member_role
            )
            await repository.record_admin_action(
                tenant_id,
                actor_id=context.user_id,
                action_code="ADMIN_QUEUE_MEMBER_ADDED",
                resource_type="SUPPORT_GROUP_MEMBER",
                resource_id=f"{support_group_id}:{payload.user_id}",
                change_summary={
                    "member_role": payload.member_role,
                    "previous": (
                        None
                        if existing is None
                        else {
                            "member_role": existing.member_role,
                            "active_flag": existing.active_flag,
                        }
                    ),
                },
            )
            await uow.commit()
            return AdminQueueMemberChangeResponse(
                support_group_id=support_group_id,
                user_id=payload.user_id,
                member_role=payload.member_role,
                changed=True,
            )

    async def remove_queue_member(
        self, context: RequestContext, support_group_id: UUID, user_id: UUID
    ) -> AdminQueueMemberChangeResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            queue = await repository.queue_reference(tenant_id, support_group_id)
            if queue is None:
                raise NotFoundError("Queue not found.")
            deactivated = await repository.deactivate_queue_member(support_group_id, user_id)
            changed = deactivated > 0
            if changed:
                await repository.record_admin_action(
                    tenant_id,
                    actor_id=context.user_id,
                    action_code="ADMIN_QUEUE_MEMBER_REMOVED",
                    resource_type="SUPPORT_GROUP_MEMBER",
                    resource_id=f"{support_group_id}:{user_id}",
                    change_summary={"user_id": str(user_id)},
                )
            await uow.commit()
            return AdminQueueMemberChangeResponse(
                support_group_id=support_group_id,
                user_id=user_id,
                member_role=None,
                changed=changed,
            )

    async def _forbid_self_mutation(
        self, context: RequestContext, user_id: UUID, *, resource_type: str
    ) -> None:
        if context.user_id == user_id:
            await self._record_security_denial(
                context, "ADMIN_SELF_MUTATION_BLOCKED", resource_type, str(user_id)
            )
            raise AuthorizationError(
                "Administrators cannot change their own access. Ask another administrator."
            )

    @staticmethod
    async def _require_surviving_administrator(
        repository: AdminRepository, tenant_id: UUID, excluded_user_id: UUID
    ) -> None:
        survivors = await repository.active_admin_count(
            tenant_id, admin_role_code=_ADMIN_ROLE_CODE, excluded_user_id=excluded_user_id
        )
        if survivors == 0:
            raise ConflictError(
                "The tenant must keep at least one active administrator. "
                "Grant another administrator first."
            )

    async def _record_security_denial(
        self, context: RequestContext, event_type: str, resource_type: str, resource_id: str
    ) -> None:
        async with self._factory(context) as uow:
            await SecurityEventService(uow.session).record(
                SecurityEvent(
                    event_type,
                    "DENIED",
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                ),
                context,
            )
            await uow.commit()

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
