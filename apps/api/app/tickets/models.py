"""Transport-independent ticket draft and submitted-ticket records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TicketDraft:
    draft_id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    requested_for_user_id: UUID | None
    project_id: UUID
    service_node_id: UUID | None
    request_type_id: UUID
    request_type_version_id: UUID
    work_type_id: UUID
    application_environment_id: UUID | None
    summary: str
    description: str | None
    custom_values: dict[str, Any]
    impact_code: str | None
    urgency_code: str | None
    priority_code: str | None
    priority_matrix_id: UUID | None
    status: str
    submitted_ticket_id: UUID | None
    created_at: datetime
    updated_at: datetime
    row_version: int
    expires_at: datetime | None


@dataclass(frozen=True, slots=True)
class TicketView:
    ticket_id: UUID
    ticket_key: str
    summary: str
    description: str | None
    project_code: str
    project_name: str
    request_type_code: str
    request_type_name: str
    service_name: str | None
    environment_name: str | None
    work_type_code: str
    status_code: str
    status_name: str
    priority_code: str
    reporter_user_id: UUID
    reporter_name: str
    requested_for_user_id: UUID | None
    requested_for_name: str | None
    created_at: datetime
    updated_at: datetime
    created_event_at: datetime | None
