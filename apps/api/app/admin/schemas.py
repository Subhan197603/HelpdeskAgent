"""Administration shell contracts: real counts, safe status, audit reads."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

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


class AdminUserStatusRequest(BaseModel):
    active: bool
    expected_updated_at: datetime


class AdminUserStatusResponse(BaseModel):
    user_id: UUID
    active_flag: bool
    updated_at: datetime
    changed: bool


class AdminRoleAssignRequest(BaseModel):
    role_code: str = Field(pattern="^[A-Z][A-Z0-9_]{0,59}$")


class AdminRoleAssignmentChangeResponse(BaseModel):
    user_id: UUID
    role_code: str
    valid_from: datetime | None
    changed: bool


class AdminQueueMemberRequest(BaseModel):
    user_id: UUID
    member_role: MemberRole = "AGENT"


class AdminQueueMemberChangeResponse(BaseModel):
    support_group_id: UUID
    user_id: UUID
    member_role: MemberRole | None
    changed: bool


class AdminWorkflowSummary(BaseModel):
    workflow_id: UUID
    workflow_code: str
    workflow_name: str
    description: str | None
    active_flag: bool
    current_version_number: int | None
    current_version_status: str | None
    status_count: int
    transition_count: int
    request_type_count: int
    ticket_count: int
    created_at: datetime


class AdminWorkflowListResponse(BaseModel):
    items: list[AdminWorkflowSummary]
    has_more: bool


class AdminWorkflowVersionItem(BaseModel):
    workflow_version_id: UUID
    version_number: int
    version_status: str
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None
    published_by_display_name: str | None
    created_at: datetime
    ticket_count: int


class AdminWorkflowStatusItem(BaseModel):
    status_id: UUID
    status_code: str
    status_name: str
    status_category: str
    initial_flag: bool
    terminal_flag: bool
    customer_visible_name: str | None
    display_order: int


class AdminWorkflowTransitionItem(BaseModel):
    transition_id: UUID
    transition_code: str
    transition_name: str
    from_status_code: str
    from_status_name: str
    to_status_code: str
    to_status_name: str
    display_order: int
    active_flag: bool
    guarded: bool
    guard_summary: list[str]
    required_fields: list[str]
    action_types: list[str]


class AdminWorkflowRequestTypeItem(BaseModel):
    request_type_id: UUID
    request_type_code: str
    request_type_name: str
    active_flag: bool
    employee_visible_flag: bool


class AdminWorkflowDetailResponse(BaseModel):
    workflow_id: UUID
    workflow_code: str
    workflow_name: str
    description: str | None
    active_flag: bool
    created_at: datetime
    displayed_version_number: int | None
    displayed_version_status: str | None
    versions: list[AdminWorkflowVersionItem]
    statuses: list[AdminWorkflowStatusItem]
    transitions: list[AdminWorkflowTransitionItem]
    request_types: list[AdminWorkflowRequestTypeItem]


class AdminSlaPolicySummary(BaseModel):
    sla_definition_id: UUID
    sla_code: str
    sla_name: str
    metric_code: str
    project_key: str
    project_name: str
    active_flag: bool
    goal_count: int
    running_cycle_count: int
    breached_cycle_count: int


class AdminSlaPolicyListResponse(BaseModel):
    items: list[AdminSlaPolicySummary]
    has_more: bool


class AdminSlaGoalItem(BaseModel):
    sla_goal_id: UUID
    goal_name: str
    priority_order: int
    active_flag: bool
    target_minutes: int | None
    warning_minutes: int | None
    calendar_code: str | None
    calendar_name: str | None
    version_number: int | None
    version_status: str | None
    match_summary: list[str]


class AdminSlaVersionItem(BaseModel):
    sla_definition_version_id: UUID
    version_number: int
    version_status: str
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None


class AdminSlaCycleCounts(BaseModel):
    pending: int
    running: int
    paused: int
    completed: int
    breached: int
    cancelled: int


class AdminSlaPolicyDetailResponse(BaseModel):
    sla_definition_id: UUID
    sla_code: str
    sla_name: str
    metric_code: str
    description: str | None
    project_key: str
    project_name: str
    active_flag: bool
    start_condition_summary: list[str]
    pause_condition_summary: list[str]
    stop_condition_summary: list[str]
    goals: list[AdminSlaGoalItem]
    versions: list[AdminSlaVersionItem]
    cycle_counts: AdminSlaCycleCounts


class AdminCalendarSummary(BaseModel):
    calendar_id: UUID
    calendar_code: str
    calendar_name: str
    timezone_name: str
    twenty_four_seven_flag: bool
    active_flag: bool
    current_version_number: int | None
    current_version_status: str | None
    linked_goal_count: int


class AdminCalendarListResponse(BaseModel):
    items: list[AdminCalendarSummary]
    has_more: bool


class AdminCalendarVersionItem(BaseModel):
    business_calendar_version_id: UUID
    version_number: int
    version_status: str
    timezone_name: str
    twenty_four_seven_flag: bool
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None


class AdminCalendarWorkingPeriodItem(BaseModel):
    iso_day_of_week: int
    start_local_time: str
    end_local_time: str


class AdminCalendarExceptionItem(BaseModel):
    exception_date: str
    exception_type: str
    start_local_time: str | None
    end_local_time: str | None
    description: str | None


class AdminCalendarLinkedGoalItem(BaseModel):
    sla_code: str
    goal_name: str


class AdminCalendarDetailResponse(BaseModel):
    calendar_id: UUID
    calendar_code: str
    calendar_name: str
    timezone_name: str
    twenty_four_seven_flag: bool
    active_flag: bool
    displayed_version_number: int | None
    displayed_version_status: str | None
    versions: list[AdminCalendarVersionItem]
    working_periods: list[AdminCalendarWorkingPeriodItem]
    exceptions: list[AdminCalendarExceptionItem]
    linked_goals: list[AdminCalendarLinkedGoalItem]


class AdminRequestTypeSummary(BaseModel):
    request_type_id: UUID
    request_type_code: str
    request_type_name: str
    portal_group: str | None
    project_key: str
    project_name: str
    work_type_code: str
    workflow_code: str
    workflow_name: str
    employee_visible_flag: bool
    active_flag: bool
    display_order: int
    current_version_number: int | None
    current_version_status: str | None
    updated_at: datetime


class AdminRequestTypeListResponse(BaseModel):
    items: list[AdminRequestTypeSummary]
    has_more: bool


class AdminFormFieldOptionItem(BaseModel):
    option_code: str
    option_label: str
    display_order: int
    active_flag: bool


class AdminFormFieldItem(BaseModel):
    field_code: str
    label: str
    data_type: str
    required_flag: bool
    hidden_flag: bool
    display_order: int
    help_text: str | None
    condition_summary: list[str]
    options: list[AdminFormFieldOptionItem]


class AdminRequestTypeVersionItem(BaseModel):
    request_type_version_id: UUID
    version_number: int
    version_status: str
    effective_from: datetime | None
    effective_to: datetime | None
    published_at: datetime | None


class AdminRequestTypeDetailResponse(BaseModel):
    request_type_id: UUID
    request_type_code: str
    request_type_name: str
    portal_description: str | None
    portal_group: str | None
    icon_name: str | None
    project_key: str
    project_name: str
    work_type_code: str
    workflow_id: UUID
    workflow_code: str
    workflow_name: str
    employee_visible_flag: bool
    active_flag: bool
    display_order: int
    displayed_version_number: int | None
    displayed_version_status: str | None
    versions: list[AdminRequestTypeVersionItem]
    form_fields: list[AdminFormFieldItem]
    created_at: datetime
    updated_at: datetime


class AdminRequestTypeVisibilityRequest(BaseModel):
    active: bool
    employee_visible: bool
    expected_updated_at: datetime


class AdminRequestTypeVisibilityResponse(BaseModel):
    request_type_id: UUID
    active_flag: bool
    employee_visible_flag: bool
    updated_at: datetime
    changed: bool
