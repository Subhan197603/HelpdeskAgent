"""Authenticated ticket draft, confirmation, and customer ticket endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.tickets.schemas import (
    DraftCreateRequest,
    DraftPatchRequest,
    DraftResponse,
    DraftValidationResponse,
    DraftVersionRequest,
    TicketPage,
    TicketResponse,
)
from apps.api.app.tickets.service import TicketService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Resource not found"},
    409: {
        "model": ProblemResponse,
        "description": "Concurrency, configuration, or idempotency conflict",
    },
    422: {"model": ProblemResponse, "description": "Structured validation failure"},
}
SUBMIT_RESPONSES = {
    **ERRORS,
    200: {"model": TicketResponse, "description": "Identical idempotent replay"},
}
router = APIRouter(tags=["tickets"])


def _service(request: Request) -> TicketService:
    return cast("TicketService", request.app.state.ticket_service)


@router.post(
    "/api/v1/ticket-drafts",
    response_model=DraftResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def create_draft(
    request: Request,
    command: DraftCreateRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_DRAFT_CREATE))],
) -> DraftResponse:
    return await _service(request).create_draft(context, command)


@router.get("/api/v1/ticket-drafts/{draft_id}", response_model=DraftResponse, responses=ERRORS)
async def get_draft(
    request: Request,
    draft_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.TICKET_DRAFT_READ_OWN))
    ],
) -> DraftResponse:
    return await _service(request).get_draft(context, draft_id)


@router.patch("/api/v1/ticket-drafts/{draft_id}", response_model=DraftResponse, responses=ERRORS)
async def update_draft(
    request: Request,
    draft_id: UUID,
    command: DraftPatchRequest,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.TICKET_DRAFT_UPDATE_OWN))
    ],
    if_match: Annotated[
        str | None,
        Header(alias="If-Match", description='Optional quoted row version, for example "3"'),
    ] = None,
) -> DraftResponse:
    _match_version(if_match, command.row_version)
    return await _service(request).update_draft(context, draft_id, command)


@router.post(
    "/api/v1/ticket-drafts/{draft_id}/validate",
    response_model=DraftValidationResponse,
    responses=ERRORS,
)
async def validate_draft(
    request: Request,
    draft_id: UUID,
    command: DraftVersionRequest,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.TICKET_DRAFT_UPDATE_OWN))
    ],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> DraftValidationResponse:
    _match_version(if_match, command.row_version)
    draft = await _service(request).validate_draft(context, draft_id, command.row_version)
    return DraftValidationResponse(draft=draft)


@router.post(
    "/api/v1/ticket-drafts/{draft_id}/submit",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    responses=SUBMIT_RESPONSES,
)
async def submit_draft(
    response: Response,
    request: Request,
    draft_id: UUID,
    command: DraftVersionRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_SUBMIT))],
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
) -> TicketResponse:
    _match_version(if_match, command.row_version)
    ticket, replay = await _service(request).submit(
        context, draft_id, command.row_version, idempotency_key
    )
    if replay:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return ticket


@router.delete(
    "/api/v1/ticket-drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT, responses=ERRORS
)
async def cancel_draft(
    request: Request,
    draft_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.TICKET_DRAFT_UPDATE_OWN))
    ],
    if_match: Annotated[
        str, Header(alias="If-Match", description='Required quoted row version, for example "3"')
    ],
) -> Response:
    await _service(request).cancel_draft(context, draft_id, _required_version(if_match))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/v1/tickets/{ticket_key}", response_model=TicketResponse, responses=ERRORS)
async def get_ticket(
    request: Request,
    ticket_key: str,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_READ_OWN))],
) -> TicketResponse:
    return await _service(request).get_ticket(context, ticket_key)


@router.get("/api/v1/my/tickets", response_model=TicketPage, responses=ERRORS)
async def my_tickets(
    request: Request,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_READ_OWN))],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> TicketPage:
    items, next_cursor = await _service(request).my_tickets(context, limit, cursor)
    return TicketPage(items=items, limit=limit, next_cursor=next_cursor)


def _match_version(if_match: str | None, row_version: int) -> None:
    if if_match is not None and _required_version(if_match) != row_version:
        raise ValidationError(
            "If-Match and body row version must agree.",
            field_errors={"header.If-Match": ["Version mismatch."]},
        )


def _required_version(value: str) -> int:
    stripped = value.strip().strip('"')
    try:
        version = int(stripped)
    except ValueError:
        raise ValidationError("If-Match must contain a row version.") from None
    if version < 1:
        raise ValidationError("If-Match must contain a positive row version.")
    return version
