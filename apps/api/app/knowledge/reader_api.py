"""Persona-authorized published knowledge article endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_authenticated_context
from apps.api.app.knowledge.reader_schemas import (
    DocumentTypeCode,
    KnowledgeArticleDetailResponse,
    KnowledgeArticleListResponse,
    ReaderPersona,
)
from apps.api.app.knowledge.reader_service import KnowledgeReaderService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Knowledge access denied"},
    404: {"model": ProblemResponse, "description": "Knowledge article not found"},
    422: {"model": ProblemResponse, "description": "Article request validation failed"},
}
router = APIRouter(prefix="/api/v1/knowledge/articles", tags=["knowledge-articles"])


def _service(request: Request) -> KnowledgeReaderService:
    return cast("KnowledgeReaderService", request.app.state.knowledge_reader_service)


@router.get("", response_model=KnowledgeArticleListResponse, responses=ERRORS)
async def list_articles(
    request: Request,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
    persona: ReaderPersona = "EMPLOYEE",
    document_type: DocumentTypeCode | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> KnowledgeArticleListResponse:
    return await _service(request).articles(
        context,
        persona=persona,
        document_type=document_type,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=KnowledgeArticleDetailResponse, responses=ERRORS)
async def get_article(
    request: Request,
    document_id: UUID,
    context: Annotated[RequestContext, Depends(require_authenticated_context)],
    persona: ReaderPersona = "EMPLOYEE",
) -> KnowledgeArticleDetailResponse:
    return await _service(request).article(context, persona=persona, document_id=document_id)
