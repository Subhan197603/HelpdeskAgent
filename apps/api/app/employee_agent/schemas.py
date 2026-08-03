"""Public employee-assistant conversation and cancellation contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

MessageText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]


class ConversationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationResponse(BaseModel):
    id: UUID
    state: str
    stream_endpoint: str


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: MessageText


class CancellationResponse(BaseModel):
    conversation_id: UUID
    turn_id: UUID
    status: Literal["CANCELLED"] = "CANCELLED"
    cancelled_at: datetime
