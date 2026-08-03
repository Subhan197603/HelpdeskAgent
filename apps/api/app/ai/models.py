"""Provider-independent AI request, result, policy, and tool contracts."""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_estimate: Decimal = Decimal("0")
    currency_code: str = "USD"

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.cached_tokens) < 0:
            raise ValueError("AI token usage cannot be negative")
        if not self.cost_estimate.is_finite() or self.cost_estimate < 0:
            raise ValueError("AI cost usage must be finite and non-negative")
        if len(self.currency_code) != 3 or not self.currency_code.isalpha():
            raise ValueError("AI usage currency must be a three-letter code")


@dataclass(frozen=True, slots=True)
class ToolRequest:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResult:
    text: str
    tool_requests: tuple[ToolRequest, ...]
    usage: ModelUsage
    provider: str
    model: str
    finish_reason: str


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    instructions: str
    messages: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)
    maximum_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class EffectiveAIPolicy:
    feature_policy_id: UUID
    agent_configuration_id: UUID
    agent_configuration_version_id: UUID
    prompt_version_id: UUID
    tool_set_version_id: UUID
    retrieval_configuration_version_id: UUID
    model_policy_version_id: UUID
    provider_alias: str
    model_alias: str
    fallback_provider_alias: str | None
    fallback_model_alias: str | None
    maximum_input_tokens: int | None
    maximum_output_tokens: int | None
    maximum_tool_calls: int
    per_user_requests_per_minute: int | None
    budget_remaining: bool


class ToolResult(BaseModel):
    """Validated, serializable tool output safe to return to a model."""

    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any] = Field(default_factory=dict)
    redacted: bool = False
