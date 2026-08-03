"""Bounded analyst copilot API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CopilotAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    focus: str | None = Field(default=None, max_length=500)


class SafeTicketSummary(BaseModel):
    key: str
    summary: str
    description: str | None
    project: str
    request_type: str
    service: str | None
    environment: str | None
    status: str
    priority: str


class ClassifiedActivity(BaseModel):
    id: str
    type: str
    classification: Literal["PUBLIC", "INTERNAL", "SYSTEM"]
    body: str | None
    created_at: datetime


class SimilarTicketEvidence(BaseModel):
    key: str
    summary: str
    resolution_summary: str
    status: Literal["RESOLVED", "CLOSED"]
    resolved_at: datetime | None
    score: float
    citation_id: str


class KnowledgeEvidence(BaseModel):
    citation_id: str
    kind: Literal["INTERNAL_RUNBOOK", "ORACLE_DOCUMENTATION"]
    title: str
    excerpt: str
    canonical_uri: str
    section: str | None
    release: str | None
    score: float


class TechnicalRecommendation(BaseModel):
    classification: Literal["INFERENCE"] = "INFERENCE"
    text: str
    citation_ids: list[str]


class CopilotVersionCaptureResponse(BaseModel):
    agent_run_id: UUID
    provider: str
    model: str
    agent_configuration_version_id: UUID
    prompt_version_id: UUID
    tool_set_version_id: UUID
    model_policy_version_id: UUID
    retrieval_configuration_version_id: UUID
    knowledge_retrieval_configuration_version_id: UUID


class CopilotAnalysisResponse(BaseModel):
    conversation_id: UUID
    ticket: SafeTicketSummary
    activity: list[ClassifiedActivity]
    similar_tickets: list[SimilarTicketEvidence]
    internal_runbooks: list[KnowledgeEvidence]
    oracle_documentation: list[KnowledgeEvidence]
    recommendation: TechnicalRecommendation | None
    safety_notice: str
    versions: CopilotVersionCaptureResponse


DraftKind = Literal["PUBLIC_RESPONSE", "INTERNAL_NOTE", "RESOLUTION_SUMMARY"]


class CopilotDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: DraftKind
    focus: str | None = Field(default=None, max_length=500)


class DraftClaim(BaseModel):
    text: str
    citation_ids: list[str]
    supported: bool


class CopilotDraftResponse(BaseModel):
    draft_id: UUID
    conversation_id: UUID
    ticket_key: str
    kind: DraftKind
    classification: Literal["INFERENCE"] = "INFERENCE"
    body: str
    claims: list[DraftClaim]
    similar_tickets: list[SimilarTicketEvidence]
    internal_runbooks: list[KnowledgeEvidence]
    oracle_documentation: list[KnowledgeEvidence]
    safety_notice: str
    versions: CopilotVersionCaptureResponse


class CopilotDraftPostRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=8_000)


class CopilotDraftPostResponse(BaseModel):
    ticket_key: str
    comment_id: UUID
    visibility: Literal["PUBLIC", "INTERNAL"]
    body: str
    replayed: bool


class CopilotDraftResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transition_code: str = Field(min_length=1, max_length=100, pattern=r"^[A-Z0-9_]+$")
    row_version: int = Field(ge=1)
    resolution_code: str = Field(min_length=1, max_length=100)
    resolution_summary: str = Field(min_length=1, max_length=8_000)
    comment: str | None = Field(default=None, max_length=8_000)


class CopilotDraftResolveResponse(BaseModel):
    ticket_key: str
    status: str
    row_version: int


FeedbackDecision = Literal["APPROVED", "EDITED", "REJECTED"]
FEEDBACK_REASON_CODES: tuple[str, ...] = (
    "INCORRECT",
    "INCOMPLETE",
    "NOT_RELEVANT",
    "RISKY_ACTION",
    "POLICY_CONCERN",
    "STYLE",
    "OTHER",
)


class CopilotFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: FeedbackDecision
    reason_code: str | None = Field(default=None, max_length=40)
    comment: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def _validate_reason(self) -> "CopilotFeedbackRequest":
        if self.reason_code is not None and self.reason_code not in FEEDBACK_REASON_CODES:
            raise ValueError("reason_code must be one of the approved reason codes")
        if self.decision == "REJECTED" and self.reason_code is None:
            raise ValueError("A reason_code is required when rejecting copilot output")
        return self


class CopilotFeedbackResponse(BaseModel):
    feedback_id: UUID
    agent_run_id: UUID
    decision: FeedbackDecision
    reason_code: str | None
    created_at: datetime


class EvaluationRecord(BaseModel):
    agent_run_id: UUID
    use_case: str
    draft_kind: str | None
    claims: list[DraftClaim]
    decision: FeedbackDecision | None
    reason_code: str | None
    created_at: datetime


class EvaluationDatasetResponse(BaseModel):
    records: list[EvaluationRecord]


class CopilotUsageMetricsResponse(BaseModel):
    runs: int
    drafts: int
    drafts_posted: int
    drafts_resolved: int
    feedback: dict[str, int]
