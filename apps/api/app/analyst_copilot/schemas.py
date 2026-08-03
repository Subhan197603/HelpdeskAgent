"""Bounded analyst copilot API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
