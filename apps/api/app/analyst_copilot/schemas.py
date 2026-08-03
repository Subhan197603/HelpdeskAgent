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
