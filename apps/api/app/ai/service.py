"""Policy-enforced AI provider and authorized tool application services."""

import asyncio
import time
from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

from apps.api.app.ai.models import LLMResult, ProviderRequest, ToolResult
from apps.api.app.ai.providers import ProviderError
from apps.api.app.ai.registry import ProviderRegistry, UnknownProviderAliasError
from apps.api.app.ai.repository import (
    AIPolicyDisabledError,
    AIPolicyUnavailableError,
    AIRepository,
    ToolAuditRecord,
)
from apps.api.app.ai.resilience import ResilientProviderExecutor
from apps.api.app.ai.tools import InvalidToolInputError, ToolNotFoundError, ToolRegistry
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, ExternalDependencyError
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class AIDisabledError(ExternalDependencyError):
    error_code = "ai_disabled"


class AIGateway:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        settings: Settings,
        providers: ProviderRegistry,
        executor: ResilientProviderExecutor,
    ) -> None:
        self._factory = factory
        self._settings = settings
        self._providers = providers
        self._executor = executor

    async def generate(
        self,
        context: RequestContext,
        *,
        conversation_id: UUID,
        agent_code: str,
        use_case_code: str,
        request: ProviderRequest,
        environment_id: UUID | None = None,
    ) -> LLMResult:
        if not self._settings.ai_globally_enabled:
            raise AIDisabledError("AI is disabled; use the deterministic ticketing workflow.")
        try:
            async with self._factory(context) as uow:
                repository = AIRepository(uow.session)
                policy = await repository.effective_policy(
                    context,
                    agent_code=agent_code,
                    use_case_code=use_case_code,
                    environment_id=environment_id,
                )
                if not policy.budget_remaining:
                    raise AIPolicyDisabledError("AI budget hard stop reached")
                if (
                    policy.maximum_input_tokens is not None
                    and _conservative_input_units(request) > policy.maximum_input_tokens
                ):
                    raise AIPolicyDisabledError("AI input limit exceeded")
                if len(request.tools) > policy.maximum_tool_calls:
                    raise AIPolicyDisabledError("AI tool limit exceeded")
                primary = self._providers.resolve(policy.provider_alias, policy.model_alias)
                fallback = None
                if policy.fallback_provider_alias and policy.fallback_model_alias:
                    fallback = self._providers.resolve(
                        policy.fallback_provider_alias, policy.fallback_model_alias
                    )
                bounded_request = replace(
                    request, maximum_output_tokens=policy.maximum_output_tokens
                )
                run_id = await repository.start_run(context, conversation_id, policy)
                await uow.commit()
        except (AIPolicyDisabledError, AIPolicyUnavailableError) as error:
            raise AIDisabledError("AI is unavailable under the effective policy.") from error
        except UnknownProviderAliasError as error:
            raise AIDisabledError("AI provider policy is not deployed.") from error
        started = time.monotonic()
        try:
            result = await self._executor.generate(primary, bounded_request, fallback=fallback)
            allowed_models = {(policy.provider_alias, policy.model_alias)}
            if policy.fallback_provider_alias and policy.fallback_model_alias:
                allowed_models.add((policy.fallback_provider_alias, policy.fallback_model_alias))
            if (result.provider, result.model) not in allowed_models:
                raise ProviderError("UNEXPECTED_PROVIDER_RESULT")
            if len(result.tool_requests) > policy.maximum_tool_calls:
                raise ProviderError("PROVIDER_TOOL_LIMIT_EXCEEDED")
        except asyncio.CancelledError:
            async with self._factory(context) as uow:
                await AIRepository(uow.session).cancel_run(run_id)
                await uow.commit()
            raise
        except (ProviderError, TimeoutError) as error:
            async with self._factory(context) as uow:
                await AIRepository(uow.session).fail_run(
                    run_id, getattr(error, "code", "PROVIDER_TIMEOUT")
                )
                await uow.commit()
            raise ExternalDependencyError("AI provider is unavailable.") from error
        latency_ms = max(0, int((time.monotonic() - started) * 1000))
        if result.usage.cost_estimate == 0:
            cost_key = f"{result.provider}:{result.model}"
            input_rate = self._settings.ai_model_input_cost_per_million.get(cost_key, Decimal("0"))
            output_rate = self._settings.ai_model_output_cost_per_million.get(
                cost_key, Decimal("0")
            )
            estimated_cost = (
                input_rate * result.usage.input_tokens + output_rate * result.usage.output_tokens
            ) / 1_000_000
            result = replace(
                result,
                usage=replace(
                    result.usage,
                    cost_estimate=estimated_cost,
                    currency_code=self._settings.ai_cost_currency,
                ),
            )
        async with self._factory(context) as uow:
            await AIRepository(uow.session).complete_run(
                context, run_id, policy, result, latency_ms=latency_ms
            )
            await uow.commit()
        return result


class AuthorizedToolService:
    def __init__(self, factory: UnitOfWorkFactory, tools: ToolRegistry) -> None:
        self._factory = factory
        self._tools = tools

    async def execute(
        self,
        context: RequestContext,
        *,
        agent_run_id: UUID,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        started = time.monotonic()
        async with self._factory(context) as uow:
            await AIRepository(uow.session).audit_tool_requested(context, agent_run_id, tool_name)
            await uow.commit()
        try:
            result = await self._tools.execute(tool_name, arguments, context)
        except AuthorizationError:
            await self._finalize(
                context,
                ToolAuditRecord(
                    agent_run_id,
                    tool_name,
                    arguments,
                    None,
                    "DENIED",
                    "SKIPPED",
                    _duration_ms(started),
                ),
            )
            raise
        except (InvalidToolInputError, ToolNotFoundError):
            await self._finalize(
                context,
                ToolAuditRecord(
                    agent_run_id,
                    tool_name,
                    arguments,
                    None,
                    "DENIED",
                    "SKIPPED",
                    _duration_ms(started),
                ),
            )
            raise
        except asyncio.CancelledError:
            await self._finalize(
                context,
                ToolAuditRecord(
                    agent_run_id,
                    tool_name,
                    arguments,
                    None,
                    "ALLOWED",
                    "FAILED",
                    _duration_ms(started),
                ),
            )
            raise
        except Exception:
            await self._finalize(
                context,
                ToolAuditRecord(
                    agent_run_id,
                    tool_name,
                    arguments,
                    None,
                    "ALLOWED",
                    "FAILED",
                    _duration_ms(started),
                ),
            )
            raise
        await self._finalize(
            context,
            ToolAuditRecord(
                agent_run_id,
                tool_name,
                arguments,
                result.model_dump(mode="json"),
                "ALLOWED",
                "COMPLETED",
                _duration_ms(started),
            ),
        )
        return result

    async def _finalize(self, context: RequestContext, record: ToolAuditRecord) -> None:
        async with self._factory(context) as uow:
            await AIRepository(uow.session).audit_tool(context, record)
            await uow.commit()


def _conservative_input_units(request: ProviderRequest) -> int:
    """Fail closed without coupling policy enforcement to a provider tokenizer."""
    return len(request.instructions) + sum(
        len(str(value)) for message in request.messages for value in message.values()
    )


def _duration_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))
