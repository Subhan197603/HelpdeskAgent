"""Administration shell endpoints: overview counts, system status, audit reads."""

from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request

from apps.api.app.admin.schemas import (
    AdminOverviewResponse,
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
