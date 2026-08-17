"""Read-only retrieval quality analytics endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.retrieval_analytics_schemas import (
    RetrievalAnalyticsSummaryResponse,
    RetrievalQueryGroupListResponse,
)
from apps.api.app.knowledge.retrieval_analytics_service import RetrievalAnalyticsService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Retrieval analytics permission denied"},
    422: {"model": ProblemResponse, "description": "Retrieval analytics request invalid"},
}
router = APIRouter(
    prefix="/api/v1/admin/knowledge/retrieval-analytics", tags=["knowledge-analytics"]
)
ReadAdmin = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)),
]
WindowDays = Annotated[int, Query(ge=1, le=365)]


def _service(request: Request) -> RetrievalAnalyticsService:
    return cast("RetrievalAnalyticsService", request.app.state.retrieval_analytics_service)


@router.get("/summary", response_model=RetrievalAnalyticsSummaryResponse, responses=ERRORS)
async def retrieval_analytics_summary(
    request: Request,
    context: ReadAdmin,
    days: WindowDays = 30,
) -> RetrievalAnalyticsSummaryResponse:
    return await _service(request).summary(context, window_days=days)


@router.get(
    "/zero-result-queries",
    response_model=RetrievalQueryGroupListResponse,
    responses=ERRORS,
)
async def zero_result_queries(
    request: Request,
    context: ReadAdmin,
    days: WindowDays = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RetrievalQueryGroupListResponse:
    return await _service(request).zero_result_groups(
        context, window_days=days, limit=limit, offset=offset
    )


@router.get(
    "/low-confidence-queries",
    response_model=RetrievalQueryGroupListResponse,
    responses=ERRORS,
)
async def low_confidence_queries(
    request: Request,
    context: ReadAdmin,
    days: WindowDays = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RetrievalQueryGroupListResponse:
    return await _service(request).low_confidence_groups(
        context, window_days=days, limit=limit, offset=offset
    )
