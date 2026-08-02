"""Approval API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApprovalItem(BaseModel):
    approval_id: UUID
    ticket_key: str
    ticket_summary: str
    approval_code: str
    approval_name: str
    approval_mode: str
    status: str
    requested_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None
    row_version: int
    sequence_number: int
    decision: str | None
    decision_comment: str | None
    decided_at: datetime | None


class ApprovalList(BaseModel):
    items: list[ApprovalItem]


class ApprovalDecisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["APPROVE", "REJECT"]
    comment: str | None = Field(default=None, max_length=10_000)
    expected_version: int = Field(ge=1)


class ApprovalDecisionResponse(BaseModel):
    approval: ApprovalItem
    replayed: bool = False
