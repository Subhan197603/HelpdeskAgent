"""Authorized employee conversation endpoints with server-sent event streaming."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from apps.api.app.catalog.schemas import ProblemResponse
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.employee_agent.models import StreamEvent
from apps.api.app.employee_agent.schemas import (
    CancellationResponse,
    ConversationCreateRequest,
    ConversationResponse,
    MessageRequest,
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
