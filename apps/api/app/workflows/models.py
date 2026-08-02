"""Transport-independent workflow execution records."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WorkflowTicket:
    ticket_id: UUID
    tenant_id: UUID
    ticket_key: str
    project_id: UUID
    work_type_code: str
    workflow_version_id: UUID
    workflow_version_status: str
    status_id: UUID
    status_code: str
    row_version: int
    summary: str
    description: str | None
    resolution_code: str | None
    resolution_summary: str | None
    assignment_group_id: UUID | None
    assignee_user_id: UUID | None
    first_response_at: Any
    resolved_at: Any
    closed_at: Any


@dataclass(frozen=True, slots=True)
class WorkflowTransition:
    transition_id: UUID
    workflow_version_id: UUID
    transition_code: str
    transition_name: str
    from_status_id: UUID
    from_status_code: str
    to_status_id: UUID
    to_status_code: str
    to_status_name: str
    condition: Any
    validators: Any
    actions: Any
