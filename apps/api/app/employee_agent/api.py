"""Authorized employee conversation endpoints with server-sent event streaming."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from starlette.responses import StreamingResponse

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.employee_agent.models import StreamEvent
from apps.api.app.employee_agent.schemas import (
    CancellationResponse,
    ConfirmTicketRequest,
    ConfirmTicketResponse,
    ConversationCreateRequest,
    ConversationResponse,
    MessageRequest,
    ResolutionFeedbackRequest,
    ResolutionFeedbackResponse,
)
from apps.api.app.employee_agent.service import EmployeeAgentService
from apps.api.app.identity.authorization import Permission

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Assistant access denied"},
    404: {"model": ProblemResponse, "description": "Conversation not found"},
    409: {"model": ProblemResponse, "description": "Conversation conflict"},
    422: {"model": ProblemResponse, "description": "Message validation failed"},
    503: {"model": ProblemResponse, "description": "Assistant unavailable"},
}
router = APIRouter(prefix="/api/v1/assistant/conversations", tags=["employee-assistant"])


def _service(request: Request) -> EmployeeAgentService:
    return cast("EmployeeAgentService", request.app.state.employee_agent_service)


@router.post("", response_model=ConversationResponse, status_code=201, responses=ERRORS)
async def create_conversation(
    request: Request,
    _: ConversationCreateRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.AI_EMPLOYEE_USE))],
) -> ConversationResponse:
    conversation = await _service(request).create_conversation(context)
    return _conversation_response(conversation.conversation_id, conversation.state.value)


@router.get("/{conversation_id}", response_model=ConversationResponse, responses=ERRORS)
async def get_conversation(
    request: Request,
    conversation_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.AI_EMPLOYEE_USE))],
) -> ConversationResponse:
    conversation = await _service(request).conversation(context, conversation_id)
    return _conversation_response(conversation.conversation_id, conversation.state.value)


@router.post(
    "/{conversation_id}/messages",
    response_class=StreamingResponse,
    responses=ERRORS,
)
async def stream_message(
    request: Request,
    conversation_id: UUID,
    command: MessageRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.AI_EMPLOYEE_USE))],
) -> StreamingResponse:
    events = _service(request).stream_message(context, conversation_id, command.content)
    first = await anext(events)
    return StreamingResponse(
        _sse(first, events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/{conversation_id}/turns/{turn_id}/cancel",
    response_model=CancellationResponse,
    responses=ERRORS,
)
async def cancel_turn(
    request: Request,
    conversation_id: UUID,
    turn_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.AI_EMPLOYEE_USE))],
) -> CancellationResponse:
    await _service(request).cancel(context, conversation_id, turn_id)
    return CancellationResponse(
        conversation_id=conversation_id,
        turn_id=turn_id,
        cancelled_at=datetime.now(UTC),
    )


@router.post(
    "/{conversation_id}/resolution-feedback",
    response_model=ResolutionFeedbackResponse,
    responses=ERRORS,
)
async def resolution_feedback(
    request: Request,
    conversation_id: UUID,
    command: ResolutionFeedbackRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.AI_EMPLOYEE_USE))],
) -> ResolutionFeedbackResponse:
    state, draft = await _service(request).resolution_feedback(context, conversation_id, command)
    return ResolutionFeedbackResponse(
        conversation_id=conversation_id,
        state=state.value,
        helpful=command.helpful,
        resolved=command.resolved,
        draft=draft,
    )


@router.post(
    "/{conversation_id}/confirm-ticket",
    response_model=ConfirmTicketResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        **ERRORS,
        200: {"model": ConfirmTicketResponse, "description": "Idempotent confirmation replay"},
    },
)
async def confirm_ticket(
    response: Response,
    request: Request,
    conversation_id: UUID,
    command: ConfirmTicketRequest,
    context: Annotated[RequestContext, Depends(require_permission(Permission.AI_EMPLOYEE_USE))],
    idempotency_key: Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=255,
            pattern=r"^[A-Za-z0-9._:-]+$",
        ),
    ],
) -> ConfirmTicketResponse:
    ticket, replay = await _service(request).confirm_ticket(
        context, conversation_id, command.row_version, idempotency_key
    )
    if replay:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return ConfirmTicketResponse(
        conversation_id=conversation_id,
        state="TICKET_SUBMITTED",
        ticket=ticket,
        idempotent_replay=replay,
    )


async def _sse(first: StreamEvent, remaining: AsyncIterator[StreamEvent]) -> AsyncIterator[str]:
    yield _encode(first)
    async for event in remaining:
        yield _encode(event)


def _encode(event: StreamEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data, separators=(',', ':'))}\n\n"


def _conversation_response(conversation_id: UUID, state: str) -> ConversationResponse:
    return ConversationResponse(
        id=conversation_id,
        state=state,
        stream_endpoint=f"/api/v1/assistant/conversations/{conversation_id}/messages",
    )
