"""Authorized deterministic routing and manual assignment endpoints."""

from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, Request, Response

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.routing.schemas import (
    AssignmentResponse,
    ManualAssignmentCommand,
    RouteCommand,
)
from apps.api.app.routing.service import RoutingService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Ticket not found"},
    409: {"model": ProblemResponse, "description": "Routing or concurrency conflict"},
    422: {"model": ProblemResponse, "description": "Assignment validation failed"},
}
router = APIRouter(prefix="/api/v1/agent/tickets", tags=["routing"])


def _service(request: Request) -> RoutingService:
    return cast("RoutingService", request.app.state.routing_service)


@router.post("/{ticket_key}/route", response_model=AssignmentResponse, responses=ERRORS)
async def route_ticket(
    response: Response,
    request: Request,
    ticket_key: str,
    command: RouteCommand,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ROUTE))],
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
) -> AssignmentResponse:
    _match_version(if_match, command.row_version)
    result = await _service(request).route(context, ticket_key, command, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


@router.post("/{ticket_key}/assignment", response_model=AssignmentResponse, responses=ERRORS)
async def assign_ticket(
    response: Response,
    request: Request,
    ticket_key: str,
    command: ManualAssignmentCommand,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.TICKET_ASSIGN_MANUAL))
    ],
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
) -> AssignmentResponse:
    _match_version(if_match, command.row_version)
    result = await _service(request).assign_manual(context, ticket_key, command, idempotency_key)
    if result.replayed:
        response.headers["Idempotent-Replayed"] = "true"
    return result


def _match_version(if_match: str | None, row_version: int) -> None:
    if if_match is None:
        return
    try:
        version = int(if_match.strip().strip('"'))
    except ValueError:
        raise ValidationError("If-Match must contain a row version.") from None
    if version != row_version:
        raise ValidationError(
            "If-Match and body row version must agree.",
            field_errors={"header.If-Match": ["Version mismatch."]},
        )
