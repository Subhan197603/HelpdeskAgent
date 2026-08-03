"""Public employee-assistant conversation and cancellation contracts."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from apps.api.app.tickets.schemas import DraftCreateRequest, DraftResponse, TicketResponse

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


class ResolutionFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    helpful: bool
    resolved: bool
    comment: str | None = Field(default=None, max_length=1000)
    draft: DraftCreateRequest | None = None

    @model_validator(mode="after")
    def validate_draft_intent(self) -> "ResolutionFeedbackRequest":
        if self.resolved and self.draft is not None:
            raise ValueError("Resolved feedback cannot include a ticket draft.")
        if not self.resolved and self.draft is None:
            raise ValueError("Unresolved feedback requires ticket draft details.")
        return self


class ResolutionFeedbackResponse(BaseModel):
    conversation_id: UUID
    state: str
    helpful: bool
    resolved: bool
    draft: DraftResponse | None = None


class ConfirmTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_version: int = Field(ge=1)


class ConfirmTicketResponse(BaseModel):
    conversation_id: UUID
    state: str
    ticket: TicketResponse
    idempotent_replay: bool
