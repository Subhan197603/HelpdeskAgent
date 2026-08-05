"""Analyst dashboard endpoint."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.reporting.schemas import AnalystDashboardResponse
from apps.api.app.reporting.service import DashboardService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
}
router = APIRouter(tags=["reporting"])


@router.get(
    "/api/v1/agent/dashboard",
    response_model=AnalystDashboardResponse,
    responses=ERRORS,
)
async def agent_dashboard(
    request: Request,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> AnalystDashboardResponse:
    service = cast("DashboardService", request.app.state.dashboard_service)
    return await service.dashboard(context)
