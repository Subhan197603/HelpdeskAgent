"""Analyst queue and ticket activity endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ValidationError
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission
from apps.api.app.queues.schemas import (
    ActivityItemResponse,
    AnalystCommentCreateRequest,
    CannedResponseCreateRequest,
    CannedResponseDeleteRequest,
    CannedResponseListResponse,
    CannedResponseOrderRequest,
    CannedResponseResponse,
    CannedResponseUpdateRequest,
    QueueListResponse,
    QueueTicketPage,
    SavedFilterCreateRequest,
    SavedFilterDeleteRequest,
    SavedFilterListResponse,
    SavedFilterOrderRequest,
    SavedFilterResponse,
    SavedFilterUpdateRequest,
    TimelineResponse,
)
from apps.api.app.queues.service import QueueService

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Queue or ticket not found"},
    409: {"model": ProblemResponse, "description": "Queue configuration conflict"},
    422: {"model": ProblemResponse, "description": "Query validation failed"},
}
router = APIRouter(tags=["queues"])


def _service(request: Request) -> QueueService:
    return cast("QueueService", request.app.state.queue_service)


@router.get(
    "/api/v1/agent/canned-responses",
    response_model=CannedResponseListResponse,
    responses=ERRORS,
)
async def canned_responses(
    request: Request,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> CannedResponseListResponse:
    return CannedResponseListResponse(items=await _service(request).canned_responses(context))


@router.post(
    "/api/v1/agent/canned-responses",
    response_model=CannedResponseResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def create_canned_response(
    response: Response,
    request: Request,
    command: CannedResponseCreateRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
) -> CannedResponseResponse:
    item, replayed = await _service(request).create_canned_response(
        context, command, idempotency_key
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return item


@router.put(
    "/api/v1/agent/canned-responses/order",
    response_model=CannedResponseListResponse,
    responses=ERRORS,
)
async def reorder_canned_responses(
    request: Request,
    command: CannedResponseOrderRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> CannedResponseListResponse:
    return CannedResponseListResponse(
        items=await _service(request).reorder_canned_responses(context, command)
    )


@router.get(
    "/api/v1/agent/canned-responses/{canned_response_id}",
    response_model=CannedResponseResponse,
    responses=ERRORS,
)
async def canned_response(
    request: Request,
    canned_response_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> CannedResponseResponse:
    return await _service(request).canned_response(context, canned_response_id)


@router.patch(
    "/api/v1/agent/canned-responses/{canned_response_id}",
    response_model=CannedResponseResponse,
    responses=ERRORS,
)
async def update_canned_response(
    request: Request,
    canned_response_id: UUID,
    command: CannedResponseUpdateRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> CannedResponseResponse:
    if if_match is not None and _version(if_match) != command.row_version:
        raise ValidationError(
            "If-Match and body row version must agree.",
            field_errors={"header.If-Match": ["Version mismatch."]},
        )
    return await _service(request).update_canned_response(context, canned_response_id, command)


@router.delete(
    "/api/v1/agent/canned-responses/{canned_response_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERRORS,
)
async def delete_canned_response(
    request: Request,
    canned_response_id: UUID,
    command: CannedResponseDeleteRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Response:
    if if_match is not None and _version(if_match) != command.row_version:
        raise ValidationError(
            "If-Match and body row version must agree.",
            field_errors={"header.If-Match": ["Version mismatch."]},
        )
    await _service(request).delete_canned_response(context, canned_response_id, command.row_version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/v1/agent/queues", response_model=QueueListResponse, responses=ERRORS)
async def queues(
    request: Request,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> QueueListResponse:
    return QueueListResponse(items=await _service(request).queues(context))


@router.get(
    "/api/v1/agent/saved-filters",
    response_model=SavedFilterListResponse,
    responses=ERRORS,
)
async def saved_filters(
    request: Request,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> SavedFilterListResponse:
    return SavedFilterListResponse(items=await _service(request).saved_filters(context))


@router.post(
    "/api/v1/agent/saved-filters",
    response_model=SavedFilterResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def create_saved_filter(
    response: Response,
    request: Request,
    command: SavedFilterCreateRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
) -> SavedFilterResponse:
    item, replayed = await _service(request).create_saved_filter(context, command, idempotency_key)
    if replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return item


@router.put(
    "/api/v1/agent/saved-filters/order",
    response_model=SavedFilterListResponse,
    responses=ERRORS,
)
async def reorder_saved_filters(
    request: Request,
    command: SavedFilterOrderRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> SavedFilterListResponse:
    return SavedFilterListResponse(
        items=await _service(request).reorder_saved_filters(context, command)
    )


@router.get(
    "/api/v1/agent/saved-filters/{saved_filter_id}",
    response_model=SavedFilterResponse,
    responses=ERRORS,
)
async def saved_filter(
    request: Request,
    saved_filter_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> SavedFilterResponse:
    return await _service(request).saved_filter(context, saved_filter_id)


@router.patch(
    "/api/v1/agent/saved-filters/{saved_filter_id}",
    response_model=SavedFilterResponse,
    responses=ERRORS,
)
async def update_saved_filter(
    request: Request,
    saved_filter_id: UUID,
    command: SavedFilterUpdateRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> SavedFilterResponse:
    if if_match is not None and _version(if_match) != command.row_version:
        raise ValidationError(
            "If-Match and body row version must agree.",
            field_errors={"header.If-Match": ["Version mismatch."]},
        )
    return await _service(request).update_saved_filter(context, saved_filter_id, command)


@router.delete(
    "/api/v1/agent/saved-filters/{saved_filter_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=ERRORS,
)
async def delete_saved_filter(
    request: Request,
    saved_filter_id: UUID,
    command: SavedFilterDeleteRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> Response:
    if if_match is not None and _version(if_match) != command.row_version:
        raise ValidationError(
            "If-Match and body row version must agree.",
            field_errors={"header.If-Match": ["Version mismatch."]},
        )
    await _service(request).delete_saved_filter(context, saved_filter_id, command.row_version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/v1/agent/saved-filters/{saved_filter_id}/tickets",
    response_model=QueueTicketPage,
    responses=ERRORS,
)
async def saved_filter_tickets(
    request: Request,
    saved_filter_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> QueueTicketPage:
    items, next_cursor = await _service(request).saved_filter_tickets(
        context, saved_filter_id, limit, cursor
    )
    return QueueTicketPage(items=items, limit=limit, next_cursor=next_cursor)


@router.get(
    "/api/v1/agent/queues/{queue_id}/tickets",
    response_model=QueueTicketPage,
    responses=ERRORS,
)
async def queue_tickets(
    request: Request,
    queue_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
    status_code: Annotated[str | None, Query(pattern=r"^[A-Z][A-Z0-9_]{0,49}$")] = None,
    priority_code: Annotated[str | None, Query(pattern=r"^[A-Z][A-Z0-9_]{0,19}$")] = None,
    search: Annotated[str | None, Query(max_length=100)] = None,
    assignment_group_id: UUID | None = None,
    assignee: Annotated[str | None, Query(pattern=r"^(me|unassigned)$")] = None,
) -> QueueTicketPage:
    items, next_cursor = await _service(request).tickets(
        context,
        queue_id,
        limit,
        cursor,
        status=status_code,
        priority=priority_code,
        search=search,
        assignment_group_id=assignment_group_id,
        assignee=assignee,
    )
    return QueueTicketPage(items=items, limit=limit, next_cursor=next_cursor)


@router.get(
    "/api/v1/tickets/{ticket_key}/timeline",
    response_model=TimelineResponse,
    responses=ERRORS,
)
async def customer_timeline(
    request: Request,
    ticket_key: str,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_READ_OWN))],
) -> TimelineResponse:
    return await _service(request).customer_timeline(context, ticket_key)


@router.get(
    "/api/v1/agent/tickets/{ticket_key}/timeline",
    response_model=TimelineResponse,
    responses=ERRORS,
)
async def analyst_timeline(
    request: Request,
    ticket_key: str,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
) -> TimelineResponse:
    return await _service(request).analyst_timeline(context, ticket_key)


@router.post(
    "/api/v1/agent/tickets/{ticket_key}/comments",
    response_model=ActivityItemResponse,
    status_code=status.HTTP_201_CREATED,
    responses=ERRORS,
)
async def add_analyst_comment(
    response: Response,
    request: Request,
    ticket_key: str,
    command: AnalystCommentCreateRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.TICKET_ANALYST_READ))],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
) -> ActivityItemResponse:
    item, replayed = await _service(request).add_comment(
        context, ticket_key, command, idempotency_key
    )
    if replayed:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return item


def _version(value: str) -> int:
    try:
        version = int(value.strip().strip('"'))
    except ValueError:
        raise ValidationError("If-Match must contain a row version.") from None
    if version < 1:
        raise ValidationError("If-Match must contain a positive row version.")
    return version
