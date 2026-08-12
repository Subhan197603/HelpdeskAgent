"""Read-only AI governance orchestration with explicit secret boundaries."""

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from apps.api.app.ai.governance_models import (
    GovernancePolicy,
    GovernanceRetrievalConfiguration,
)
from apps.api.app.ai.governance_repository import AIGovernanceRepository
from apps.api.app.ai.governance_schemas import (
    AIGovernanceOverviewResponse,
    AIPolicyListResponse,
    AIPolicySummaryResponse,
    AIUsageResponse,
    BudgetState,
    CircuitStatusResponse,
    GlobalAISwitchResponse,
    ModelAssignmentResponse,
    OperationalState,
    ProviderStatusResponse,
    RetrievalGovernanceResponse,
    RunOutcomeResponse,
    UsageAgentResponse,
    UsageCurrencyTotalResponse,
    UsageDailyResponse,
    UsageProviderResponse,
)
from apps.api.app.ai.resilience import CircuitBreaker
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AppError, NotFoundError
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class AIGovernanceRequestError(AppError):
    status_code, title, error_code = 400, "Invalid AI governance request", "ai_governance_request"


class AIGovernanceService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        settings: Settings,
        circuit_breaker: CircuitBreaker,
    ) -> None:
        self._factory = factory
        self._settings = settings
        self._circuit_breaker = circuit_breaker

    async def overview(self, context: RequestContext) -> AIGovernanceOverviewResponse:
        tenant_id = _tenant(context)
        async with self._factory(context) as uow:
            repository = AIGovernanceRepository(uow.session)
            assignments = await repository.assignments(tenant_id)
            retrieval = await repository.retrieval(tenant_id)
            await uow.commit()

        provider_statuses = self._providers()
        configured = {
            (provider.provider_alias, model)
            for provider in provider_statuses
            for model in provider.model_aliases
            if provider.configured
        }
        known_models = {
            (assignment.provider_alias, assignment.model_alias) for assignment in assignments
        } | {
            (assignment.fallback_provider_alias, assignment.fallback_model_alias)
            for assignment in assignments
            if assignment.fallback_provider_alias and assignment.fallback_model_alias
        }
        observations = await self._circuit_breaker.snapshot(known_models)
        retrieval_status = self._retrieval(retrieval)
        operational_state, explanation = self._operational_state(
            provider_statuses, retrieval_status
        )
        return AIGovernanceOverviewResponse(
            as_of=datetime.now(UTC),
            global_switch=GlobalAISwitchResponse(
                enabled=self._settings.ai_globally_enabled,
                calls_blocked=not self._settings.ai_globally_enabled,
            ),
            providers=provider_statuses,
            model_assignments=[
                ModelAssignmentResponse(
                    **asdict(assignment),
                    provider_deployed=(assignment.provider_alias, assignment.model_alias)
                    in configured,
                    fallback_deployed=(
                        (
                            assignment.fallback_provider_alias,
                            assignment.fallback_model_alias,
                        )
                        in configured
                        if assignment.fallback_provider_alias and assignment.fallback_model_alias
                        else None
                    ),
                )
                for assignment in assignments
            ],
            circuits=[CircuitStatusResponse(**asdict(observation)) for observation in observations],
            retrieval=retrieval_status,
            operational_state=operational_state,
            operational_explanation=explanation,
        )

    async def policies(
        self, context: RequestContext, *, limit: int, offset: int
    ) -> AIPolicyListResponse:
        tenant_id = _tenant(context)
        async with self._factory(context) as uow:
            rows = await AIGovernanceRepository(uow.session).policies(
                tenant_id, limit=limit + 1, offset=offset
            )
            await uow.commit()
        return AIPolicyListResponse(
            as_of=datetime.now(UTC),
            items=[_policy(row) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )

    async def policy(self, context: RequestContext, policy_id: UUID) -> AIPolicySummaryResponse:
        tenant_id = _tenant(context)
        async with self._factory(context) as uow:
            row = await AIGovernanceRepository(uow.session).policy(tenant_id, policy_id)
            await uow.commit()
        if row is None:
            raise NotFoundError("AI policy was not found.")
        return _policy(row)

    async def usage(
        self,
        context: RequestContext,
        *,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
    ) -> AIUsageResponse:
        tenant_id = _tenant(context)
        now = datetime.now(UTC)
        end = occurred_to or now
        start = occurred_from or end - timedelta(days=7)
        if start.tzinfo is None or end.tzinfo is None:
            raise AIGovernanceRequestError("Usage timestamps must include a timezone.")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        if start >= end:
            raise AIGovernanceRequestError("Usage start must be before usage end.")
        if end - start > timedelta(days=90):
            raise AIGovernanceRequestError("Usage range cannot exceed 90 days.")
        if end > now + timedelta(minutes=1):
            raise AIGovernanceRequestError("Usage end cannot be in the future.")
        async with self._factory(context) as uow:
            usage = await AIGovernanceRepository(uow.session).usage(tenant_id, start, end)
            await uow.commit()
        return AIUsageResponse(
            as_of=now,
            occurred_from=start,
            occurred_to=end,
            totals_by_currency=[
                UsageCurrencyTotalResponse.model_validate(x) for x in usage.totals_by_currency
            ],
            daily=[UsageDailyResponse.model_validate(x) for x in usage.daily],
            providers=[UsageProviderResponse.model_validate(x) for x in usage.providers],
            agents=[UsageAgentResponse.model_validate(x) for x in usage.agents],
            run_outcomes=[RunOutcomeResponse.model_validate(x) for x in usage.run_outcomes],
        )

    def _providers(self) -> list[ProviderStatusResponse]:
        definitions = (
            ("anthropic", self._settings.anthropic_model_aliases, self._settings.anthropic_api_key),
            ("openai", self._settings.openai_model_aliases, self._settings.openai_api_key),
        )
        return [
            ProviderStatusResponse(
                provider_alias=alias,
                configured=bool(models) and secret is not None,
                enabled=self._settings.ai_globally_enabled and bool(models) and secret is not None,
                model_aliases=sorted(models),
            )
            for alias, models, secret in definitions
        ]

    def _retrieval(
        self, row: GovernanceRetrievalConfiguration | None
    ) -> RetrievalGovernanceResponse:
        http_configured = (
            self._settings.retrieval_embedding_endpoint is not None
            and self._settings.retrieval_embedding_api_key is not None
        )
        reranker_configured = (
            self._settings.retrieval_reranker_enabled
            and self._settings.retrieval_reranker_endpoint is not None
            and self._settings.retrieval_reranker_api_key is not None
        )
        common = {
            "query_embedding_provider": self._settings.retrieval_embedding_provider,
            "query_embedding_model_code": self._settings.retrieval_embedding_model_code,
            "query_embedding_configured": (
                self._settings.retrieval_embedding_provider == "deterministic" or http_configured
            ),
            "reranker_enabled": self._settings.retrieval_reranker_enabled,
            "reranker_configured": reranker_configured,
            "reranker_model_code": (
                self._settings.retrieval_reranker_model_code
                if self._settings.retrieval_reranker_enabled
                else None
            ),
            "published_configuration_available": row is not None,
        }
        if row is None:
            return RetrievalGovernanceResponse(
                **common,  # type: ignore[arg-type]
                retrieval_configuration_version_id=None,
                tenant_specific=None,
                version_number=None,
                effective_from=None,
                effective_to=None,
                embedding_configuration_version_id=None,
            )
        return RetrievalGovernanceResponse(
            **common,  # type: ignore[arg-type]
            retrieval_configuration_version_id=row.retrieval_configuration_version_id,
            tenant_specific=row.tenant_specific,
            version_number=row.version_number,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            embedding_configuration_version_id=row.embedding_configuration_version_id,
        )

    def _operational_state(
        self,
        providers: list[ProviderStatusResponse],
        retrieval: RetrievalGovernanceResponse,
    ) -> tuple[OperationalState, str]:
        if not self._settings.ai_globally_enabled:
            return (
                "platform_disabled",
                "The environment-level switch blocks every AI provider call.",
            )
        if not any(provider.configured for provider in providers):
            return (
                "provider_configuration_incomplete",
                "No provider has both a safe model alias allowlist and a configured credential.",
            )
        if not retrieval.published_configuration_available:
            return (
                "retrieval_configuration_unavailable",
                "The published hybrid retrieval configuration is unavailable for this tenant.",
            )
        return (
            "ready_to_attempt",
            "Configuration permits an attempt; provider availability has not been probed.",
        )


def _tenant(context: RequestContext) -> UUID:
    if context.tenant_id is None:
        raise RuntimeError("Authenticated AI governance context is required")
    return context.tenant_id


def _policy(row: GovernancePolicy) -> AIPolicySummaryResponse:
    warning = row.warning_threshold_percent
    hard_stop = row.hard_stop_threshold_percent or Decimal("100")
    state: BudgetState = "not_configured"
    periods = (
        (row.daily_budget, row.daily_enforcement_spend),
        (row.monthly_budget, row.monthly_enforcement_spend),
    )
    configured = [(budget, spend) for budget, spend in periods if budget is not None]
    if configured:
        state = "within_budget"
        if any(spend >= budget * hard_stop / 100 for budget, spend in configured):
            state = "hard_stop"
        elif warning is not None and any(
            spend >= budget * warning / 100 for budget, spend in configured
        ):
            state = "warning"
    values = {field: getattr(row, field) for field in row.__dataclass_fields__}
    return AIPolicySummaryResponse(**values, budget_state=state)
