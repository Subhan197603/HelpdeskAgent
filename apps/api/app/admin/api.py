"""Administration shell endpoints: overview counts, system status, audit reads."""

from datetime import datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request

from apps.api.app.admin.schemas import (
    AdminCalendarDetailResponse,
    AdminCalendarListResponse,
    AdminOverviewResponse,
    AdminQueueDetailResponse,
    AdminQueueListResponse,
    AdminQueueMemberChangeResponse,
    AdminQueueMemberRequest,
    AdminRequestTypeDetailResponse,
    AdminRequestTypeListResponse,
    AdminRequestTypeVisibilityRequest,
    AdminRequestTypeVisibilityResponse,
    AdminRoleAssignmentChangeResponse,
    AdminRoleAssignRequest,
    AdminRoleDetailResponse,
    AdminRoleListResponse,
    AdminSlaPolicyDetailResponse,
    AdminSlaPolicyListResponse,
    AdminTicketViewListResponse,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserStatusRequest,
    AdminUserStatusResponse,
    AdminWorkflowDetailResponse,
    AdminWorkflowListResponse,
    AuditEventListResponse,
    DecisionCode,
    OutcomeCode,
    SecurityEventListResponse,
    SystemStatusResponse,
)
from apps.api.app.admin.service import AdminService
from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Administration access denied"},
    422: {"model": ProblemResponse, "description": "Administration request validation failed"},
}
router = APIRouter(prefix="/api/v1/admin", tags=["administration"])

Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]
FilterText = Annotated[str | None, Query(min_length=1, max_length=120)]
FilterCode = Annotated[str | None, Query(pattern="^[A-Z][A-Z0-9_]{0,59}$")]
FilterProvider = Annotated[str | None, Query(min_length=1, max_length=80)]
DETAIL_ERRORS: dict[int | str, dict[str, Any]] = {
    **ERRORS,
    404: {"model": ProblemResponse, "description": "Administration resource not found"},
}
_IDENTITY_READ = Depends(require_permission(Permission.ADMIN_IDENTITY_READ, privileged_access=True))
_IDENTITY_WRITE = Depends(
    require_permission(Permission.ADMIN_IDENTITY_WRITE, privileged_access=True)
)
_CONFIG_READ = Depends(require_permission(Permission.ADMIN_CONFIG_READ, privileged_access=True))
_CONFIG_WRITE = Depends(require_permission(Permission.ADMIN_CONFIG_WRITE, privileged_access=True))
MUTATION_ERRORS: dict[int | str, dict[str, Any]] = {
    **DETAIL_ERRORS,
    409: {
        "model": ProblemResponse,
        "description": "Concurrent modification or administrator safeguard conflict",
    },
}
RoleCode = Annotated[str, Path(pattern="^[A-Z][A-Z0-9_]{0,59}$")]


def _service(request: Request) -> AdminService:
    return cast("AdminService", request.app.state.admin_service)


@router.get("/overview", response_model=AdminOverviewResponse, responses=ERRORS)
async def overview(
    request: Request,
    context: Annotated[RequestContext, Depends(require_permission(Permission.ADMIN_IDENTITY_READ))],
) -> AdminOverviewResponse:
    return await _service(request).overview(context)


@router.get("/system-status", response_model=SystemStatusResponse, responses=ERRORS)
async def system_status(
    request: Request,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.SYSTEM_HEALTH_READ, privileged_access=True)),
    ],
) -> SystemStatusResponse:
    return await _service(request).system_status(context)


@router.get("/users", response_model=AdminUserListResponse, responses=ERRORS)
async def admin_users(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_READ],
    search: FilterText = None,
    active: bool | None = None,
    role_code: FilterCode = None,
    support_group_id: UUID | None = None,
    provider_code: FilterProvider = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminUserListResponse:
    return await _service(request).users(
        context,
        search=search,
        active=active,
        role_code=role_code,
        support_group_id=support_group_id,
        provider_code=provider_code,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse, responses=DETAIL_ERRORS)
async def admin_user_detail(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_READ],
    user_id: UUID,
) -> AdminUserDetailResponse:
    return await _service(request).user_detail(context, user_id)


@router.get("/roles", response_model=AdminRoleListResponse, responses=ERRORS)
async def admin_roles(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_READ],
    search: FilterText = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminRoleListResponse:
    return await _service(request).roles(context, search=search, limit=limit, offset=offset)


@router.get("/roles/{role_code}", response_model=AdminRoleDetailResponse, responses=DETAIL_ERRORS)
async def admin_role_detail(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_READ],
    role_code: Annotated[str, Path(pattern="^[A-Z][A-Z0-9_]{0,59}$")],
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminRoleDetailResponse:
    return await _service(request).role_detail(context, role_code, limit=limit, offset=offset)


@router.get("/queues", response_model=AdminQueueListResponse, responses=ERRORS)
async def admin_queues(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_READ],
    search: FilterText = None,
    active: bool | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminQueueListResponse:
    return await _service(request).queues(
        context, search=search, active=active, limit=limit, offset=offset
    )


@router.get(
    "/queues/{support_group_id}",
    response_model=AdminQueueDetailResponse,
    responses=DETAIL_ERRORS,
)
async def admin_queue_detail(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_READ],
    support_group_id: UUID,
) -> AdminQueueDetailResponse:
    return await _service(request).queue_detail(context, support_group_id)


@router.get("/ticket-views", response_model=AdminTicketViewListResponse, responses=ERRORS)
async def admin_ticket_views(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_READ],
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminTicketViewListResponse:
    return await _service(request).ticket_views(context, limit=limit, offset=offset)


@router.patch(
    "/users/{user_id}/status",
    response_model=AdminUserStatusResponse,
    responses=MUTATION_ERRORS,
)
async def admin_user_status(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_WRITE],
    user_id: UUID,
    payload: AdminUserStatusRequest,
) -> AdminUserStatusResponse:
    return await _service(request).set_user_status(context, user_id, payload)


@router.post(
    "/users/{user_id}/roles",
    response_model=AdminRoleAssignmentChangeResponse,
    responses=DETAIL_ERRORS,
)
async def admin_assign_role(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_WRITE],
    user_id: UUID,
    payload: AdminRoleAssignRequest,
) -> AdminRoleAssignmentChangeResponse:
    return await _service(request).assign_role(context, user_id, payload)


@router.delete(
    "/users/{user_id}/roles/{role_code}",
    response_model=AdminRoleAssignmentChangeResponse,
    responses=MUTATION_ERRORS,
)
async def admin_remove_role(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_WRITE],
    user_id: UUID,
    role_code: RoleCode,
) -> AdminRoleAssignmentChangeResponse:
    return await _service(request).remove_role(context, user_id, role_code)


@router.post(
    "/queues/{support_group_id}/members",
    response_model=AdminQueueMemberChangeResponse,
    responses=DETAIL_ERRORS,
)
async def admin_add_queue_member(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_WRITE],
    support_group_id: UUID,
    payload: AdminQueueMemberRequest,
) -> AdminQueueMemberChangeResponse:
    return await _service(request).add_queue_member(context, support_group_id, payload)


@router.delete(
    "/queues/{support_group_id}/members/{user_id}",
    response_model=AdminQueueMemberChangeResponse,
    responses=DETAIL_ERRORS,
)
async def admin_remove_queue_member(
    request: Request,
    context: Annotated[RequestContext, _IDENTITY_WRITE],
    support_group_id: UUID,
    user_id: UUID,
) -> AdminQueueMemberChangeResponse:
    return await _service(request).remove_queue_member(context, support_group_id, user_id)


@router.get("/workflows", response_model=AdminWorkflowListResponse, responses=ERRORS)
async def admin_workflows(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_READ],
    search: FilterText = None,
    active: bool | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminWorkflowListResponse:
    return await _service(request).workflows(
        context, search=search, active=active, limit=limit, offset=offset
    )


@router.get(
    "/workflows/{workflow_id}",
    response_model=AdminWorkflowDetailResponse,
    responses=DETAIL_ERRORS,
)
async def admin_workflow_detail(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_READ],
    workflow_id: UUID,
) -> AdminWorkflowDetailResponse:
    return await _service(request).workflow_detail(context, workflow_id)


@router.get("/sla-policies", response_model=AdminSlaPolicyListResponse, responses=ERRORS)
async def admin_sla_policies(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_READ],
    search: FilterText = None,
    active: bool | None = None,
    project_id: UUID | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminSlaPolicyListResponse:
    return await _service(request).sla_policies(
        context, search=search, active=active, project_id=project_id, limit=limit, offset=offset
    )


@router.get(
    "/sla-policies/{sla_definition_id}",
    response_model=AdminSlaPolicyDetailResponse,
    responses=DETAIL_ERRORS,
)
async def admin_sla_policy_detail(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_READ],
    sla_definition_id: UUID,
) -> AdminSlaPolicyDetailResponse:
    return await _service(request).sla_policy_detail(context, sla_definition_id)


@router.get("/calendars", response_model=AdminCalendarListResponse, responses=ERRORS)
async def admin_calendars(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_READ],
    search: FilterText = None,
    active: bool | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminCalendarListResponse:
    return await _service(request).calendars(
        context, search=search, active=active, limit=limit, offset=offset
    )


@router.get(
    "/calendars/{calendar_id}",
    response_model=AdminCalendarDetailResponse,
    responses=DETAIL_ERRORS,
)
async def admin_calendar_detail(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_READ],
    calendar_id: UUID,
) -> AdminCalendarDetailResponse:
    return await _service(request).calendar_detail(context, calendar_id)


@router.get("/catalogue", response_model=AdminRequestTypeListResponse, responses=ERRORS)
async def admin_catalogue(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_READ],
    search: FilterText = None,
    active: bool | None = None,
    project_id: UUID | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> AdminRequestTypeListResponse:
    return await _service(request).request_types(
        context, search=search, active=active, project_id=project_id, limit=limit, offset=offset
    )


@router.get(
    "/catalogue/{request_type_id}",
    response_model=AdminRequestTypeDetailResponse,
    responses=DETAIL_ERRORS,
)
async def admin_catalogue_detail(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_READ],
    request_type_id: UUID,
) -> AdminRequestTypeDetailResponse:
    return await _service(request).request_type_detail(context, request_type_id)


@router.patch(
    "/catalogue/{request_type_id}/visibility",
    response_model=AdminRequestTypeVisibilityResponse,
    responses=MUTATION_ERRORS,
)
async def admin_catalogue_visibility(
    request: Request,
    context: Annotated[RequestContext, _CONFIG_WRITE],
    request_type_id: UUID,
    payload: AdminRequestTypeVisibilityRequest,
) -> AdminRequestTypeVisibilityResponse:
    return await _service(request).set_request_type_visibility(context, request_type_id, payload)


@router.get("/audit/events", response_model=AuditEventListResponse, responses=ERRORS)
async def audit_events(
    request: Request,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.AUDIT_EVENT_READ, privileged_access=True)),
    ],
    resource_type: FilterText = None,
    action_code: FilterText = None,
    outcome_code: OutcomeCode | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> AuditEventListResponse:
    return await _service(request).audit_events(
        context,
        resource_type=resource_type,
        action_code=action_code,
        outcome_code=outcome_code,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )


@router.get("/audit/security-events", response_model=SecurityEventListResponse, responses=ERRORS)
async def security_events(
    request: Request,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.AUDIT_EVENT_READ, privileged_access=True)),
    ],
    event_type: FilterText = None,
    decision_code: DecisionCode | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
) -> SecurityEventListResponse:
    return await _service(request).security_events(
        context,
        event_type=event_type,
        decision_code=decision_code,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
        offset=offset,
    )
