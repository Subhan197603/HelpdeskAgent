"""Human-controlled knowledge document publication endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.document_schemas import (
    DocumentAdminResponse,
    DocumentApprovalCommand,
    PublishDocumentCommand,
    RetireDocumentCommand,
)
from apps.api.app.knowledge.document_service import KnowledgeDocumentService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Publication permission denied"},
    404: {"model": ProblemResponse, "description": "Knowledge document not found"},
    409: {"model": ProblemResponse, "description": "Publication lifecycle conflict"},
    422: {"model": ProblemResponse, "description": "Publication validation failed"},
}
router = APIRouter(prefix="/api/v1/admin/knowledge/documents", tags=["knowledge-publication"])
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=255,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def _service(request: Request) -> KnowledgeDocumentService:
    return cast("KnowledgeDocumentService", request.app.state.knowledge_document_service)


@router.get("/{document_id}", response_model=DocumentAdminResponse, responses=ERRORS)
async def get_document(
    request: Request,
    document_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN))
    ],
) -> DocumentAdminResponse:
    return await _service(request).get(context, document_id)


@router.post(
    "/{document_id}/approval-decisions",
    response_model=DocumentAdminResponse,
    responses=ERRORS,
)
async def approve_document(
    response: Response,
    request: Request,
    document_id: UUID,
    command: DocumentApprovalCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_APPROVE))
    ],
) -> DocumentAdminResponse:
    result = await _service(request).approve(context, document_id, command, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post(
    "/{document_id}/publication",
    response_model=DocumentAdminResponse,
    responses=ERRORS,
)
async def publish_document(
    response: Response,
    request: Request,
    document_id: UUID,
    command: PublishDocumentCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_PUBLISH))
    ],
) -> DocumentAdminResponse:
    result = await _service(request).publish(context, document_id, command, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post(
    "/{document_id}/retirement",
    response_model=DocumentAdminResponse,
    responses=ERRORS,
)
async def retire_document(
    response: Response,
    request: Request,
    document_id: UUID,
    command: RetireDocumentCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_RETIRE))
    ],
) -> DocumentAdminResponse:
    result = await _service(request).retire(context, document_id, command, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result
