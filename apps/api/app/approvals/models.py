"""Transport-independent approval records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ApprovalDefinition:
    definition_id: UUID
    version_id: UUID
    tenant_id: UUID
    project_id: UUID
    code: str
    name: str
    mode: str
    approver_rule: Any
    approved_transition_id: UUID | None
    rejected_transition_id: UUID | None
    allow_requester_self_approval: bool
    expires_after_minutes: int | None


@dataclass(frozen=True, slots=True)
class ApprovalTicket:
    ticket_id: UUID
    tenant_id: UUID
    ticket_key: str
    project_id: UUID
    reporter_user_id: UUID
    requested_for_user_id: UUID | None


@dataclass(frozen=True, slots=True)
class ApprovalView:
    approval_id: UUID
    ticket_id: UUID
    ticket_key: str
    ticket_summary: str
    definition_version_id: UUID
    approval_code: str
    approval_name: str
    approval_mode: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
    row_version: int
    approver_user_id: UUID
    sequence_number: int
    decision: str | None
    decision_comment: str | None
    decided_at: datetime | None


@dataclass(frozen=True, slots=True)
class LockedApproval:
    approval_id: UUID
    tenant_id: UUID
    ticket_id: UUID
    ticket_key: str
    requester_user_id: UUID
    status: str
    row_version: int
    mode: str
    approver_rule: Any
    approved_transition_id: UUID | None
    rejected_transition_id: UUID | None
    allow_requester_self_approval: bool
    expires_at: datetime | None
    approver_user_id: UUID
    existing_decision: str | None
