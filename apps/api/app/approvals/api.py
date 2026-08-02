"""Assigned approval and immutable decision endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response

from apps.api.app.approvals.schemas import (
    ApprovalDecisionCommand,
    ApprovalDecisionResponse,
    ApprovalList,
)
from apps.api.app.approvals.service import ApprovalService
from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Approval not found"},
    409: {"model": ProblemResponse, "description": "Approval conflict"},
    422: {"model": ProblemResponse, "description": "Decision validation failed"},
}
router = APIRouter(tags=["approvals"])


def _service(request: Request) -> ApprovalService:
    return cast("ApprovalService", request.app.state.approval_service)


@router.get("/api/v1/my/approvals", response_model=ApprovalList, responses=ERRORS)
async def my_approvals(
    request: Request,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.APPROVAL_READ_ASSIGNED))
    ],
) -> ApprovalList:
    return await _service(request).mine(context)


@router.post(
    "/api/v1/approvals/{approval_id}/decisions",
    response_model=ApprovalDecisionResponse,
    responses=ERRORS,
)
async def decide_approval(
    response: Response,
    request: Request,
    approval_id: UUID,
    command: ApprovalDecisionCommand,
    context: Annotated[RequestContext, Depends(require_permission(Permission.APPROVAL_DECIDE))],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> ApprovalDecisionResponse:
    if if_match is not None and _version(if_match) != command.expected_version:
        raise ValidationError(
            "If-Match and body row version must agree.",
            field_errors={"header.If-Match": ["Version mismatch."]},
        )
    result = await _service(request).decide(context, approval_id, command, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


def _version(value: str) -> int:
    try:
        version = int(value.strip().strip('"'))
    except ValueError:
        raise ValidationError("If-Match must contain a row version.") from None
    if version < 1:
        raise ValidationError("If-Match must contain a positive row version.")
    return version
