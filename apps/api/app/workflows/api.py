"""Analyst workflow transition endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.workflows.schemas import (
    AvailableTransitionList,
    TransitionCommand,
    TransitionResponse,
)
from apps.api.app.workflows.service import WorkflowService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Ticket not found"},
    409: {"model": ProblemResponse, "description": "Invalid or concurrent transition"},
    422: {"model": ProblemResponse, "description": "Transition validation failed"},
}
router = APIRouter(prefix="/api/v1/agent/tickets", tags=["workflows"])


def _service(request: Request) -> WorkflowService:
    return cast("WorkflowService", request.app.state.workflow_service)


@router.get("/{ticket_key}/transitions", response_model=AvailableTransitionList, responses=ERRORS)
async def available_transitions(
    request: Request,
    ticket_key: str,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_TRANSITION))],
) -> AvailableTransitionList:
    return await _service(request).available(context, ticket_key)


@router.post("/{ticket_key}/transitions", response_model=TransitionResponse, responses=ERRORS)
async def execute_transition(
    response: Response,
    request: Request,
    ticket_key: str,
    command: TransitionCommand,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_TRANSITION))],
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
) -> TransitionResponse:
    if if_match is not None and _version(if_match) != command.row_version:
        raise ValidationError(
            "If-Match and body row version must agree.",
            field_errors={"header.If-Match": ["Version mismatch."]},
        )
    result = await _service(request).execute(context, ticket_key, command, idempotency_key)
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
