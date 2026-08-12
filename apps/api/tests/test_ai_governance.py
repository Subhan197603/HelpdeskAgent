"""Contract and safety tests for read-only AI governance."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from apps.api.app.ai.governance_models import GovernancePolicy
from apps.api.app.ai.governance_service import (
    AIGovernanceRequestError,
    AIGovernanceService,
    _policy,
)
from apps.api.app.ai.providers import FakeLLMProvider
from apps.api.app.ai.resilience import CircuitBreaker
from apps.api.app.core.context import RequestContext
from apps.api.app.core.settings import Settings
from apps.api.app.identity.authorization import ROLE_PERMISSIONS, Permission

TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
USER_ID = UUID("22000000-0000-0000-0000-000000000001")
PATHS = (
    "/api/v1/admin/ai",
    "/api/v1/admin/ai/policies",
    "/api/v1/admin/ai/policies/21200000-0000-0000-0000-000000000001",
    "/api/v1/admin/ai/usage",
)


def _context() -> RequestContext:
    return RequestContext(
        TENANT_ID,
        USER_ID,
        "ai-admin",
        frozenset({"AI_ADMIN"}),
        frozenset(),
        None,
        str(uuid4()),
        "ai-governance-test",
    )


def test_governance_endpoints_require_authentication_and_are_read_only(
    client: TestClient,
) -> None:
    contract = cast("dict[str, Any]", client.get("/openapi.json").json())
    for path in PATHS:
        assert client.get(path).status_code == 401, path
        template = (
            "/api/v1/admin/ai/policies/{feature_policy_id}" if "/policies/212" in path else path
        )
        assert set(contract["paths"][template]) == {"get"}


def test_contract_exposes_only_allowlisted_safe_fields(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    names = {
        "AIGovernanceOverviewResponse",
        "AIPolicySummaryResponse",
        "AIUsageResponse",
        "ProviderStatusResponse",
        "RetrievalGovernanceResponse",
    }
    forbidden = {
        "api_key",
        "credential",
        "authorization",
        "endpoint",
        "database_url",
        "secret",
        "prompt_text",
        "configuration_json",
        "content_text",
        "embedding",
    }
    for name in names:
        properties = schemas[name]["properties"]
        assert not (set(properties) & forbidden), name
    provider_fields = set(schemas["ProviderStatusResponse"]["properties"])
    assert provider_fields == {
        "provider_alias",
        "configured",
        "enabled",
        "model_aliases",
        "availability",
    }


def test_ai_oversight_is_dedicated_to_ai_and_platform_administrators() -> None:
    assert Permission.AI_OVERSIGHT in ROLE_PERMISSIONS["AI_ADMIN"]
    assert Permission.AI_OVERSIGHT in ROLE_PERMISSIONS["PLATFORM_ADMIN"]
    for role in ("CUSTOMER", "AGENT", "SUPPORT_MANAGER", "PROJECT_ADMIN", "AUDITOR"):
        assert Permission.AI_OVERSIGHT not in ROLE_PERMISSIONS[role]


@pytest.mark.anyio
async def test_circuit_snapshot_is_process_local_read_only() -> None:
    clock_value = 10.0
    circuit = CircuitBreaker(2, 30, clock=lambda: clock_value)
    provider = FakeLLMProvider([], "model-a")
    before = await circuit.snapshot({("fake", "model-a")})
    assert before[0].state == "not_observed"
    await circuit.failure(provider)
    closed = await circuit.snapshot()
    assert closed[0].state == "closed"
    assert closed[0].recent_failures == 1
    await circuit.failure(provider)
    opened = await circuit.snapshot()
    assert opened[0].state == "open"
    assert opened[0].recovery_seconds_remaining == 30


def test_budget_state_uses_runtime_warning_and_hard_stop_thresholds() -> None:
    def policy_with_spend(daily_enforcement_spend: str) -> GovernancePolicy:
        return GovernancePolicy(
            feature_policy_id=uuid4(),
            tenant_specific=True,
            scope_type="TENANT",
            enabled=True,
            approval_status="APPROVED",
            environment_code=None,
            agent_code=None,
            use_case_code=None,
            daily_budget=Decimal("10"),
            monthly_budget=None,
            budget_currency="USD",
            warning_threshold_percent=Decimal("80"),
            hard_stop_threshold_percent=Decimal("100"),
            maximum_input_tokens=None,
            maximum_output_tokens=None,
            maximum_context_tokens=None,
            maximum_tool_calls=None,
            maximum_retrieved_chunks=None,
            per_user_requests_per_minute=None,
            effective_from=None,
            effective_to=None,
            row_version=1,
            updated_at=datetime.now(UTC),
            daily_enforcement_spend=Decimal(daily_enforcement_spend),
            monthly_enforcement_spend=Decimal("0"),
            ledger_currency_count=1,
        )

    assert _policy(policy_with_spend("7")).budget_state == "within_budget"
    assert _policy(policy_with_spend("8")).budget_state == "warning"
    assert _policy(policy_with_spend("10")).budget_state == "hard_stop"


@pytest.mark.anyio
async def test_usage_rejects_unbounded_invalid_ranges_before_database_access() -> None:
    def fail_factory(_: RequestContext) -> Any:
        raise AssertionError("database must not be accessed")

    service = AIGovernanceService(fail_factory, Settings(), CircuitBreaker(2, 30))
    end = datetime.now(UTC)
    with pytest.raises(AIGovernanceRequestError, match="90 days"):
        await service.usage(_context(), occurred_from=end - timedelta(days=91), occurred_to=end)


def test_provider_metadata_uses_alias_keys_and_never_deployment_values() -> None:
    settings = Settings(
        ai_globally_enabled=True,
        openai_api_key=SecretStr("top-secret"),
        openai_model_aliases={"employee-safe": "provider-deployment-123"},
    )
    service = AIGovernanceService(cast("Any", None), settings, CircuitBreaker(2, 30))
    payload = [item.model_dump(mode="json") for item in service._providers()]
    rendered = str(payload)
    assert "employee-safe" in rendered
    assert "provider-deployment-123" not in rendered
    assert "top-secret" not in rendered
