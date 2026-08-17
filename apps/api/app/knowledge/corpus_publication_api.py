"""Human-triggered corpus publication and rollback endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.corpus_publication_schemas import (
    ActiveCorpusVersionResponse,
    CorpusVersionHistoryResponse,
    CorpusVersionResponse,
)
from apps.api.app.knowledge.corpus_publication_service import CorpusPublicationService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Corpus publication permission denied"},
    409: {"model": ProblemResponse, "description": "Corpus publication conflict"},
    422: {"model": ProblemResponse, "description": "Corpus publication request invalid"},
}
router = APIRouter(
    prefix="/api/v1/admin/knowledge/corpus-publications", tags=["knowledge-publication"]
)
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=255,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def _service(request: Request) -> CorpusPublicationService:
    return cast("CorpusPublicationService", request.app.state.corpus_publication_service)


@router.post(
    "",
    response_model=CorpusVersionResponse,
    status_code=201,
    responses=ERRORS,
)
async def publish_corpus(
    response: Response,
    request: Request,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_PUBLISH, privileged_access=True)),
    ],
) -> CorpusVersionResponse:
    result = await _service(request).publish(context, idempotency_key)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post(
    "/rollback",
    response_model=CorpusVersionResponse,
    status_code=201,
    responses=ERRORS,
)
async def rollback_corpus(
    response: Response,
    request: Request,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_PUBLISH, privileged_access=True)),
    ],
) -> CorpusVersionResponse:
    result = await _service(request).rollback(context, idempotency_key)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.get("/active", response_model=ActiveCorpusVersionResponse, responses=ERRORS)
async def active_corpus_version(
    request: Request,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)),
    ],
) -> ActiveCorpusVersionResponse:
    return await _service(request).active(context)


@router.get("", response_model=CorpusVersionHistoryResponse, responses=ERRORS)
async def corpus_version_history(
    request: Request,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)),
    ],
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CorpusVersionHistoryResponse:
    return await _service(request).history(context, limit=limit, offset=offset)
