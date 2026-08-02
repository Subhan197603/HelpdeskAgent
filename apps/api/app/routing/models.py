"""Transport-independent routing and assignment records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RoutingTicket:
    ticket_id: UUID
    tenant_id: UUID
    ticket_key: str
    project_id: UUID
    project_code: str
    service_node_id: UUID | None
    service_node_code: str | None
    service_code: str | None
    module_code: str | None
    environment_code: str | None
    work_type_code: str
    priority_code: str
    status_code: str
    summary: str
    description: str | None
    assignment_group_id: UUID | None
    assignee_user_id: UUID | None
    row_version: int
    custom_fields: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RoutingRuleVersion:
    routing_rule_id: UUID
    routing_rule_version_id: UUID
    version_number: int
    rule_priority: int
    condition: Any
    assignment_group_id: UUID
    assignment_method: str
    assignee_user_id: UUID | None
    effective_from: datetime | None
    group_code: str


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    assignment_group_id: UUID
    assignment_group_code: str
    assignee_user_id: UUID | None
    new_row_version: int
