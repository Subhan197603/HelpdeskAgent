"""Stable API contracts for draft and confirmed ticket submission."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CustomFieldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_code: str = Field(min_length=1, max_length=100)
    value: Any


class DraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_type_id: UUID
    service_node_id: UUID | None = None
    application_environment_id: UUID | None = None
    requested_for_user_id: UUID | None = None
    summary: str = Field(max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    impact: str = Field(min_length=1, max_length=20)
    urgency: str = Field(min_length=1, max_length=20)
    custom_fields: list[CustomFieldInput] = Field(default_factory=list, max_length=200)


class DraftPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_for_user_id: UUID | None = None
    service_node_id: UUID | None = None
    application_environment_id: UUID | None = None
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=20_000)
    impact: str | None = Field(default=None, min_length=1, max_length=20)
    urgency: str | None = Field(default=None, min_length=1, max_length=20)
    custom_fields: list[CustomFieldInput] | None = Field(default=None, max_length=200)
    row_version: int = Field(ge=1)


class DraftVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_version: int = Field(ge=1)


class NormalizedField(BaseModel):
    field_code: str
    data_type: str
    value: str | Decimal | date | datetime | bool | UUID | list[str] | dict[str, Any] | None


class DraftResponse(BaseModel):
    id: UUID
    request_type_id: UUID
    request_type_version_id: UUID
    project_id: UUID
    service_node_id: UUID | None
    application_environment_id: UUID | None
    owner_user_id: UUID
    requested_for_user_id: UUID | None
    summary: str
    description: str | None
    impact: str | None
    urgency: str | None
    priority: str | None
    status: Literal["DRAFT", "READY_FOR_REVIEW", "SUBMITTED", "EXPIRED", "CANCELLED"]
    custom_fields: list[NormalizedField]
    row_version: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    submitted_ticket_key: str | None = None


class DraftValidationResponse(BaseModel):
    valid: Literal[True] = True
    draft: DraftResponse


class TicketResponse(BaseModel):
    id: UUID
    key: str
    summary: str
    description: str | None
    project_code: str
    project_name: str
    request_type_code: str
    request_type_name: str
    service_name: str | None
    environment_name: str | None
    work_type: str
    status: str
    status_name: str
    priority: str
    reporter_user_id: UUID
    reporter_name: str
    requested_for_user_id: UUID | None
    requested_for_name: str | None
    created_at: datetime
    updated_at: datetime
    creation_event_at: datetime | None
    row_version: int
    public_comments: list["PublicCommentResponse"] = Field(default_factory=list)


class PublicCommentResponse(BaseModel):
    id: UUID
    author_user_id: UUID
    author_name: str
    body: str
    created_at: datetime


class PublicCommentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=10_000)


class TicketPage(BaseModel):
    items: list[TicketResponse]
    limit: int
    next_cursor: Annotated[str | None, Field(description="Opaque keyset cursor")] = None
