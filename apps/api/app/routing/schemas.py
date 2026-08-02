"""API contracts for deterministic routing and manual assignment."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.tickets.schemas import TicketResponse


class RouteCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_version: int = Field(ge=1)


class ManualAssignmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignment_group_id: UUID
    assignee_user_id: UUID | None = None
    reason: str = Field(min_length=3, max_length=64)
    row_version: int = Field(ge=1)


class AssignmentResponse(BaseModel):
    ticket: TicketResponse
    assignment_group_code: str
    assignee_user_id: str | None
    routing_rule_version_id: str | None = None
    fallback: bool = False
    replayed: bool = False
