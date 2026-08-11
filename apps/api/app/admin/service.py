"""Administration shell reads: real counts, safe status metadata, audit history."""

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from apps.api.app.admin.repository import (
    AdminRepository,
    FormFieldRow,
    SecurityEventRow,
    SlaGoalRow,
    TicketViewRow,
    WorkflowTransitionRow,
)
from apps.api.app.admin.schemas import (
    AdminCalendarDetailResponse,
    AdminCalendarExceptionItem,
    AdminCalendarLinkedGoalItem,
    AdminCalendarListResponse,
    AdminCalendarSummary,
    AdminCalendarVersionItem,
    AdminCalendarWorkingPeriodItem,
    AdminExternalIdentityItem,
    AdminFormFieldItem,
    AdminFormFieldOptionItem,
    AdminOverviewResponse,
    AdminPermissionGroup,
    AdminQueueDetailResponse,
    AdminQueueListResponse,
    AdminQueueMemberChangeResponse,
    AdminQueueMemberItem,
    AdminQueueMemberRequest,
    AdminQueueSummary,
    AdminRequestTypeDetailResponse,
    AdminRequestTypeListResponse,
    AdminRequestTypeSummary,
    AdminRequestTypeVersionItem,
    AdminRequestTypeVisibilityRequest,
    AdminRequestTypeVisibilityResponse,
    AdminRoleAssignmentChangeResponse,
    AdminRoleAssignmentItem,
    AdminRoleAssignRequest,
    AdminRoleDetailResponse,
    AdminRoleListResponse,
    AdminRoleSummary,
    AdminSlaCycleCounts,
    AdminSlaGoalItem,
    AdminSlaPolicyDetailResponse,
    AdminSlaPolicyListResponse,
    AdminSlaPolicySummary,
    AdminSlaVersionItem,
    AdminTicketViewListResponse,
    AdminTicketViewSummary,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserMembershipItem,
    AdminUserRoleItem,
    AdminUserStatusRequest,
    AdminUserStatusResponse,
    AdminUserSummary,
    AdminWorkflowDetailResponse,
    AdminWorkflowListResponse,
    AdminWorkflowRequestTypeItem,
    AdminWorkflowStatusItem,
    AdminWorkflowSummary,
    AdminWorkflowTransitionItem,
    AdminWorkflowVersionItem,
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
        Permission.ADMIN_CONFIG_READ,
        Permission.ADMIN_CONFIG_WRITE,
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


# Stored configuration rules are summarized into plain sentences; the raw JSON
# payloads never leave the service. Unknown shapes degrade to "Custom rule"
# instead of failing or leaking the payload.
_RULE_OPERATOR_LABELS = {
    "equals": "is",
    "not_equals": "is not",
    "in": "is one of",
    "not_in": "is not one of",
    "is_empty": "is empty",
    "is_not_empty": "is not empty",
    "is_null": "is not set",
    "is_not_null": "is set",
}
_VALUELESS_RULE_OPERATORS = frozenset({"is_empty", "is_not_empty", "is_null", "is_not_null"})


def _rule_line(item: dict[str, Any]) -> str:
    if set(item.keys()) == {"status_code"} and isinstance(item["status_code"], str):
        return f"Ticket status is {item['status_code']}"
    field = item.get("field")
    operator = item.get("operator")
    if isinstance(field, str) and isinstance(operator, str):
        label = _RULE_OPERATOR_LABELS.get(operator, operator.replace("_", " "))
        value = item.get("value")
        if operator in _VALUELESS_RULE_OPERATORS or value is None:
            return f"{field} {label}"
        if isinstance(value, list):
            rendered = ", ".join(str(entry) for entry in value)
            return f"{field} {label} {rendered}"
        return f"{field} {label} {value}"
    return "Custom rule"


def summarize_rules(payload: object) -> list[str]:
    """Readable one-line summaries of a stored rule payload."""
    if payload is None or payload == {} or payload == []:
        return []
    if isinstance(payload, dict):
        for connector, header in (("all", None), ("any", "Any of the following:")):
            group = payload.get(connector)
            if set(payload.keys()) == {connector} and isinstance(group, list) and group:
                lines = [
                    _rule_line(entry) if isinstance(entry, dict) else "Custom rule"
                    for entry in group
                ]
                if header is not None and len(lines) > 1:
                    return [header, *lines]
                return lines
        if all(isinstance(value, str | int | float | bool) for value in payload.values()):
            return [f"{key} is {value}" for key, value in sorted(payload.items())]
        return ["Custom rule"]
    if isinstance(payload, list):
        return [
            _rule_line(entry) if isinstance(entry, dict) else "Custom rule" for entry in payload
        ]
    return ["Custom rule"]


def transition_required_fields(payload: object) -> list[str]:
    if not isinstance(payload, list):
        return []
    return [
        str(entry["field"])
        for entry in payload
        if isinstance(entry, dict)
        and entry.get("type") == "required_field"
        and isinstance(entry.get("field"), str)
    ]


def transition_action_types(payload: object) -> list[str]:
    if not isinstance(payload, list):
        return []
    return [
        str(entry["type"])
        for entry in payload
        if isinstance(entry, dict) and isinstance(entry.get("type"), str)
    ]


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

    async def workflows(
        self,
        context: RequestContext,
        *,
        search: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> AdminWorkflowListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).workflows(
                tenant_id, search=search, active=active, limit=limit + 1, offset=offset
            )
            await uow.commit()
        return AdminWorkflowListResponse(
            items=[
                AdminWorkflowSummary(
                    workflow_id=row.workflow_id,
                    workflow_code=row.workflow_code,
                    workflow_name=row.workflow_name,
                    description=row.description,
                    active_flag=row.active_flag,
                    current_version_number=row.current_version_number,
                    current_version_status=row.current_version_status,
                    status_count=row.status_count,
                    transition_count=row.transition_count,
                    request_type_count=row.request_type_count,
                    ticket_count=row.ticket_count,
                    created_at=row.created_at,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def workflow_detail(
        self, context: RequestContext, workflow_id: UUID
    ) -> AdminWorkflowDetailResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            workflow = await repository.workflow(tenant_id, workflow_id)
            if workflow is None:
                raise NotFoundError("Workflow not found.")
            statuses = (
                await repository.workflow_statuses(workflow.displayed_version_id)
                if workflow.displayed_version_id is not None
                else ()
            )
            transitions = (
                await repository.workflow_transitions(workflow.displayed_version_id)
                if workflow.displayed_version_id is not None
                else ()
            )
            await uow.commit()
        return AdminWorkflowDetailResponse(
            workflow_id=workflow.workflow_id,
            workflow_code=workflow.workflow_code,
            workflow_name=workflow.workflow_name,
            description=workflow.description,
            active_flag=workflow.active_flag,
            created_at=workflow.created_at,
            displayed_version_number=workflow.displayed_version_number,
            displayed_version_status=workflow.displayed_version_status,
            versions=[
                AdminWorkflowVersionItem(
                    workflow_version_id=version.workflow_version_id,
                    version_number=version.version_number,
                    version_status=version.version_status,
                    effective_from=version.effective_from,
                    effective_to=version.effective_to,
                    published_at=version.published_at,
                    published_by_display_name=version.published_by_display_name,
                    created_at=version.created_at,
                    ticket_count=version.ticket_count,
                )
                for version in workflow.versions
            ],
            statuses=[
                AdminWorkflowStatusItem(
                    status_id=status.status_id,
                    status_code=status.status_code,
                    status_name=status.status_name,
                    status_category=status.status_category,
                    initial_flag=status.initial_flag,
                    terminal_flag=status.terminal_flag,
                    customer_visible_name=status.customer_visible_name,
                    display_order=status.display_order,
                )
                for status in statuses
            ],
            transitions=[self._transition_item(transition) for transition in transitions],
            request_types=[
                AdminWorkflowRequestTypeItem(
                    request_type_id=request_type.request_type_id,
                    request_type_code=request_type.request_type_code,
                    request_type_name=request_type.request_type_name,
                    active_flag=request_type.active_flag,
                    employee_visible_flag=request_type.employee_visible_flag,
                )
                for request_type in workflow.request_types
            ],
        )

    async def sla_policies(
        self,
        context: RequestContext,
        *,
        search: str | None,
        active: bool | None,
        project_id: UUID | None,
        limit: int,
        offset: int,
    ) -> AdminSlaPolicyListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).sla_policies(
                tenant_id,
                search=search,
                active=active,
                project_id=project_id,
                limit=limit + 1,
                offset=offset,
            )
            await uow.commit()
        return AdminSlaPolicyListResponse(
            items=[
                AdminSlaPolicySummary(
                    sla_definition_id=row.sla_definition_id,
                    sla_code=row.sla_code,
                    sla_name=row.sla_name,
                    metric_code=row.metric_code,
                    project_key=row.project_key,
                    project_name=row.project_name,
                    active_flag=row.active_flag,
                    goal_count=row.goal_count,
                    running_cycle_count=row.running_cycle_count,
                    breached_cycle_count=row.breached_cycle_count,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def sla_policy_detail(
        self, context: RequestContext, sla_definition_id: UUID
    ) -> AdminSlaPolicyDetailResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            policy = await repository.sla_policy(tenant_id, sla_definition_id)
            if policy is None:
                raise NotFoundError("SLA policy not found.")
            goals = await repository.sla_goals(sla_definition_id)
            await uow.commit()
        return AdminSlaPolicyDetailResponse(
            sla_definition_id=policy.sla_definition_id,
            sla_code=policy.sla_code,
            sla_name=policy.sla_name,
            metric_code=policy.metric_code,
            description=policy.description,
            project_key=policy.project_key,
            project_name=policy.project_name,
            active_flag=policy.active_flag,
            start_condition_summary=summarize_rules(policy.start_condition_payload),
            pause_condition_summary=summarize_rules(policy.pause_condition_payload),
            stop_condition_summary=summarize_rules(policy.stop_condition_payload),
            goals=[self._sla_goal_item(goal) for goal in goals],
            versions=[
                AdminSlaVersionItem(
                    sla_definition_version_id=version.sla_definition_version_id,
                    version_number=version.version_number,
                    version_status=version.version_status,
                    effective_from=version.effective_from,
                    effective_to=version.effective_to,
                    published_at=version.published_at,
                )
                for version in policy.versions
            ],
            cycle_counts=AdminSlaCycleCounts(
                pending=policy.pending_count,
                running=policy.running_count,
                paused=policy.paused_count,
                completed=policy.completed_count,
                breached=policy.breached_count,
                cancelled=policy.cancelled_count,
            ),
        )

    async def calendars(
        self,
        context: RequestContext,
        *,
        search: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> AdminCalendarListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).calendars(
                tenant_id, search=search, active=active, limit=limit + 1, offset=offset
            )
            await uow.commit()
        return AdminCalendarListResponse(
            items=[
                AdminCalendarSummary(
                    calendar_id=row.calendar_id,
                    calendar_code=row.calendar_code,
                    calendar_name=row.calendar_name,
                    timezone_name=row.timezone_name,
                    twenty_four_seven_flag=row.twenty_four_seven_flag,
                    active_flag=row.active_flag,
                    current_version_number=row.current_version_number,
                    current_version_status=row.current_version_status,
                    linked_goal_count=row.linked_goal_count,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def calendar_detail(
        self, context: RequestContext, calendar_id: UUID
    ) -> AdminCalendarDetailResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            calendar = await repository.calendar(tenant_id, calendar_id)
            if calendar is None:
                raise NotFoundError("Business calendar not found.")
            working_periods = (
                await repository.calendar_working_periods(calendar.displayed_version_id)
                if calendar.displayed_version_id is not None
                else ()
            )
            exceptions = (
                await repository.calendar_exceptions(calendar.displayed_version_id)
                if calendar.displayed_version_id is not None
                else ()
            )
            await uow.commit()
        return AdminCalendarDetailResponse(
            calendar_id=calendar.calendar_id,
            calendar_code=calendar.calendar_code,
            calendar_name=calendar.calendar_name,
            timezone_name=calendar.timezone_name,
            twenty_four_seven_flag=calendar.twenty_four_seven_flag,
            active_flag=calendar.active_flag,
            displayed_version_number=calendar.displayed_version_number,
            displayed_version_status=calendar.displayed_version_status,
            versions=[
                AdminCalendarVersionItem(
                    business_calendar_version_id=version.business_calendar_version_id,
                    version_number=version.version_number,
                    version_status=version.version_status,
                    timezone_name=version.timezone_name,
                    twenty_four_seven_flag=version.twenty_four_seven_flag,
                    effective_from=version.effective_from,
                    effective_to=version.effective_to,
                    published_at=version.published_at,
                )
                for version in calendar.versions
            ],
            working_periods=[
                AdminCalendarWorkingPeriodItem(
                    iso_day_of_week=period.iso_day_of_week,
                    start_local_time=period.start_local_time,
                    end_local_time=period.end_local_time,
                )
                for period in working_periods
            ],
            exceptions=[
                AdminCalendarExceptionItem(
                    exception_date=exception.exception_date,
                    exception_type=exception.exception_type,
                    start_local_time=exception.start_local_time,
                    end_local_time=exception.end_local_time,
                    description=exception.description,
                )
                for exception in exceptions
            ],
            linked_goals=[
                AdminCalendarLinkedGoalItem(sla_code=goal.sla_code, goal_name=goal.goal_name)
                for goal in calendar.linked_goals
            ],
        )

    async def request_types(
        self,
        context: RequestContext,
        *,
        search: str | None,
        active: bool | None,
        project_id: UUID | None,
        limit: int,
        offset: int,
    ) -> AdminRequestTypeListResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            rows = await AdminRepository(uow.session).request_types(
                tenant_id,
                search=search,
                active=active,
                project_id=project_id,
                limit=limit + 1,
                offset=offset,
            )
            await uow.commit()
        return AdminRequestTypeListResponse(
            items=[
                AdminRequestTypeSummary(
                    request_type_id=row.request_type_id,
                    request_type_code=row.request_type_code,
                    request_type_name=row.request_type_name,
                    portal_group=row.portal_group,
                    project_key=row.project_key,
                    project_name=row.project_name,
                    work_type_code=row.work_type_code,
                    workflow_code=row.workflow_code,
                    workflow_name=row.workflow_name,
                    employee_visible_flag=row.employee_visible_flag,
                    active_flag=row.active_flag,
                    display_order=row.display_order,
                    current_version_number=row.current_version_number,
                    current_version_status=row.current_version_status,
                    updated_at=row.updated_at,
                )
                for row in rows[:limit]
            ],
            has_more=len(rows) > limit,
        )

    async def request_type_detail(
        self, context: RequestContext, request_type_id: UUID
    ) -> AdminRequestTypeDetailResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            request_type = await repository.request_type(tenant_id, request_type_id)
            if request_type is None:
                raise NotFoundError("Request type not found.")
            form_fields = (
                await repository.request_type_form_fields(
                    tenant_id, request_type.displayed_version_id
                )
                if request_type.displayed_version_id is not None
                else ()
            )
            await uow.commit()
        return AdminRequestTypeDetailResponse(
            request_type_id=request_type.request_type_id,
            request_type_code=request_type.request_type_code,
            request_type_name=request_type.request_type_name,
            portal_description=request_type.portal_description,
            portal_group=request_type.portal_group,
            icon_name=request_type.icon_name,
            project_key=request_type.project_key,
            project_name=request_type.project_name,
            work_type_code=request_type.work_type_code,
            workflow_id=request_type.workflow_id,
            workflow_code=request_type.workflow_code,
            workflow_name=request_type.workflow_name,
            employee_visible_flag=request_type.employee_visible_flag,
            active_flag=request_type.active_flag,
            display_order=request_type.display_order,
            displayed_version_number=request_type.displayed_version_number,
            displayed_version_status=request_type.displayed_version_status,
            versions=[
                AdminRequestTypeVersionItem(
                    request_type_version_id=version.request_type_version_id,
                    version_number=version.version_number,
                    version_status=version.version_status,
                    effective_from=version.effective_from,
                    effective_to=version.effective_to,
                    published_at=version.published_at,
                )
                for version in request_type.versions
            ],
            form_fields=[self._form_field_item(field) for field in form_fields],
            created_at=request_type.created_at,
            updated_at=request_type.updated_at,
        )

    async def set_request_type_visibility(
        self,
        context: RequestContext,
        request_type_id: UUID,
        payload: AdminRequestTypeVisibilityRequest,
    ) -> AdminRequestTypeVisibilityResponse:
        tenant_id = self._tenant(context)
        async with self._factory(context) as uow:
            repository = AdminRepository(uow.session)
            current = await repository.request_type_for_update(tenant_id, request_type_id)
            if current is None:
                raise NotFoundError("Request type not found.")
            if (
                current.active_flag == payload.active
                and current.employee_visible_flag == payload.employee_visible
            ):
                await uow.commit()
                return AdminRequestTypeVisibilityResponse(
                    request_type_id=request_type_id,
                    active_flag=current.active_flag,
                    employee_visible_flag=current.employee_visible_flag,
                    updated_at=current.updated_at,
                    changed=False,
                )
            if current.updated_at != payload.expected_updated_at:
                raise ConcurrencyError(
                    "The request type was modified by someone else. Reload and try again."
                )
            updated = await repository.set_request_type_visibility(
                tenant_id,
                request_type_id,
                active=payload.active,
                employee_visible=payload.employee_visible,
            )
            await repository.record_admin_action(
                tenant_id,
                actor_id=context.user_id,
                action_code="ADMIN_REQUEST_TYPE_VISIBILITY_CHANGED",
                resource_type="REQUEST_TYPE",
                resource_id=str(request_type_id),
                change_summary={
                    "active_flag": {
                        "from": current.active_flag,
                        "to": updated.active_flag,
                    },
                    "employee_visible_flag": {
                        "from": current.employee_visible_flag,
                        "to": updated.employee_visible_flag,
                    },
                },
            )
            await uow.commit()
            return AdminRequestTypeVisibilityResponse(
                request_type_id=request_type_id,
                active_flag=updated.active_flag,
                employee_visible_flag=updated.employee_visible_flag,
                updated_at=updated.updated_at,
                changed=True,
            )

    @staticmethod
    def _transition_item(transition: WorkflowTransitionRow) -> AdminWorkflowTransitionItem:
        guard_summary = summarize_rules(transition.condition_payload)
        return AdminWorkflowTransitionItem(
            transition_id=transition.transition_id,
            transition_code=transition.transition_code,
            transition_name=transition.transition_name,
            from_status_code=transition.from_status_code,
            from_status_name=transition.from_status_name,
            to_status_code=transition.to_status_code,
            to_status_name=transition.to_status_name,
            display_order=transition.display_order,
            active_flag=transition.active_flag,
            guarded=bool(guard_summary),
            guard_summary=guard_summary,
            required_fields=transition_required_fields(transition.validator_payload),
            action_types=transition_action_types(transition.action_payload),
        )

    @staticmethod
    def _sla_goal_item(goal: SlaGoalRow) -> AdminSlaGoalItem:
        return AdminSlaGoalItem(
            sla_goal_id=goal.sla_goal_id,
            goal_name=goal.goal_name,
            priority_order=goal.priority_order,
            active_flag=goal.active_flag,
            target_minutes=goal.target_minutes,
            warning_minutes=goal.warning_minutes,
            calendar_code=goal.calendar_code,
            calendar_name=goal.calendar_name,
            version_number=goal.version_number,
            version_status=goal.version_status,
            match_summary=summarize_rules(goal.match_condition_payload),
        )

    @staticmethod
    def _form_field_item(field: FormFieldRow) -> AdminFormFieldItem:
        return AdminFormFieldItem(
            field_code=field.field_code,
            label=field.label,
            data_type=field.data_type,
            required_flag=field.required_flag,
            hidden_flag=field.hidden_flag,
            display_order=field.display_order,
            help_text=field.help_text,
            condition_summary=summarize_rules(field.condition_payload),
            options=[
                AdminFormFieldOptionItem(
                    option_code=option.option_code,
                    option_label=option.option_label,
                    display_order=option.display_order,
                    active_flag=option.active_flag,
                )
                for option in field.options
            ],
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
