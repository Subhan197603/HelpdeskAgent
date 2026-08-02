"""API contracts for deterministic workflow transitions."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.tickets.schemas import TicketResponse


class TransitionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transition_code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Z0-9_]+$")
    row_version: int = Field(ge=1)
    field_updates: dict[str, Any] = Field(default_factory=dict, max_length=20)
    comment: str | None = Field(default=None, max_length=10_000)


class AvailableTransition(BaseModel):
    code: str
    name: str
    to_status: str
    to_status_name: str


class AvailableTransitionList(BaseModel):
    ticket_key: str
    row_version: int
    current_status: str
    transitions: list[AvailableTransition]


class TransitionResponse(BaseModel):
    ticket: TicketResponse
    transition_code: str
    replayed: bool = False
