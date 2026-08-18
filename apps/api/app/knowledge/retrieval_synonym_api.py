"""Synonym and acronym registry administration endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.retrieval_synonym_schemas import (
    RetrievalSynonymCommand,
    RetrievalSynonymListResponse,
    RetrievalSynonymResponse,
    SynonymStatus,
)
from apps.api.app.knowledge.retrieval_synonym_service import RetrievalSynonymService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Synonym registry permission denied"},
    409: {"model": ProblemResponse, "description": "Synonym registry conflict"},
    422: {"model": ProblemResponse, "description": "Synonym registry request invalid"},
}
router = APIRouter(prefix="/api/v1/admin/knowledge/retrieval-synonyms", tags=["knowledge-synonyms"])
ReadAdmin = Annotated[
    RequestContext,
    Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)),
]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=255,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def _service(request: Request) -> RetrievalSynonymService:
    return cast("RetrievalSynonymService", request.app.state.retrieval_synonym_service)


@router.get("", response_model=RetrievalSynonymListResponse, responses=ERRORS)
async def list_retrieval_synonyms(
    request: Request,
    context: ReadAdmin,
    status: Annotated[SynonymStatus | None, Query()] = None,
    term: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RetrievalSynonymListResponse:
    return await _service(request).list_entries(
        context, status=status, term=term, limit=limit, offset=offset
    )


@router.put(
    "",
    response_model=RetrievalSynonymResponse,
    status_code=201,
    responses=ERRORS,
)
async def put_retrieval_synonym(
    response: Response,
    request: Request,
    command: RetrievalSynonymCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_SOURCE_UPDATE, privileged_access=True)),
    ],
) -> RetrievalSynonymResponse:
    result = await _service(request).change(context, command, idempotency_key)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result
