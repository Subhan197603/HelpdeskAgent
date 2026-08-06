"""Administration shell contracts: real counts, safe status, audit reads."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

OutcomeCode = Literal["SUCCESS", "DENIED", "FAILED", "PARTIAL"]
DecisionCode = Literal["ALLOWED", "DENIED"]


class AdminOverviewResponse(BaseModel):
    active_users: int
    support_groups: int
    open_tickets: int
    published_knowledge_documents: int


class DependencyStatusItem(BaseModel):
    name: str
    status: Literal["healthy", "unhealthy", "disabled"]
    required: bool


class SystemStatusResponse(BaseModel):
    app_version: str
    environment: str
    migration_head: str | None
    oidc_enabled: bool
    developer_identity_enabled: bool
    ai_globally_enabled: bool
    object_storage_enabled: bool
    clamav_required: bool
    metrics_endpoint_enabled: bool
    rls_enabled: bool
    retrieval_embedding_provider: str
    dependencies: list[DependencyStatusItem]


class AuditEventSummary(BaseModel):
    id: int
    actor_id: str | None
    actor_type: str
    action_code: str
    resource_type: str
    resource_id: str | None
    outcome_code: str
    failure_reason: str | None
    change_summary: dict[str, Any]
    correlation_id: UUID | None
    request_id: str | None
    occurred_at: datetime


class AuditEventListResponse(BaseModel):
    items: list[AuditEventSummary]
    has_more: bool


class SecurityEventSummary(BaseModel):
    id: int
    event_type: str
    decision_code: str
    user_id: UUID | None
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any]
    occurred_at: datetime


class SecurityEventListResponse(BaseModel):
    items: list[SecurityEventSummary]
    has_more: bool
