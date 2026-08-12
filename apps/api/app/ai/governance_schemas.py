"""Strict, secret-free API contracts for AI governance reads."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GlobalAISwitchResponse(StrictModel):
    enabled: bool
    calls_blocked: bool
    source: Literal["environment"] = "environment"
    mutable_at_runtime: Literal[False] = False
    restart_required_to_change: Literal[True] = True


class ProviderStatusResponse(StrictModel):
    provider_alias: str
    configured: bool
    enabled: bool
    model_aliases: list[str]
    availability: Literal["not_probed"] = "not_probed"


class ModelAssignmentResponse(StrictModel):
    agent_code: str
    agent_name: str
    tenant_specific: bool
    agent_configuration_version_id: UUID
    prompt_version_id: UUID
    tool_set_version_id: UUID
    retrieval_configuration_version_id: UUID
    model_policy_version_id: UUID
    provider_alias: str
    model_alias: str
    provider_deployed: bool
    fallback_provider_alias: str | None
    fallback_model_alias: str | None
    fallback_deployed: bool | None


class CircuitStatusResponse(StrictModel):
    provider_alias: str
    model_alias: str
    state: Literal["not_observed", "closed", "open"]
    recent_failures: int
    recovery_seconds_remaining: float | None
    scope: Literal["current_process"] = "current_process"


class RetrievalGovernanceResponse(StrictModel):
    query_embedding_provider: Literal["deterministic", "http"]
    query_embedding_model_code: str
    query_embedding_configured: bool
    reranker_enabled: bool
    reranker_configured: bool
    reranker_model_code: str | None
    published_configuration_available: bool
    retrieval_configuration_version_id: UUID | None
    tenant_specific: bool | None
    version_number: int | None
    effective_from: datetime | None
    effective_to: datetime | None
    embedding_configuration_version_id: UUID | None


OperationalState = Literal[
    "platform_disabled",
    "provider_configuration_incomplete",
    "retrieval_configuration_unavailable",
    "ready_to_attempt",
]


class AIGovernanceOverviewResponse(StrictModel):
    as_of: datetime
    global_switch: GlobalAISwitchResponse
    providers: list[ProviderStatusResponse]
    model_assignments: list[ModelAssignmentResponse]
    circuits: list[CircuitStatusResponse]
    retrieval: RetrievalGovernanceResponse
    operational_state: OperationalState
    operational_explanation: str


BudgetState = Literal["not_configured", "within_budget", "warning", "hard_stop"]


class AIPolicySummaryResponse(StrictModel):
    feature_policy_id: UUID
    tenant_specific: bool
    scope_type: str
    enabled: bool
    approval_status: str
    environment_code: str | None
    agent_code: str | None
    use_case_code: str | None
    daily_budget: Decimal | None
    monthly_budget: Decimal | None
    budget_currency: str | None
    warning_threshold_percent: Decimal | None
    hard_stop_threshold_percent: Decimal | None
    maximum_input_tokens: int | None
    maximum_output_tokens: int | None
    maximum_context_tokens: int | None
    maximum_tool_calls: int | None
    maximum_retrieved_chunks: int | None
    per_user_requests_per_minute: int | None
    effective_from: datetime | None
    effective_to: datetime | None
    row_version: int
    updated_at: datetime
    daily_enforcement_spend: Decimal
    monthly_enforcement_spend: Decimal
    ledger_currency_count: int
    budget_state: BudgetState


class AIPolicyListResponse(StrictModel):
    as_of: datetime
    items: list[AIPolicySummaryResponse]
    has_more: bool


class UsageCurrencyTotalResponse(StrictModel):
    currency_code: str
    requests: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    tool_calls: int
    estimated_cost: Decimal


class UsageDailyResponse(UsageCurrencyTotalResponse):
    day: datetime


class UsageProviderResponse(UsageCurrencyTotalResponse):
    provider_alias: str
    model_alias: str


class UsageAgentResponse(UsageCurrencyTotalResponse):
    agent_code: str


class RunOutcomeResponse(StrictModel):
    run_status: str
    runs: int


class AIUsageResponse(StrictModel):
    as_of: datetime
    occurred_from: datetime
    occurred_to: datetime
    bucket: Literal["day"] = "day"
    completed_calls_only: Literal[True] = True
    costs_are_estimates: Literal[True] = True
    totals_by_currency: list[UsageCurrencyTotalResponse]
    daily: list[UsageDailyResponse]
    providers: list[UsageProviderResponse]
    agents: list[UsageAgentResponse]
    run_outcomes: list[RunOutcomeResponse]
