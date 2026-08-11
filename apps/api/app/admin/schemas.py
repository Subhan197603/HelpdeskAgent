"""Administration shell contracts: real counts, safe status, audit reads."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

OutcomeCode = Literal["SUCCESS", "DENIED", "FAILED", "PARTIAL"]
DecisionCode = Literal["ALLOWED", "DENIED"]


class AdminOverviewResponse(BaseModel):
    active_users: int
    support_groups: int
    open_tickets: int
    published_knowledge_documents: int


class DependencyStatusItem(BaseModel):
    name: str
    status: Literal["healthy", "unhealthy", "disabled"]
    required: bool


class SystemStatusResponse(BaseModel):
    app_version: str
    environment: str
    migration_head: str | None
    oidc_enabled: bool
    developer_identity_enabled: bool
    ai_globally_enabled: bool
    object_storage_enabled: bool
    clamav_required: bool
    metrics_endpoint_enabled: bool
    rls_enabled: bool
    retrieval_embedding_provider: str
    dependencies: list[DependencyStatusItem]


class AuditEventSummary(BaseModel):
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


class AuditEventListResponse(BaseModel):
    items: list[AuditEventSummary]
    has_more: bool


class SecurityEventSummary(BaseModel):
    id: int
    event_type: str
    decision_code: str
    user_id: UUID | None
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any]
    occurred_at: datetime


class SecurityEventListResponse(BaseModel):
    items: list[SecurityEventSummary]
    has_more: bool


MemberRole = Literal["AGENT", "LEAD", "MANAGER", "OBSERVER"]
Provisioning = Literal["JIT", "PRE_PROVISIONED"]


class AdminUserSummary(BaseModel):
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    business_unit_name: str | None
    role_codes: list[str]
    support_group_names: list[str]
    identity_provider_codes: list[str]
    created_at: datetime
    updated_at: datetime


class AdminUserListResponse(BaseModel):
    items: list[AdminUserSummary]
    has_more: bool


class AdminUserRoleItem(BaseModel):
    role_code: str
    role_name: str
    active_flag: bool
    valid_from: datetime
    valid_to: datetime | None


class AdminUserMembershipItem(BaseModel):
    support_group_id: UUID
    group_name: str
    member_role: str
    active_flag: bool
    joined_at: datetime


class AdminExternalIdentityItem(BaseModel):
    provider_code: str
    active_flag: bool
    last_authenticated_at: datetime | None


class AdminUserDetailResponse(BaseModel):
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    business_unit_name: str | None
    locale_code: str
    timezone_name: str
    provisioning: Provisioning
    oidc_linked: bool
    roles: list[AdminUserRoleItem]
    effective_permission_codes: list[str]
    memberships: list[AdminUserMembershipItem]
    external_identities: list[AdminExternalIdentityItem]
    recent_security_events: list[SecurityEventSummary]
    created_at: datetime
    updated_at: datetime


class AdminRoleSummary(BaseModel):
    role_code: str
    role_name: str
    description: str | None
    system_role_flag: bool
    active_flag: bool
    permission_count: int
    assigned_user_count: int


class AdminRoleListResponse(BaseModel):
    items: list[AdminRoleSummary]
    has_more: bool


class AdminPermissionGroup(BaseModel):
    domain: str
    permission_codes: list[str]


class AdminRoleAssignmentItem(BaseModel):
    user_id: UUID
    display_name: str
    email_address: str
    active_flag: bool
    valid_from: datetime
    valid_to: datetime | None


class AdminRoleDetailResponse(BaseModel):
    role_code: str
    role_name: str
    description: str | None
    system_role_flag: bool
    active_flag: bool
    permission_groups: list[AdminPermissionGroup]
    assignments: list[AdminRoleAssignmentItem]
    assignments_has_more: bool


class AdminQueueSummary(BaseModel):
    support_group_id: UUID
    group_code: str
    group_name: str
    contact_email: str | None
    assignment_method: str
    active_flag: bool
    member_count: int
    created_at: datetime
    updated_at: datetime


class AdminQueueListResponse(BaseModel):
    items: list[AdminQueueSummary]
    has_more: bool


class AdminQueueMemberItem(BaseModel):
    user_id: UUID
    display_name: str
    member_role: str
    active_flag: bool
    joined_at: datetime


class AdminTicketViewSummary(BaseModel):
    queue_id: UUID
    queue_name: str
    description: str | None
    project_code: str
    visibility: str
    display_order: int
    version_status: str | None
    active_flag: bool


class AdminQueueDetailResponse(BaseModel):
    support_group_id: UUID
    group_code: str
    group_name: str
    contact_email: str | None
    assignment_method: str
    active_flag: bool
    manager_display_name: str | None
    members: list[AdminQueueMemberItem]
    ticket_views: list[AdminTicketViewSummary]
    created_at: datetime
    updated_at: datetime


class AdminTicketViewListResponse(BaseModel):
    items: list[AdminTicketViewSummary]
    has_more: bool
