"""Tenant-scoped administration reads over identity, ticket, kb, and audit data."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_OVERVIEW = text("""
SELECT
  (SELECT count(*) FROM identity.app_user app_user
    WHERE app_user.tenant_id=:tenant_id AND app_user.active_flag) AS active_users,
  (SELECT count(*) FROM identity.support_group support_group
    WHERE support_group.tenant_id=:tenant_id AND support_group.active_flag) AS support_groups,
  (SELECT count(*) FROM itsm.ticket ticket
    JOIN config.workflow_status status ON status.status_id=ticket.status_id
    WHERE ticket.tenant_id=:tenant_id AND NOT status.terminal_flag) AS open_tickets,
  (SELECT count(*) FROM kb.document document
    JOIN kb.document_version version ON version.document_id=document.document_id
      AND version.current_version_flag
      AND version.published_processing_version_id IS NOT NULL
    WHERE (document.tenant_id IS NULL OR document.tenant_id=:tenant_id)
      AND document.active_flag
      AND document.approval_status='APPROVED') AS published_knowledge_documents
""")

_AUDIT_EVENTS = text("""
SELECT audit_event_id,actor_id,actor_type,action_code,resource_type,resource_id,
  outcome_code,failure_reason,change_summary_json,correlation_id,request_id,occurred_at
FROM audit.audit_event
WHERE tenant_id=:tenant_id
  AND (CAST(:resource_type AS text) IS NULL OR resource_type=:resource_type)
  AND (CAST(:action_code AS text) IS NULL OR action_code=:action_code)
  AND (CAST(:outcome_code AS text) IS NULL OR outcome_code=:outcome_code)
  AND (CAST(:occurred_from AS timestamptz) IS NULL OR occurred_at>=:occurred_from)
  AND (CAST(:occurred_to AS timestamptz) IS NULL OR occurred_at<=:occurred_to)
ORDER BY occurred_at DESC,audit_event_id DESC
LIMIT :result_limit OFFSET :result_offset
""")

_USERS = text("""
SELECT app_user.user_id,app_user.display_name,app_user.email_address,app_user.active_flag,
  app_user.created_at,app_user.updated_at,business_unit.business_unit_name,
  COALESCE((SELECT array_agg(effective_role.role_code ORDER BY effective_role.role_code)
    FROM (SELECT DISTINCT user_role.role_code FROM identity.user_role user_role
      WHERE user_role.tenant_id=:tenant_id AND user_role.user_id=app_user.user_id
        AND user_role.active_flag AND user_role.valid_from<=CURRENT_TIMESTAMP
        AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
    ) effective_role),CAST('{}' AS text[])) AS role_codes,
  COALESCE((SELECT array_agg(support_group.group_name ORDER BY support_group.group_name)
    FROM identity.support_group_member member
    JOIN identity.support_group support_group
      ON support_group.support_group_id=member.support_group_id
      AND support_group.tenant_id=:tenant_id AND support_group.active_flag
    WHERE member.user_id=app_user.user_id AND member.active_flag),
    CAST('{}' AS text[])) AS support_group_names,
  COALESCE((SELECT array_agg(provider.provider_code ORDER BY provider.provider_code)
    FROM (SELECT DISTINCT mapping.provider_code FROM identity.external_identity external_identity
      JOIN identity.oidc_tenant_mapping mapping
        ON mapping.oidc_tenant_mapping_id=external_identity.oidc_tenant_mapping_id
      WHERE external_identity.tenant_id=:tenant_id
        AND external_identity.user_id=app_user.user_id AND external_identity.active_flag
    ) provider),CAST('{}' AS text[])) AS identity_provider_codes
FROM identity.app_user app_user
LEFT JOIN identity.business_unit business_unit
  ON business_unit.business_unit_id=app_user.business_unit_id
WHERE app_user.tenant_id=:tenant_id
  AND (CAST(:active AS boolean) IS NULL OR app_user.active_flag=:active)
  AND (CAST(:search_pattern AS text) IS NULL
    OR app_user.display_name ILIKE :search_pattern ESCAPE '\\'
    OR app_user.email_address ILIKE :search_pattern ESCAPE '\\')
  AND (CAST(:role_code AS text) IS NULL OR EXISTS (
    SELECT 1 FROM identity.user_role filter_role
    WHERE filter_role.tenant_id=:tenant_id AND filter_role.user_id=app_user.user_id
      AND filter_role.role_code=:role_code AND filter_role.active_flag
      AND filter_role.valid_from<=CURRENT_TIMESTAMP
      AND (filter_role.valid_to IS NULL OR filter_role.valid_to>CURRENT_TIMESTAMP)))
  AND (CAST(:support_group_id AS uuid) IS NULL OR EXISTS (
    SELECT 1 FROM identity.support_group_member filter_member
    JOIN identity.support_group filter_group
      ON filter_group.support_group_id=filter_member.support_group_id
      AND filter_group.tenant_id=:tenant_id
    WHERE filter_member.user_id=app_user.user_id AND filter_member.active_flag
      AND filter_member.support_group_id=:support_group_id))
  AND (CAST(:provider_code AS text) IS NULL OR EXISTS (
    SELECT 1 FROM identity.external_identity filter_identity
    JOIN identity.oidc_tenant_mapping filter_mapping
      ON filter_mapping.oidc_tenant_mapping_id=filter_identity.oidc_tenant_mapping_id
    WHERE filter_identity.tenant_id=:tenant_id AND filter_identity.user_id=app_user.user_id
      AND filter_identity.active_flag AND filter_mapping.provider_code=:provider_code))
ORDER BY app_user.display_name,app_user.user_id
LIMIT :result_limit OFFSET :result_offset
""")

_USER_PROFILE = text("""
SELECT app_user.user_id,app_user.display_name,app_user.email_address,app_user.active_flag,
  app_user.external_subject,app_user.locale_code,app_user.timezone_name,
  app_user.created_at,app_user.updated_at,business_unit.business_unit_name,
  COALESCE((SELECT json_agg(json_build_object(
      'provider_code',mapping.provider_code,
      'active_flag',external_identity.active_flag,
      'last_authenticated_at',external_identity.last_authenticated_at)
      ORDER BY mapping.provider_code)
    FROM identity.external_identity external_identity
    JOIN identity.oidc_tenant_mapping mapping
      ON mapping.oidc_tenant_mapping_id=external_identity.oidc_tenant_mapping_id
    WHERE external_identity.tenant_id=:tenant_id
      AND external_identity.user_id=app_user.user_id),CAST('[]' AS json)) AS external_identities
FROM identity.app_user app_user
LEFT JOIN identity.business_unit business_unit
  ON business_unit.business_unit_id=app_user.business_unit_id
WHERE app_user.tenant_id=:tenant_id AND app_user.user_id=:user_id
""")

_USER_ROLES = text("""
SELECT user_role.role_code,role_definition.role_name,user_role.active_flag,
  user_role.valid_from,user_role.valid_to
FROM identity.user_role user_role
JOIN identity.role_definition role_definition
  ON role_definition.role_code=user_role.role_code AND role_definition.active_flag
WHERE user_role.tenant_id=:tenant_id AND user_role.user_id=:user_id
  AND user_role.active_flag AND user_role.valid_from<=CURRENT_TIMESTAMP
  AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
ORDER BY user_role.role_code,user_role.valid_from DESC
""")

_USER_MEMBERSHIPS = text("""
SELECT member.support_group_id,support_group.group_name,member.member_role,
  member.active_flag,member.joined_at
FROM identity.support_group_member member
JOIN identity.support_group support_group
  ON support_group.support_group_id=member.support_group_id
  AND support_group.tenant_id=:tenant_id
WHERE member.user_id=:user_id
ORDER BY support_group.group_name,member.support_group_id
""")

_USER_SECURITY_EVENTS = text("""
SELECT security_event_id,event_type,decision_code,user_id,resource_type,resource_id,
  event_data_json,occurred_at
FROM audit.security_event
WHERE tenant_id=:tenant_id AND user_id=:user_id
ORDER BY occurred_at DESC,security_event_id DESC
LIMIT :result_limit
""")

_ROLES = text("""
SELECT role_definition.role_code,role_definition.role_name,role_definition.description,
  role_definition.system_role_flag,role_definition.active_flag,
  COALESCE(assignment.assigned_user_count,0) AS assigned_user_count
FROM identity.role_definition role_definition
LEFT JOIN (
  SELECT user_role.role_code,count(DISTINCT user_role.user_id) AS assigned_user_count
  FROM identity.user_role user_role
  WHERE user_role.tenant_id=:tenant_id AND user_role.active_flag
    AND user_role.valid_from<=CURRENT_TIMESTAMP
    AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
  GROUP BY user_role.role_code) assignment
  ON assignment.role_code=role_definition.role_code
WHERE (CAST(:search_pattern AS text) IS NULL
  OR role_definition.role_code ILIKE :search_pattern ESCAPE '\\'
  OR role_definition.role_name ILIKE :search_pattern ESCAPE '\\')
ORDER BY role_definition.role_code
LIMIT :result_limit OFFSET :result_offset
""")

_ROLE = text("""
SELECT role_code,role_name,description,system_role_flag,active_flag
FROM identity.role_definition
WHERE role_code=:role_code
""")

_ROLE_ASSIGNMENTS = text("""
SELECT app_user.user_id,app_user.display_name,app_user.email_address,app_user.active_flag,
  user_role.valid_from,user_role.valid_to
FROM identity.user_role user_role
JOIN identity.app_user app_user
  ON app_user.user_id=user_role.user_id AND app_user.tenant_id=:tenant_id
WHERE user_role.tenant_id=:tenant_id AND user_role.role_code=:role_code
  AND user_role.active_flag AND user_role.valid_from<=CURRENT_TIMESTAMP
  AND (user_role.valid_to IS NULL OR user_role.valid_to>CURRENT_TIMESTAMP)
ORDER BY app_user.display_name,app_user.user_id
LIMIT :result_limit OFFSET :result_offset
""")

_QUEUES = text("""
SELECT support_group.support_group_id,support_group.group_code,support_group.group_name,
  support_group.email_address,support_group.assignment_method,support_group.active_flag,
  support_group.created_at,support_group.updated_at,
  COALESCE(member.member_count,0) AS member_count
FROM identity.support_group support_group
LEFT JOIN (
  SELECT support_group_member.support_group_id,count(*) AS member_count
  FROM identity.support_group_member support_group_member
  WHERE support_group_member.active_flag
  GROUP BY support_group_member.support_group_id) member
  ON member.support_group_id=support_group.support_group_id
WHERE support_group.tenant_id=:tenant_id
  AND (CAST(:active AS boolean) IS NULL OR support_group.active_flag=:active)
  AND (CAST(:search_pattern AS text) IS NULL
    OR support_group.group_code ILIKE :search_pattern ESCAPE '\\'
    OR support_group.group_name ILIKE :search_pattern ESCAPE '\\')
ORDER BY support_group.group_name,support_group.support_group_id
LIMIT :result_limit OFFSET :result_offset
""")

_QUEUE = text("""
SELECT support_group.support_group_id,support_group.group_code,support_group.group_name,
  support_group.email_address,support_group.assignment_method,support_group.active_flag,
  support_group.created_at,support_group.updated_at,
  manager.display_name AS manager_display_name
FROM identity.support_group support_group
LEFT JOIN identity.app_user manager ON manager.user_id=support_group.manager_user_id
WHERE support_group.tenant_id=:tenant_id AND support_group.support_group_id=:support_group_id
""")

_QUEUE_MEMBERS = text("""
SELECT member.user_id,app_user.display_name,member.member_role,member.active_flag,
  member.joined_at
FROM identity.support_group_member member
JOIN identity.support_group support_group
  ON support_group.support_group_id=member.support_group_id
  AND support_group.tenant_id=:tenant_id
JOIN identity.app_user app_user ON app_user.user_id=member.user_id
WHERE member.support_group_id=:support_group_id
ORDER BY app_user.display_name,member.user_id
""")

_TICKET_VIEWS = text("""
SELECT queue_definition.queue_id,queue_definition.queue_name,queue_definition.description,
  service_project.project_key AS project_code,queue_definition.visibility_type,
  queue_definition.display_order,queue_definition.active_flag,version.version_status
FROM config.queue_definition queue_definition
JOIN config.service_project service_project
  ON service_project.project_id=queue_definition.project_id
LEFT JOIN LATERAL (
  SELECT queue_definition_version.version_status
  FROM config.queue_definition_version queue_definition_version
  WHERE queue_definition_version.queue_id=queue_definition.queue_id
  ORDER BY queue_definition_version.version_number DESC
  LIMIT 1) version ON true
WHERE queue_definition.tenant_id=:tenant_id
  AND (CAST(:owner_group_id AS uuid) IS NULL
    OR queue_definition.owner_group_id=:owner_group_id)
ORDER BY queue_definition.display_order,queue_definition.queue_name,queue_definition.queue_id
LIMIT :result_limit OFFSET :result_offset
""")

_SECURITY_EVENTS = text("""
SELECT security_event_id,event_type,decision_code,user_id,resource_type,resource_id,
  event_data_json,occurred_at
FROM audit.security_event
WHERE tenant_id=:tenant_id
  AND (CAST(:event_type AS text) IS NULL OR event_type=:event_type)
  AND (CAST(:decision_code AS text) IS NULL OR decision_code=:decision_code)
  AND (CAST(:occurred_from AS timestamptz) IS NULL OR occurred_at>=:occurred_from)
  AND (CAST(:occurred_to AS timestamptz) IS NULL OR occurred_at<=:occurred_to)
ORDER BY occurred_at DESC,security_event_id DESC
LIMIT :result_limit OFFSET :result_offset
""")


@dataclass(frozen=True, slots=True)
class OverviewCounts:
    active_users: int
    support_groups: int
    open_tickets: int
    published_knowledge_documents: int


@dataclass(frozen=True, slots=True)
class AuditEventRow:
    id: int
    actor_id: str | None
    actor_type: str
    action_code: str
    resource_type: str
    resource_id: str | None
    outcome_code: str
    failure_reason: str | None
    change_summary: dict[str, Any]
    correlation_id: UUID | None
    request_id: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SecurityEventRow:
    id: int
    event_type: str
    decision_code: str
    user_id: UUID | None
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AdminUserRow:
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    business_unit_name: str | None
    role_codes: tuple[str, ...]
    support_group_names: tuple[str, ...]
    identity_provider_codes: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ExternalIdentityRow:
    provider_code: str
    active_flag: bool
    last_authenticated_at: datetime | None


@dataclass(frozen=True, slots=True)
class AdminUserProfileRow:
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    external_subject: str
    locale_code: str
    timezone_name: str
    business_unit_name: str | None
    external_identities: tuple[ExternalIdentityRow, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserRoleRow:
    role_code: str
    role_name: str
    active_flag: bool
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class UserMembershipRow:
    support_group_id: UUID
    group_name: str
    member_role: str
    active_flag: bool
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class RoleSummaryRow:
    role_code: str
    role_name: str
    description: str | None
    system_role_flag: bool
    active_flag: bool
    assigned_user_count: int


@dataclass(frozen=True, slots=True)
class RoleAssignmentRow:
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    valid_from: datetime
    valid_to: datetime | None


@dataclass(frozen=True, slots=True)
class QueueSummaryRow:
    support_group_id: UUID
    group_code: str
    group_name: str
    contact_email: str | None
    assignment_method: str
    active_flag: bool
    member_count: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QueueDetailRow:
    support_group_id: UUID
    group_code: str
    group_name: str
    contact_email: str | None
    assignment_method: str
    active_flag: bool
    manager_display_name: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QueueMemberRow:
    user_id: UUID
    display_name: str
    member_role: str
    active_flag: bool
    joined_at: datetime


@dataclass(frozen=True, slots=True)
class TicketViewRow:
    queue_id: UUID
    queue_name: str
    description: str | None
    project_code: str
    visibility: str
    display_order: int
    version_status: str | None
    active_flag: bool


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def escape_like_pattern(search: str | None) -> str | None:
    """A contains-pattern with LIKE wildcards neutralised, or None when unset."""
    if search is None:
        return None
    escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _identity_timestamp(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _external_identities(value: object) -> tuple[ExternalIdentityRow, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        ExternalIdentityRow(
            provider_code=str(item["provider_code"]),
            active_flag=bool(item["active_flag"]),
            last_authenticated_at=_identity_timestamp(item.get("last_authenticated_at")),
        )
        for item in value
        if isinstance(item, dict)
    )


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def overview(self, tenant_id: UUID) -> OverviewCounts:
        row = (await self._session.execute(_OVERVIEW, {"tenant_id": tenant_id})).one()
        return OverviewCounts(
            active_users=int(row.active_users),
            support_groups=int(row.support_groups),
            open_tickets=int(row.open_tickets),
            published_knowledge_documents=int(row.published_knowledge_documents),
        )

    async def audit_events(
        self,
        tenant_id: UUID,
        *,
        resource_type: str | None,
        action_code: str | None,
        outcome_code: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[AuditEventRow, ...]:
        rows = (
            await self._session.execute(
                _AUDIT_EVENTS,
                {
                    "tenant_id": tenant_id,
                    "resource_type": resource_type,
                    "action_code": action_code,
                    "outcome_code": outcome_code,
                    "occurred_from": occurred_from,
                    "occurred_to": occurred_to,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            AuditEventRow(
                id=int(row.audit_event_id),
                actor_id=row.actor_id,
                actor_type=row.actor_type,
                action_code=row.action_code,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                outcome_code=row.outcome_code,
                failure_reason=row.failure_reason,
                change_summary=_mapping(row.change_summary_json),
                correlation_id=row.correlation_id,
                request_id=row.request_id,
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def security_events(
        self,
        tenant_id: UUID,
        *,
        event_type: str | None,
        decision_code: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[SecurityEventRow, ...]:
        rows = (
            await self._session.execute(
                _SECURITY_EVENTS,
                {
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "decision_code": decision_code,
                    "occurred_from": occurred_from,
                    "occurred_to": occurred_to,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            SecurityEventRow(
                id=int(row.security_event_id),
                event_type=row.event_type,
                decision_code=row.decision_code,
                user_id=row.user_id,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                details=_mapping(row.event_data_json),
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def users(
        self,
        tenant_id: UUID,
        *,
        search: str | None,
        active: bool | None,
        role_code: str | None,
        support_group_id: UUID | None,
        provider_code: str | None,
        limit: int,
        offset: int,
    ) -> tuple[AdminUserRow, ...]:
        rows = (
            await self._session.execute(
                _USERS,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "active": active,
                    "role_code": role_code,
                    "support_group_id": support_group_id,
                    "provider_code": provider_code,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            AdminUserRow(
                user_id=row.user_id,
                display_name=row.display_name,
                email_address=row.email_address,
                active_flag=row.active_flag,
                business_unit_name=row.business_unit_name,
                role_codes=tuple(row.role_codes),
                support_group_names=tuple(row.support_group_names),
                identity_provider_codes=tuple(row.identity_provider_codes),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        )

    async def user_profile(self, tenant_id: UUID, user_id: UUID) -> AdminUserProfileRow | None:
        row = (
            await self._session.execute(_USER_PROFILE, {"tenant_id": tenant_id, "user_id": user_id})
        ).one_or_none()
        if row is None:
            return None
        return AdminUserProfileRow(
            user_id=row.user_id,
            display_name=row.display_name,
            email_address=row.email_address,
            active_flag=row.active_flag,
            external_subject=row.external_subject,
            locale_code=row.locale_code,
            timezone_name=row.timezone_name,
            business_unit_name=row.business_unit_name,
            external_identities=_external_identities(row.external_identities),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def user_roles(self, tenant_id: UUID, user_id: UUID) -> tuple[UserRoleRow, ...]:
        rows = (
            await self._session.execute(_USER_ROLES, {"tenant_id": tenant_id, "user_id": user_id})
        ).all()
        return tuple(
            UserRoleRow(
                role_code=row.role_code,
                role_name=row.role_name,
                active_flag=row.active_flag,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
            )
            for row in rows
        )

    async def user_memberships(
        self, tenant_id: UUID, user_id: UUID
    ) -> tuple[UserMembershipRow, ...]:
        rows = (
            await self._session.execute(
                _USER_MEMBERSHIPS, {"tenant_id": tenant_id, "user_id": user_id}
            )
        ).all()
        return tuple(
            UserMembershipRow(
                support_group_id=row.support_group_id,
                group_name=row.group_name,
                member_role=row.member_role,
                active_flag=row.active_flag,
                joined_at=row.joined_at,
            )
            for row in rows
        )

    async def user_security_events(
        self, tenant_id: UUID, user_id: UUID, *, limit: int
    ) -> tuple[SecurityEventRow, ...]:
        rows = (
            await self._session.execute(
                _USER_SECURITY_EVENTS,
                {"tenant_id": tenant_id, "user_id": user_id, "result_limit": limit},
            )
        ).all()
        return tuple(
            SecurityEventRow(
                id=int(row.security_event_id),
                event_type=row.event_type,
                decision_code=row.decision_code,
                user_id=row.user_id,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                details=_mapping(row.event_data_json),
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def roles(
        self, tenant_id: UUID, *, search: str | None, limit: int, offset: int
    ) -> tuple[RoleSummaryRow, ...]:
        rows = (
            await self._session.execute(
                _ROLES,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            RoleSummaryRow(
                role_code=row.role_code,
                role_name=row.role_name,
                description=row.description,
                system_role_flag=row.system_role_flag,
                active_flag=row.active_flag,
                assigned_user_count=int(row.assigned_user_count),
            )
            for row in rows
        )

    async def role(self, role_code: str) -> RoleSummaryRow | None:
        row = (await self._session.execute(_ROLE, {"role_code": role_code})).one_or_none()
        if row is None:
            return None
        return RoleSummaryRow(
            role_code=row.role_code,
            role_name=row.role_name,
            description=row.description,
            system_role_flag=row.system_role_flag,
            active_flag=row.active_flag,
            assigned_user_count=0,
        )

    async def role_assignments(
        self, tenant_id: UUID, role_code: str, *, limit: int, offset: int
    ) -> tuple[RoleAssignmentRow, ...]:
        rows = (
            await self._session.execute(
                _ROLE_ASSIGNMENTS,
                {
                    "tenant_id": tenant_id,
                    "role_code": role_code,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            RoleAssignmentRow(
                user_id=row.user_id,
                display_name=row.display_name,
                email_address=row.email_address,
                active_flag=row.active_flag,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
            )
            for row in rows
        )

    async def queues(
        self,
        tenant_id: UUID,
        *,
        search: str | None,
        active: bool | None,
        limit: int,
        offset: int,
    ) -> tuple[QueueSummaryRow, ...]:
        rows = (
            await self._session.execute(
                _QUEUES,
                {
                    "tenant_id": tenant_id,
                    "search_pattern": escape_like_pattern(search),
                    "active": active,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            QueueSummaryRow(
                support_group_id=row.support_group_id,
                group_code=row.group_code,
                group_name=row.group_name,
                contact_email=row.email_address,
                assignment_method=row.assignment_method,
                active_flag=row.active_flag,
                member_count=int(row.member_count),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        )

    async def queue(self, tenant_id: UUID, support_group_id: UUID) -> QueueDetailRow | None:
        row = (
            await self._session.execute(
                _QUEUE, {"tenant_id": tenant_id, "support_group_id": support_group_id}
            )
        ).one_or_none()
        if row is None:
            return None
        return QueueDetailRow(
            support_group_id=row.support_group_id,
            group_code=row.group_code,
            group_name=row.group_name,
            contact_email=row.email_address,
            assignment_method=row.assignment_method,
            active_flag=row.active_flag,
            manager_display_name=row.manager_display_name,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def queue_members(
        self, tenant_id: UUID, support_group_id: UUID
    ) -> tuple[QueueMemberRow, ...]:
        rows = (
            await self._session.execute(
                _QUEUE_MEMBERS, {"tenant_id": tenant_id, "support_group_id": support_group_id}
            )
        ).all()
        return tuple(
            QueueMemberRow(
                user_id=row.user_id,
                display_name=row.display_name,
                member_role=row.member_role,
                active_flag=row.active_flag,
                joined_at=row.joined_at,
            )
            for row in rows
        )

    async def ticket_views(
        self,
        tenant_id: UUID,
        *,
        owner_group_id: UUID | None,
        limit: int,
        offset: int,
    ) -> tuple[TicketViewRow, ...]:
        rows = (
            await self._session.execute(
                _TICKET_VIEWS,
                {
                    "tenant_id": tenant_id,
                    "owner_group_id": owner_group_id,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            TicketViewRow(
                queue_id=row.queue_id,
                queue_name=row.queue_name,
                description=row.description,
                project_code=row.project_code,
                visibility=row.visibility_type,
                display_order=int(row.display_order),
                version_status=row.version_status,
                active_flag=row.active_flag,
            )
            for row in rows
        )
