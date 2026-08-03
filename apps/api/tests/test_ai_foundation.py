"""Deterministic Task 8.1 provider, resilience, settings, and tool tests."""

import asyncio
import logging
from decimal import Decimal
from typing import Any, ClassVar, cast
from uuid import uuid4

import pytest
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from apps.api.app.ai import service as ai_service_module
from apps.api.app.ai.models import (
    EffectiveAIPolicy,
    LLMResult,
    ModelUsage,
    ProviderRequest,
    ToolResult,
)
from apps.api.app.ai.providers import (
    AnthropicProvider,
    FakeLLMProvider,
    OpenAIProvider,
    ProviderError,
)
from apps.api.app.ai.registry import ProviderRegistry, UnknownProviderAliasError
from apps.api.app.ai.resilience import CircuitBreaker, CircuitOpenError, ResilientProviderExecutor
from apps.api.app.ai.service import AIDisabledError, AIGateway
from apps.api.app.ai.tools import InvalidToolInputError, ToolRegistry
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.core.settings import Settings
from apps.api.app.identity.authorization import AuthorizationService, Permission


def _context(*roles: str) -> RequestContext:
    return RequestContext(
        tenant_id=uuid4(),
        user_id=uuid4(),
        external_subject="test-subject",
        roles=frozenset(roles),
        support_group_ids=frozenset(),
        business_unit_id=None,
        correlation_id="correlation",
        request_id="request",
    )


def _result(provider: str = "fake", model: str = "fake-model") -> LLMResult:
    return LLMResult(
        text="safe response",
        tool_requests=(),
        usage=ModelUsage(3, 2, 1, Decimal("0.004"), "USD"),
        provider=provider,
        model=model,
        finish_reason="completed",
    )


def test_fake_provider_is_deterministic_and_records_request() -> None:
    request = ProviderRequest("approved prompt", ({"role": "user", "content": "hello"},))
    provider = FakeLLMProvider([_result()])

    assert asyncio.run(provider.generate(request)) == _result()
    assert provider.requests == [request]
    with pytest.raises(ProviderError, match="FAKE_PROVIDER_EXHAUSTED"):
        asyncio.run(provider.generate(request))


def test_openai_adapter_maps_alias_and_parses_typed_result_without_logging_secret(
    caplog: pytest.LogCaptureFixture,
) -> None:
    seen: dict[str, Any] = {}

    async def transport(
        endpoint: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        seen.update(endpoint=endpoint, headers=headers, payload=payload, timeout=timeout)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "answer"}],
                },
                {
                    "type": "function_call",
                    "call_id": "1",
                    "name": "lookup",
                    "arguments": '{"id":7}',
                },
            ],
            "status": "completed",
            "usage": {"input_tokens": 4, "output_tokens": 2},
        }

    provider = OpenAIProvider(
        "https://provider.example/v1/responses",
        "openai-super-secret",
        "employee-primary",
        "deployment-42",
        9,
        transport,
    )
    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(
            provider.generate(
                ProviderRequest(
                    "secret prompt",
                    (),
                    (
                        {
                            "name": "lookup",
                            "description": "Lookup",
                            "input_schema": {"type": "object"},
                        },
                    ),
                )
            )
        )

    assert result.provider == "openai"
    assert result.model == "employee-primary"
    assert result.tool_requests[0].arguments == {"id": 7}
    assert seen["payload"]["model"] == "deployment-42"
    assert seen["payload"]["tools"][0]["type"] == "function"
    assert "openai-super-secret" not in caplog.text
    assert "secret prompt" not in caplog.text


def test_anthropic_adapter_parses_text_tools_and_usage() -> None:
    async def transport(
        endpoint: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        del endpoint, headers, payload, timeout
        return {
            "content": [
                {"type": "text", "text": "answer"},
                {"type": "tool_use", "id": "call-2", "name": "lookup", "input": {"id": 8}},
            ],
            "usage": {"input_tokens": 5, "output_tokens": 3},
            "stop_reason": "tool_use",
        }

    provider = AnthropicProvider(
        "https://provider.example/v1/messages",
        "anthropic-secret",
        "analyst-primary",
        "deployment-9",
        10,
        transport,
    )
    result = asyncio.run(provider.generate(ProviderRequest("instructions", ())))

    assert result.text == "answer"
    assert result.tool_requests[0].name == "lookup"
    assert result.usage == ModelUsage(input_tokens=5, output_tokens=3)


class _ScriptedProvider:
    def __init__(self, alias: str, outcomes: list[LLMResult | BaseException]) -> None:
        self.provider_alias = alias
        self.model_alias = "model"
        self.outcomes = outcomes
        self.calls = 0

    async def generate(self, request: ProviderRequest) -> LLMResult:
        del request
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _executor(
    circuit: CircuitBreaker, attempts: int = 2, timeout: float = 1
) -> ResilientProviderExecutor:
    return ResilientProviderExecutor(
        timeout_seconds=timeout,
        maximum_attempts=attempts,
        circuit_breaker=circuit,
    )


def test_retry_then_success_and_explicit_fallback() -> None:
    request = ProviderRequest("instructions", ())
    primary = _ScriptedProvider(
        "primary", [ProviderError("RATE_LIMIT", retryable=True), _result("primary", "model")]
    )
    result = asyncio.run(_executor(CircuitBreaker(5, 60)).generate(primary, request))
    assert result.provider == "primary"
    assert primary.calls == 2

    exhausted = _ScriptedProvider(
        "primary", [ProviderError("DOWN", retryable=True), ProviderError("DOWN", retryable=True)]
    )
    fallback = _ScriptedProvider("fallback", [_result("fallback", "model")])
    result = asyncio.run(
        _executor(CircuitBreaker(5, 60)).generate(exhausted, request, fallback=fallback)
    )
    assert result.provider == "fallback"
    assert fallback.calls == 1


def test_fallback_is_not_implicit_and_circuit_opens_then_recovers() -> None:
    now = [0.0]
    circuit = CircuitBreaker(1, 10, lambda: now[0])
    provider = _ScriptedProvider(
        "primary", [ProviderError("DOWN", retryable=True), _result("primary", "model")]
    )
    executor = _executor(circuit, attempts=1)
    with pytest.raises(ProviderError, match="DOWN"):
        asyncio.run(executor.generate(provider, ProviderRequest("instructions", ())))
    with pytest.raises(CircuitOpenError):
        asyncio.run(executor.generate(provider, ProviderRequest("instructions", ())))
    now[0] = 11
    assert asyncio.run(executor.generate(provider, ProviderRequest("instructions", ()))).text


def test_timeout_is_bounded_and_cancellation_propagates() -> None:
    class SlowProvider:
        provider_alias = "slow"
        model_alias = "model"

        async def generate(self, request: ProviderRequest) -> LLMResult:
            del request
            await asyncio.sleep(1)
            return _result()

    with pytest.raises(TimeoutError):
        asyncio.run(
            _executor(CircuitBreaker(3, 60), attempts=1, timeout=0.001).generate(
                SlowProvider(), ProviderRequest("instructions", ())
            )
        )

    async def cancelled() -> None:
        task = asyncio.create_task(
            _executor(CircuitBreaker(3, 60), timeout=5).generate(
                SlowProvider(), ProviderRequest("instructions", ())
            )
        )
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancelled())


class _LookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket_id: int


class _LookupTool:
    name = "get_ticket_status"
    description = "Read an authorized ticket status"
    input_model = _LookupInput
    required_permission = Permission.TICKET_READ_OWN

    def __init__(self) -> None:
        self.seen_context: RequestContext | None = None
        self.authorized_input: _LookupInput | None = None

    async def authorize(self, context: RequestContext, input_data: _LookupInput) -> None:
        assert context.tenant_id is not None
        self.authorized_input = input_data

    async def execute(self, context: RequestContext, input_data: _LookupInput) -> ToolResult:
        self.seen_context = context
        return ToolResult(content={"ticket_id": input_data.ticket_id, "status": "OPEN"})


def test_tool_registry_validates_authorizes_and_propagates_context() -> None:
    tool = _LookupTool()
    registry = ToolRegistry(AuthorizationService())
    registry.register(tool)
    context = _context("CUSTOMER")

    result = asyncio.run(registry.execute(tool.name, {"ticket_id": 7}, context))
    assert result.content["status"] == "OPEN"
    assert tool.seen_context is context
    assert tool.authorized_input == _LookupInput(ticket_id=7)
    assert registry.schemas(frozenset({tool.name}))[0]["name"] == tool.name
    with pytest.raises(InvalidToolInputError):
        asyncio.run(registry.execute(tool.name, {"ticket_id": 7, "unexpected": True}, context))
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register(tool)


def test_tool_registry_denies_before_execution() -> None:
    tool = _LookupTool()
    registry = ToolRegistry(AuthorizationService())
    registry.register(tool)
    with pytest.raises(AuthorizationError):
        asyncio.run(registry.execute(tool.name, {"ticket_id": 7}, _context()))
    assert tool.seen_context is None
    assert tool.authorized_input is None


def test_provider_registry_uses_environment_secret_and_allow_listed_alias() -> None:
    settings = Settings(
        ai_globally_enabled=True,
        openai_api_key=SecretStr("provider-secret"),
        openai_model_aliases={"employee-primary": "deployment-name"},
    )
    provider = ProviderRegistry(settings).resolve("openai", "employee-primary")
    assert provider.model_alias == "employee-primary"
    assert "provider-secret" not in repr(settings)
    with pytest.raises(UnknownProviderAliasError):
        ProviderRegistry(settings).resolve("openai", "unapproved-model")
    assert not any("credential" in name or "api_key" in name for name in _database_policy_fields())


def test_ai_provider_settings_fail_closed() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings(
            ai_globally_enabled=True,
            openai_api_key=None,
            openai_model_aliases={"employee-primary": "deployment"},
        )
    with pytest.raises(ValidationError, match="must use HTTPS"):
        Settings(
            ai_globally_enabled=True,
            openai_api_key=SecretStr("secret"),
            openai_api_endpoint="http://provider.example/v1/responses",
            openai_model_aliases={"employee-primary": "deployment"},
        )
    with pytest.raises(ValidationError, match="non-negative"):
        Settings(ai_model_input_cost_per_million={"openai:employee-primary": Decimal("-1")})


def _database_policy_fields() -> set[str]:
    """Document the deliberately secret-free persisted model-policy contract."""
    return {
        "provider_alias",
        "model_alias",
        "fallback_provider_alias",
        "fallback_model_alias",
    }


def test_disabled_gateway_never_opens_a_unit_of_work() -> None:
    touched = False

    def forbidden_factory(context: RequestContext) -> Any:
        nonlocal touched
        del context
        touched = True
        raise AssertionError("disabled AI must not touch persistence")

    settings = Settings(ai_globally_enabled=False)
    gateway = AIGateway(
        forbidden_factory,
        settings,
        ProviderRegistry(settings),
        _executor(CircuitBreaker(2, 60)),
    )
    with pytest.raises(AIDisabledError, match="deterministic ticketing"):
        asyncio.run(
            gateway.generate(
                _context("CUSTOMER"),
                conversation_id=uuid4(),
                agent_code="EMPLOYEE_HELPDESK",
                use_case_code="HELPDESK_CHAT",
                request=ProviderRequest("instructions", ()),
            )
        )
    assert touched is False


def test_gateway_records_policy_versions_and_configured_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifiers = [uuid4() for _ in range(8)]
    policy = EffectiveAIPolicy(
        feature_policy_id=identifiers[0],
        agent_configuration_id=identifiers[1],
        agent_configuration_version_id=identifiers[2],
        prompt_version_id=identifiers[3],
        tool_set_version_id=identifiers[4],
        retrieval_configuration_version_id=identifiers[5],
        model_policy_version_id=identifiers[6],
        provider_alias="fake",
        model_alias="fake-model",
        fallback_provider_alias=None,
        fallback_model_alias=None,
        maximum_input_tokens=100,
        maximum_output_tokens=50,
        maximum_tool_calls=0,
        per_user_requests_per_minute=None,
        budget_remaining=True,
    )
    run_id = identifiers[7]

    class FakeRepository:
        completed: ClassVar[tuple[EffectiveAIPolicy, LLMResult] | None] = None

        def __init__(self, session: object) -> None:
            del session

        async def effective_policy(self, *args: object, **kwargs: object) -> EffectiveAIPolicy:
            del args, kwargs
            return policy

        async def start_run(self, *args: object, **kwargs: object) -> Any:
            del args, kwargs
            return run_id

        async def complete_run(
            self,
            context: RequestContext,
            completed_run_id: Any,
            completed_policy: EffectiveAIPolicy,
            result: LLMResult,
            *,
            latency_ms: int,
        ) -> None:
            del context, latency_ms
            assert completed_run_id == run_id
            FakeRepository.completed = (completed_policy, result)

        async def fail_run(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("successful provider call must not fail the run")

    class FakeUnitOfWork:
        session = object()

        async def __aenter__(self) -> "FakeUnitOfWork":
            return self

        async def __aexit__(self, *args: object) -> None:
            del args

        async def commit(self) -> None:
            return None

    provider = FakeLLMProvider(
        [
            LLMResult(
                "answer",
                (),
                ModelUsage(input_tokens=1_000_000, output_tokens=2_000_000),
                "fake",
                "fake-model",
                "completed",
            )
        ]
    )

    class FakeRegistry:
        def resolve(self, provider_alias: str, model_alias: str) -> FakeLLMProvider:
            assert (provider_alias, model_alias) == ("fake", "fake-model")
            return provider

    monkeypatch.setattr(ai_service_module, "AIRepository", FakeRepository)
    settings = Settings(
        ai_globally_enabled=True,
        openai_api_key=SecretStr("configuration-validation-only"),
        openai_model_aliases={"configured": "deployment"},
        ai_model_input_cost_per_million={"fake:fake-model": Decimal("1")},
        ai_model_output_cost_per_million={"fake:fake-model": Decimal("2")},
    )
    gateway = AIGateway(
        cast("Any", lambda context: FakeUnitOfWork()),
        settings,
        cast("Any", FakeRegistry()),
        _executor(CircuitBreaker(2, 60)),
    )
    result = asyncio.run(
        gateway.generate(
            _context("CUSTOMER"),
            conversation_id=uuid4(),
            agent_code="EMPLOYEE_HELPDESK",
            use_case_code="HELPDESK_CHAT",
            request=ProviderRequest("short", ()),
        )
    )

    assert result.usage.cost_estimate == Decimal("5")
    assert result.usage.currency_code == "USD"
    assert FakeRepository.completed is not None
    assert FakeRepository.completed[0].prompt_version_id == policy.prompt_version_id
