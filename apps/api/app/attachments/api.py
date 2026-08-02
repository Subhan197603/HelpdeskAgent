"""Attachment quarantine and protected-delivery endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status

from apps.api.app.attachments.schemas import (
    DownloadResponse,
    FinalizeResponse,
    UploadAuthorizationResponse,
    UploadRequest,
)
from apps.api.app.attachments.service import AttachmentService
from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Resource not found"},
    409: {"model": ProblemResponse, "description": "Lifecycle or idempotency conflict"},
    415: {"model": ProblemResponse, "description": "Unsupported or mismatched file"},
    422: {"model": ProblemResponse, "description": "Malware detected"},
    503: {"model": ProblemResponse, "description": "Scanner or object storage unavailable"},
}
router = APIRouter(tags=["attachments"])


def _service(request: Request) -> AttachmentService:
    return cast("AttachmentService", request.app.state.attachment_service)


@router.post(
    "/api/v1/tickets/{ticket_key}/attachments/uploads",
    response_model=UploadAuthorizationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def authorize_upload(
    request: Request,
    ticket_key: str,
    command: UploadRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.ATTACHMENT_UPLOAD))],
) -> UploadAuthorizationResponse:
    return await _service(request).authorize_upload(context, ticket_key, command)


@router.post(
    "/api/v1/attachments/{attachment_id}/finalize",
    response_model=FinalizeResponse,
    responses=ERRORS,
)
async def finalize_upload(
    response: Response,
    request: Request,
    attachment_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.ATTACHMENT_UPLOAD))],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
) -> FinalizeResponse:
    result, replayed = await _service(request).finalize(context, attachment_id, idempotency_key)
    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    if result.scan_status == "ERROR":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        response.headers["Retry-After"] = str(_service(request).retry_after_seconds)
    return result


@router.post(
    "/api/v1/attachments/{attachment_id}/download",
    response_model=DownloadResponse,
    responses=ERRORS,
)
async def authorize_download(
    request: Request,
    attachment_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.ATTACHMENT_DOWNLOAD))],
) -> DownloadResponse:
    return await _service(request).download(context, attachment_id)
