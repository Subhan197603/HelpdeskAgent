"""Permission-gated, read-only AI governance endpoints."""

from datetime import datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request

from apps.api.app.ai.governance_schemas import (
    AIGovernanceOverviewResponse,
    AIPolicyListResponse,
    AIPolicySummaryResponse,
    AIUsageResponse,
)
from apps.api.app.ai.governance_service import AIGovernanceService
from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission

router = APIRouter(prefix="/api/v1/admin/ai", tags=["ai-governance"])

ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ProblemResponse, "description": "Invalid reporting range"},
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "AI governance access denied"},
    404: {"model": ProblemResponse, "description": "AI governance resource not found"},
    422: {"model": ProblemResponse, "description": "Request validation failed"},
}
_OVERSIGHT = Depends(require_permission(Permission.AI_OVERSIGHT, privileged_access=True))


def _service(request: Request) -> AIGovernanceService:
    return cast("AIGovernanceService", request.app.state.ai_governance_service)


@router.get("", response_model=AIGovernanceOverviewResponse, responses=ERRORS)
async def overview(
    request: Request, context: Annotated[RequestContext, _OVERSIGHT]
) -> AIGovernanceOverviewResponse:
    return await _service(request).overview(context)


@router.get("/policies", response_model=AIPolicyListResponse, responses=ERRORS)
async def policies(
    request: Request,
    context: Annotated[RequestContext, _OVERSIGHT],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> AIPolicyListResponse:
    return await _service(request).policies(context, limit=limit, offset=offset)


@router.get(
    "/policies/{feature_policy_id}",
    response_model=AIPolicySummaryResponse,
    responses=ERRORS,
)
async def policy(
    request: Request,
    context: Annotated[RequestContext, _OVERSIGHT],
    feature_policy_id: Annotated[UUID, Path()],
) -> AIPolicySummaryResponse:
    return await _service(request).policy(context, feature_policy_id)


@router.get("/usage", response_model=AIUsageResponse, responses=ERRORS)
async def usage(
    request: Request,
    context: Annotated[RequestContext, _OVERSIGHT],
    occurred_from: Annotated[datetime | None, Query()] = None,
    occurred_to: Annotated[datetime | None, Query()] = None,
    bucket: Annotated[str, Query(pattern="^day$")] = "day",
) -> AIUsageResponse:
    del bucket
    return await _service(request).usage(
        context, occurred_from=occurred_from, occurred_to=occurred_to
    )
