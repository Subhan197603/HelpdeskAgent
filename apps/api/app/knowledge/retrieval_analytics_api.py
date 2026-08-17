"""Retrieval quality analytics and gap disposition endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.retrieval_analytics_schemas import (
    KnowledgeGapDispositionCommand,
    KnowledgeGapDispositionResponse,
    RetrievalAnalyticsSummaryResponse,
    RetrievalQueryGroupListResponse,
)
from apps.api.app.knowledge.retrieval_analytics_service import RetrievalAnalyticsService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Retrieval analytics permission denied"},
    409: {"model": ProblemResponse, "description": "Gap disposition conflict"},
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
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=255,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


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


@router.put(
    "/dispositions",
    response_model=KnowledgeGapDispositionResponse,
    status_code=201,
    responses=ERRORS,
)
async def put_gap_disposition(
    response: Response,
    request: Request,
    command: KnowledgeGapDispositionCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_SOURCE_UPDATE, privileged_access=True)),
    ],
) -> KnowledgeGapDispositionResponse:
    result = await _service(request).disposition(context, command, idempotency_key)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result


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
