"""Read-only chunk error-code index evidence endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Query, Request

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.error_code_index_schemas import ErrorCodeIndexListResponse
from apps.api.app.knowledge.error_code_index_service import ErrorCodeIndexService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Error-code index permission denied"},
    422: {"model": ProblemResponse, "description": "Error-code index request invalid"},
}
router = APIRouter(prefix="/api/v1/admin/knowledge/error-codes", tags=["knowledge-error-codes"])
ReadAdmin = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)),
]


def _service(request: Request) -> ErrorCodeIndexService:
    return cast("ErrorCodeIndexService", request.app.state.error_code_index_service)


@router.get("", response_model=ErrorCodeIndexListResponse, responses=ERRORS)
async def list_error_codes(
    request: Request,
    context: ReadAdmin,
    prefix: Annotated[
        str | None, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9 _-]+$")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ErrorCodeIndexListResponse:
    return await _service(request).listing(context, prefix=prefix, limit=limit, offset=offset)
