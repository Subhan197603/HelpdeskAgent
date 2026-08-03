"""Transport-independent analyst copilot records."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class SimilarResolvedTicket:
    ticket_id: UUID
    ticket_key: str
    summary: str
    resolution_summary: str
    status_code: Literal["RESOLVED", "CLOSED"]
    resolved_at: datetime | None
    closed_at: datetime | None
    score: float


@dataclass(frozen=True, slots=True)
class StoredDraft:
    draft_id: UUID
    conversation_id: UUID
    ticket_id: UUID
    kind: str
    claims: tuple[dict[str, object], ...]
    citation_labels: dict[str, str]


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    feedback_id: UUID
    created_at: datetime


@dataclass(frozen=True, slots=True)
class EvaluationRow:
    agent_run_id: UUID
    use_case: str
    draft_kind: str | None
    claims: tuple[dict[str, object], ...]
    decision: Literal["APPROVED", "EDITED", "REJECTED"] | None
    reason_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class CopilotUsageCounts:
    runs: int
    drafts: int
    drafts_posted: int
    drafts_resolved: int
    feedback: dict[str, int]


@dataclass(frozen=True, slots=True)
class CopilotVersionCapture:
    agent_run_id: UUID
    provider: str
    model: str
    agent_configuration_version_id: UUID
    prompt_version_id: UUID
    tool_set_version_id: UUID
    model_policy_version_id: UUID
    retrieval_configuration_version_id: UUID
