"""Human-controlled knowledge document publication endpoints."""

from typing import Annotated, Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.document_schemas import (
    DocumentAdminListResponse,
    DocumentAdminResponse,
    DocumentApprovalCommand,
    DocumentPreviewResponse,
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
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]
Search = Annotated[str | None, Query(min_length=2, max_length=120)]
FilterCode = Annotated[str | None, Query(pattern=r"^[A-Z][A-Z0-9_]{0,59}$")]
ApprovalStatus = Literal["DRAFT", "UNDER_REVIEW", "APPROVED", "REJECTED", "RETIRED"]
PublicationState = Literal["UNPUBLISHED", "PUBLISHED", "RETIRED"]
AudienceCode = Literal["EMPLOYEE", "ANALYST", "TECHNICAL_SPECIALIST", "ADMIN", "ALL"]
SecurityClassification = Literal["PUBLIC", "INTERNAL", "CONFIDENTIAL", "RESTRICTED"]
_READ = Depends(
    require_permission(Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN, privileged_access=True)
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


def _service(request: Request) -> KnowledgeDocumentService:
    return cast("KnowledgeDocumentService", request.app.state.knowledge_document_service)


@router.get("", response_model=DocumentAdminListResponse, responses=ERRORS)
async def list_documents(
    request: Request,
    context: Annotated[RequestContext, _READ],
    search: Search = None,
    approval_status: ApprovalStatus | None = None,
    publication_state: PublicationState | None = None,
    audience_code: AudienceCode | None = None,
    security_classification: SecurityClassification | None = None,
    document_type: FilterCode = None,
    source_id: UUID | None = None,
    owner_group_id: UUID | None = None,
    limit: Limit = 25,
    offset: Offset = 0,
) -> DocumentAdminListResponse:
    return await _service(request).list(
        context,
        search=search,
        approval_status=approval_status,
        publication_state=publication_state,
        audience_code=audience_code,
        security_classification=security_classification,
        document_type=document_type,
        source_id=source_id,
        owner_group_id=owner_group_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentAdminResponse, responses=ERRORS)
async def get_document(
    request: Request,
    document_id: UUID,
    context: Annotated[RequestContext, _READ],
) -> DocumentAdminResponse:
    return await _service(request).get(context, document_id)


@router.get(
    "/{document_id}/versions/{version_id}/preview",
    response_model=DocumentPreviewResponse,
    responses=ERRORS,
)
async def preview_document_version(
    request: Request,
    document_id: UUID,
    version_id: UUID,
    processing_version_id: UUID,
    context: Annotated[RequestContext, _READ],
    limit: Limit = 100,
    offset: Offset = 0,
) -> DocumentPreviewResponse:
    return await _service(request).preview(
        context,
        document_id,
        version_id,
        processing_version_id,
        limit=limit,
        offset=offset,
    )


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
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_APPROVE, privileged_access=True)),
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
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_PUBLISH, privileged_access=True)),
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
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_RETIRE, privileged_access=True)),
    ],
) -> DocumentAdminResponse:
    result = await _service(request).retire(context, document_id, command, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result
