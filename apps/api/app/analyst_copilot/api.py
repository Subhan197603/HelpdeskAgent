"""Analyst-only copilot endpoint."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Request

from apps.api.app.analyst_copilot.schemas import CopilotAnalysisRequest, CopilotAnalysisResponse
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
