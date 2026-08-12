"""Transport-independent records for read-only AI governance."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class GovernanceModelAssignment:
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
    fallback_provider_alias: str | None
    fallback_model_alias: str | None


@dataclass(frozen=True, slots=True)
class GovernanceRetrievalConfiguration:
    retrieval_configuration_version_id: UUID
    tenant_specific: bool
    version_number: int
    effective_from: datetime | None
    effective_to: datetime | None
    embedding_configuration_version_id: UUID | None


@dataclass(frozen=True, slots=True)
class GovernancePolicy:
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


@dataclass(frozen=True, slots=True)
class GovernanceUsage:
    totals_by_currency: list[dict[str, Any]]
    daily: list[dict[str, Any]]
    providers: list[dict[str, Any]]
    agents: list[dict[str, Any]]
    run_outcomes: list[dict[str, Any]]
