"""Stable contracts for analyst queues and ticket activity."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QueueResponse(BaseModel):
    id: UUID
    version_id: UUID
    name: str
    description: str | None
    project_id: UUID
    project_code: str
    visibility: Literal["GROUP", "PROJECT_AGENTS", "ALL_AGENTS"]
    display_order: int
    columns: list[str]
    sort: list[dict[str, str]]


class QueueListResponse(BaseModel):
    items: list[QueueResponse]


class QueueTicketResponse(BaseModel):
    id: UUID
    key: str
    summary: str
    project_code: str
    priority: str
    status: str
    status_name: str
    reporter_name: str
    assignment_group_id: UUID | None
    assignment_group_name: str | None
    assignee_user_id: UUID | None
    assignee_name: str | None
    created_at: datetime
    updated_at: datetime
    first_response_sla_target: datetime | None
    resolution_sla_target: datetime | None


class QueueTicketPage(BaseModel):
    items: list[QueueTicketResponse]
    limit: int
    next_cursor: Annotated[str | None, Field(description="Opaque scoped keyset cursor")] = None


class SavedFilterFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    queue_id: UUID
    status_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,49}$")
    priority_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,19}$")
    search: str | None = Field(default=None, min_length=2, max_length=100)
    assignment_group_id: UUID | None = None
    assignee: Literal["me", "unassigned"] | None = None


class SavedFilterCreateRequest(SavedFilterFields):
    pass


class SavedFilterUpdateRequest(SavedFilterFields):
    row_version: int = Field(ge=1)


class SavedFilterOrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    row_version: int = Field(ge=1)


class SavedFilterOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[SavedFilterOrderItem] = Field(min_length=1, max_length=100)


class SavedFilterDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_version: int = Field(ge=1)


class SavedFilterResponse(BaseModel):
    id: UUID
    name: str
    queue_id: UUID
    status_code: str | None
    priority_code: str | None
    search: str | None
    assignment_group_id: UUID | None
    assignee: Literal["me", "unassigned"] | None
    display_order: int
    row_version: int
    created_at: datetime
    updated_at: datetime


class SavedFilterListResponse(BaseModel):
    items: list[SavedFilterResponse]


class CannedResponseFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=10_000)


class CannedResponseCreateRequest(CannedResponseFields):
    pass


class CannedResponseUpdateRequest(CannedResponseFields):
    row_version: int = Field(ge=1)


class CannedResponseOrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    row_version: int = Field(ge=1)


class CannedResponseOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[CannedResponseOrderItem] = Field(min_length=1, max_length=100)


class CannedResponseDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_version: int = Field(ge=1)


class CannedResponseResponse(BaseModel):
    id: UUID
    name: str
    body: str
    display_order: int
    row_version: int
    created_at: datetime
    updated_at: datetime


class CannedResponseListResponse(BaseModel):
    items: list[CannedResponseResponse]


class ActivityItemResponse(BaseModel):
    id: str
    type: str
    classification: Literal["PUBLIC", "INTERNAL", "SYSTEM"]
    actor_user_id: UUID | None
    actor_name: str | None
    body: str | None
    details: dict[str, Any]
    created_at: datetime


class TimelineResponse(BaseModel):
    ticket_key: str
    items: list[ActivityItemResponse]


class AnalystCommentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    visibility: Literal["PUBLIC", "INTERNAL"]
    body: str = Field(min_length=1, max_length=10_000)
