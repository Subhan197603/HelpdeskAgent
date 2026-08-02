"""Role-separated knowledge-source administration endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.knowledge.schemas import (
    AcquisitionAuthorizationCommand,
    AcquisitionAuthorizationResponse,
    AcquisitionPermissionResponse,
    ApprovalStatus,
    AudienceScope,
    SourceApprovalCommand,
    SourceCreate,
    SourceList,
    SourceResponse,
    SourceStatus,
    SourceType,
    SourceUpdate,
)
from apps.api.app.knowledge.service import KnowledgeSourceService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Knowledge source not found"},
    409: {"model": ProblemResponse, "description": "Knowledge source conflict"},
    422: {"model": ProblemResponse, "description": "Knowledge source validation failed"},
}
router = APIRouter(prefix="/api/v1/admin/knowledge/sources", tags=["knowledge-admin"])
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=255,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def _service(request: Request) -> KnowledgeSourceService:
    return cast("KnowledgeSourceService", request.app.state.knowledge_source_service)


@router.get("", response_model=SourceList, responses=ERRORS)
async def list_sources(
    request: Request,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_SOURCE_READ_ADMIN))
    ],
    source_type: SourceType | None = None,
    audience: AudienceScope | None = None,
    status: SourceStatus | None = None,
    approval_status: ApprovalStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> SourceList:
    return await _service(request).list(
        context,
        source_type=source_type,
        audience=audience,
        status=status,
        approval_status=approval_status,
        limit=limit,
    )


@router.get("/{source_id}", response_model=SourceResponse, responses=ERRORS)
async def get_source(
    request: Request,
    source_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_SOURCE_READ_ADMIN))
    ],
) -> SourceResponse:
    return await _service(request).get(context, source_id)


@router.post("", response_model=SourceResponse, status_code=201, responses=ERRORS)
async def create_source(
    response: Response,
    request: Request,
    command: SourceCreate,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_SOURCE_CREATE))
    ],
) -> SourceResponse:
    result, replayed = await _service(request).create(context, command, idempotency_key)
    if replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.put("/{source_id}", response_model=SourceResponse, responses=ERRORS)
async def update_source(
    response: Response,
    request: Request,
    source_id: UUID,
    command: SourceUpdate,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_SOURCE_UPDATE))
    ],
) -> SourceResponse:
    result, replayed = await _service(request).update(context, source_id, command, idempotency_key)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post("/{source_id}/approval-decisions", response_model=SourceResponse, responses=ERRORS)
async def decide_source_approval(
    response: Response,
    request: Request,
    source_id: UUID,
    command: SourceApprovalCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_SOURCE_APPROVE))
    ],
) -> SourceResponse:
    result, replayed = await _service(request).approve(context, source_id, command, idempotency_key)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post(
    "/{source_id}/acquisition-authorizations",
    response_model=AcquisitionAuthorizationResponse,
    status_code=201,
    responses=ERRORS,
)
async def authorize_source_acquisition(
    response: Response,
    request: Request,
    source_id: UUID,
    command: AcquisitionAuthorizationCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_ACQUISITION_PERMISSION_MANAGE)),
    ],
) -> AcquisitionAuthorizationResponse:
    result = await _service(request).authorize_acquisition(
        context, source_id, command, idempotency_key
    )
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.get(
    "/{source_id}/acquisition-permission",
    response_model=AcquisitionPermissionResponse,
    responses=ERRORS,
)
async def acquisition_permission(
    request: Request,
    source_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_SOURCE_READ_ADMIN))
    ],
) -> AcquisitionPermissionResponse:
    return await _service(request).permission(context, source_id)
