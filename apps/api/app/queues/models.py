"""Transport-independent analyst queue and activity records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class QueueDefinition:
    queue_id: UUID
    queue_version_id: UUID
    tenant_id: UUID
    project_id: UUID
    project_code: str
    name: str
    description: str | None
    filter_json: Any
    sort_json: Any
    columns_json: Any
    visibility_type: str
    owner_group_id: UUID | None
    display_order: int


@dataclass(frozen=True, slots=True)
class QueueTicket:
    ticket_id: UUID
    ticket_key: str
    summary: str
    project_code: str
    priority_code: str
    status_code: str
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


@dataclass(frozen=True, slots=True)
class SavedFilter:
    saved_filter_id: UUID
    tenant_id: UUID
    owner_user_id: UUID
    name: str
    queue_id: UUID
    status_code: str | None
    priority_code: str | None
    search_text: str | None
    assignment_group_id: UUID | None
    assignee_scope: str | None
    display_order: int
    row_version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ActivityItem:
    item_id: str
    item_type: str
    classification: str
    actor_user_id: UUID | None
    actor_name: str | None
    body: str | None
    details: dict[str, Any]
    created_at: datetime
