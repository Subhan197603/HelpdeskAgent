"""Analyst-only copilot endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request

from apps.api.app.analyst_copilot.schemas import (
    CopilotAnalysisRequest,
    CopilotAnalysisResponse,
    CopilotDraftPostRequest,
    CopilotDraftPostResponse,
    CopilotDraftRequest,
    CopilotDraftResolveRequest,
    CopilotDraftResolveResponse,
    CopilotDraftResponse,
    CopilotFeedbackRequest,
    CopilotFeedbackResponse,
    CopilotUsageMetricsResponse,
    EvaluationDatasetResponse,
)
from apps.api.app.analyst_copilot.service import AnalystCopilotService
from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_authenticated_context

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Analyst copilot access denied"},
    404: {"model": ProblemResponse, "description": "Authorized ticket not found"},
    409: {"model": ProblemResponse, "description": "Copilot analysis conflict"},
    422: {"model": ProblemResponse, "description": "Request validation failed"},
    503: {"model": ProblemResponse, "description": "AI or retrieval unavailable"},
}
router = APIRouter(prefix="/api/v1/agent/tickets", tags=["analyst-copilot"])

_IDEMPOTENCY_KEY = Header(
    alias="Idempotency-Key",
    min_length=8,
    max_length=255,
    pattern=r"^[A-Za-z0-9._:-]+$",
)


def _service(request: Request) -> AnalystCopilotService:
    return cast("AnalystCopilotService", request.app.state.analyst_copilot_service)


@router.post(
    "/{ticket_key}/copilot/analysis",
    response_model=CopilotAnalysisResponse,
    responses=ERRORS,
)
async def analyze_ticket(
    request: Request,
    ticket_key: str,
    command: CopilotAnalysisRequest,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
) -> CopilotAnalysisResponse:
    return await _service(request).analyze(context, ticket_key, command)


@router.post(
    "/{ticket_key}/copilot/drafts",
    response_model=CopilotDraftResponse,
    responses=ERRORS,
)
async def draft_for_ticket(
    request: Request,
    ticket_key: str,
    command: CopilotDraftRequest,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
) -> CopilotDraftResponse:
    return await _service(request).draft(context, ticket_key, command)


@router.post(
    "/{ticket_key}/copilot/drafts/{draft_id}/post",
    response_model=CopilotDraftPostResponse,
    responses=ERRORS,
)
async def post_draft(
    request: Request,
    ticket_key: str,
    draft_id: UUID,
    command: CopilotDraftPostRequest,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
    idempotency_key: Annotated[str, _IDEMPOTENCY_KEY],
) -> CopilotDraftPostResponse:
    return await _service(request).post_draft(
        context, ticket_key, draft_id, command, idempotency_key
    )


@router.post(
    "/{ticket_key}/copilot/drafts/{draft_id}/resolve",
    response_model=CopilotDraftResolveResponse,
    responses=ERRORS,
)
async def resolve_with_draft(
    request: Request,
    ticket_key: str,
    draft_id: UUID,
    command: CopilotDraftResolveRequest,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
    idempotency_key: Annotated[str, _IDEMPOTENCY_KEY],
) -> CopilotDraftResolveResponse:
    return await _service(request).resolve_draft(
        context, ticket_key, draft_id, command, idempotency_key
    )


@router.post(
    "/{ticket_key}/copilot/runs/{agent_run_id}/feedback",
    response_model=CopilotFeedbackResponse,
    responses=ERRORS,
)
async def submit_run_feedback(
    request: Request,
    ticket_key: str,
    agent_run_id: UUID,
    command: CopilotFeedbackRequest,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
) -> CopilotFeedbackResponse:
    return await _service(request).submit_feedback(context, ticket_key, agent_run_id, command)


oversight_router = APIRouter(prefix="/api/v1/admin/ai/copilot", tags=["ai-oversight"])


@oversight_router.get(
    "/evaluation-dataset",
    response_model=EvaluationDatasetResponse,
    responses=ERRORS,
)
async def evaluation_dataset(
    request: Request,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> EvaluationDatasetResponse:
    return await _service(request).evaluation_dataset(context, limit)


@oversight_router.get(
    "/metrics",
    response_model=CopilotUsageMetricsResponse,
    responses=ERRORS,
)
async def copilot_usage_metrics(
    request: Request,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
) -> CopilotUsageMetricsResponse:
    return await _service(request).usage_metrics(context)
