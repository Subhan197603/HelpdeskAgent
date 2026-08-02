"""Administrative manifest and acquisition-run endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.ingestion.schemas import (
    AcquisitionRunCommand,
    ManifestApprovalCommand,
    ManifestEntryResponse,
    ManifestImportCommand,
    ManifestImportResponse,
    ManualUploadCommand,
    ManualUploadResponse,
    RunResponse,
    UploadCompleteResponse,
)
from apps.api.app.ingestion.service import IngestionService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Acquisition permission denied"},
    404: {"model": ProblemResponse, "description": "Acquisition resource not found"},
    409: {"model": ProblemResponse, "description": "Lifecycle or idempotency conflict"},
    415: {"model": ProblemResponse, "description": "Unsupported document content"},
    422: {"model": ProblemResponse, "description": "Acquisition validation failed"},
    503: {"model": ProblemResponse, "description": "Object storage unavailable"},
}
router = APIRouter(tags=["knowledge-ingestion"])
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=8,
        max_length=255,
        pattern=r"^[A-Za-z0-9._:-]+$",
    ),
]


def _service(request: Request) -> IngestionService:
    return cast("IngestionService", request.app.state.ingestion_service)


@router.post(
    "/api/v1/admin/knowledge/manifest/import",
    response_model=ManifestImportResponse,
    responses=ERRORS,
)
async def import_manifest(
    request: Request,
    command: ManifestImportCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_MANIFEST_IMPORT))
    ],
) -> ManifestImportResponse:
    return await _service(request).import_manifest(context, command, idempotency_key)


@router.post(
    "/api/v1/admin/knowledge/manifest/{entry_id}/approval-decisions",
    response_model=ManifestEntryResponse,
    responses=ERRORS,
)
async def decide_manifest(
    response: Response,
    request: Request,
    entry_id: UUID,
    command: ManifestApprovalCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_MANIFEST_APPROVE))
    ],
) -> ManifestEntryResponse:
    result, replayed = await _service(request).decide_manifest(
        context, entry_id, command, idempotency_key
    )
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post(
    "/api/v1/admin/ingestion/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def create_run(
    response: Response,
    request: Request,
    command: AcquisitionRunCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext,
        Depends(require_permission(Permission.KNOWLEDGE_INGESTION_RUN_CREATE)),
    ],
) -> RunResponse:
    result = await _service(request).create_run(context, command, idempotency_key)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.get("/api/v1/admin/ingestion/runs/{run_id}", response_model=RunResponse, responses=ERRORS)
async def get_run(
    request: Request,
    run_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_SOURCE_READ_ADMIN))
    ],
) -> RunResponse:
    return await _service(request).get_run(context, run_id)


@router.post(
    "/api/v1/admin/knowledge/manual-uploads",
    response_model=ManualUploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def authorize_manual_upload(
    response: Response,
    request: Request,
    command: ManualUploadCommand,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_UPLOAD))
    ],
) -> ManualUploadResponse:
    result = await _service(request).authorize_manual_upload(context, command, idempotency_key)
    if result.replayed:
        response.status_code = 200
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post(
    "/api/v1/admin/knowledge/manual-uploads/{item_id}/complete",
    response_model=UploadCompleteResponse,
    responses=ERRORS,
)
async def complete_manual_upload(
    response: Response,
    request: Request,
    item_id: UUID,
    idempotency_key: IdempotencyKey,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.KNOWLEDGE_DOCUMENT_UPLOAD))
    ],
) -> UploadCompleteResponse:
    result = await _service(request).complete_manual_upload(context, item_id, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result
