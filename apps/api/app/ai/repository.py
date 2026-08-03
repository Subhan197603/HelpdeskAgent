"""Persistence for effective AI policy, runs, usage, and append-only tool audit."""

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.ai.models import EffectiveAIPolicy, LLMResult
from apps.api.app.core.context import RequestContext


class AIPolicyUnavailableError(RuntimeError):
    pass


class AIPolicyDisabledError(RuntimeError):
    pass


_EFFECTIVE_POLICY = text(
    """
    WITH configuration AS (
      SELECT ac.agent_configuration_id, acv.agent_configuration_version_id,
             acv.prompt_version_id, acv.tool_set_version_id,
             acv.retrieval_configuration_version_id, acv.model_policy_version_id,
             mpv.provider_alias, mpv.model_alias,
             mpv.fallback_provider_alias, mpv.fallback_model_alias
      FROM ai.agent_configuration ac
      JOIN ai.agent_configuration_version acv
        ON acv.agent_configuration_id = ac.agent_configuration_id
      JOIN ai.model_policy_version mpv
        ON mpv.model_policy_version_id = acv.model_policy_version_id
      WHERE ac.agent_code = :agent_code
        AND ac.active_flag
        AND (ac.tenant_id IS NULL OR ac.tenant_id = :tenant_id)
        AND acv.version_status = 'PUBLISHED'
        AND mpv.version_status = 'PUBLISHED'
        AND COALESCE(acv.effective_from, '-infinity') <= now()
        AND COALESCE(acv.effective_to, 'infinity') > now()
      ORDER BY (ac.tenant_id IS NOT NULL) DESC, acv.version_number DESC
      LIMIT 1
    ), applicable AS (
      SELECT fp.*,
             CASE fp.scope_type
               WHEN 'AGENT' THEN 4 WHEN 'USE_CASE' THEN 3
               WHEN 'ENVIRONMENT' THEN 2 WHEN 'TENANT' THEN 1 ELSE 0
             END AS precedence
      FROM ai.feature_policy fp CROSS JOIN configuration c
      WHERE fp.approval_status = 'APPROVED'
        AND COALESCE(fp.effective_from, '-infinity') <= now()
        AND COALESCE(fp.effective_to, 'infinity') > now()
        AND (
          fp.scope_type = 'GLOBAL'
          OR (fp.scope_type = 'TENANT' AND fp.tenant_id = :tenant_id)
          OR (fp.scope_type = 'AGENT' AND fp.agent_configuration_id = c.agent_configuration_id)
          OR (fp.scope_type = 'USE_CASE' AND fp.use_case_code = :use_case_code
              AND (fp.tenant_id IS NULL OR fp.tenant_id = :tenant_id))
          OR (fp.scope_type = 'ENVIRONMENT'
              AND fp.application_environment_id = :environment_id)
        )
    ), selected AS (
      SELECT * FROM applicable ORDER BY precedence DESC, created_at DESC LIMIT 1
    ), limits AS (
      SELECT bool_and(enabled_flag) AS enabled,
             min(maximum_input_tokens) AS maximum_input_tokens,
             min(maximum_output_tokens) AS maximum_output_tokens,
             min(maximum_tool_calls) AS maximum_tool_calls,
             min(per_user_requests_per_minute) AS per_user_requests_per_minute
      FROM applicable
    )
    SELECT c.*, s.feature_policy_id, l.enabled, l.maximum_input_tokens,
           l.maximum_output_tokens, COALESCE(l.maximum_tool_calls, 0) AS maximum_tool_calls,
           l.per_user_requests_per_minute
    FROM configuration c CROSS JOIN selected s CROSS JOIN limits l
    """
)

_BUDGET_AND_RATE = text(
    """
    SELECT
      NOT EXISTS (
        SELECT 1 FROM ai.feature_policy fp
        WHERE fp.feature_policy_id = :feature_policy_id
          AND (
            (fp.daily_budget IS NOT NULL AND
             (SELECT COALESCE(sum(estimated_cost), 0) FROM ai.usage_ledger
              WHERE tenant_id = :tenant_id AND occurred_at >= date_trunc('day', now()))
             >= fp.daily_budget * COALESCE(fp.hard_stop_threshold_percent, 100) / 100)
            OR
            (fp.monthly_budget IS NOT NULL AND
             (SELECT COALESCE(sum(estimated_cost), 0) FROM ai.usage_ledger
              WHERE tenant_id = :tenant_id AND occurred_at >= date_trunc('month', now()))
             >= fp.monthly_budget * COALESCE(fp.hard_stop_threshold_percent, 100) / 100)
          )
      ) AS budget_remaining,
      (SELECT count(*) FROM ai.usage_ledger
       WHERE tenant_id = :tenant_id AND user_id = :user_id
         AND occurred_at >= now() - interval '1 minute') AS recent_requests
    """
)


@dataclass(frozen=True, slots=True)
class ToolAuditRecord:
    agent_run_id: UUID
    tool_name: str
    request: dict[str, Any]
    response: dict[str, Any] | None
    authorization_decision: str
    execution_status: str
    duration_ms: int = 0


class AIRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def effective_policy(
        self,
        context: RequestContext,
        *,
        agent_code: str,
        use_case_code: str,
        environment_id: UUID | None,
    ) -> EffectiveAIPolicy:
        if context.tenant_id is None or context.user_id is None:
            raise AIPolicyUnavailableError("Authenticated AI context is required")
        row = (
            (
                await self._session.execute(
                    _EFFECTIVE_POLICY,
                    {
                        "tenant_id": context.tenant_id,
                        "agent_code": agent_code,
                        "use_case_code": use_case_code,
                        "environment_id": environment_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AIPolicyUnavailableError("No approved AI policy is available")
        if not row["enabled"]:
            raise AIPolicyDisabledError("AI is disabled by policy")
        limits = (
            (
                await self._session.execute(
                    _BUDGET_AND_RATE,
                    {
                        "tenant_id": context.tenant_id,
                        "user_id": context.user_id,
                        "feature_policy_id": row["feature_policy_id"],
                    },
                )
            )
            .mappings()
            .one()
        )
        request_limit = row["per_user_requests_per_minute"]
        if request_limit is not None and limits["recent_requests"] >= request_limit:
            raise AIPolicyDisabledError("AI request rate limit reached")
        return EffectiveAIPolicy(
            feature_policy_id=row["feature_policy_id"],
            agent_configuration_id=row["agent_configuration_id"],
            agent_configuration_version_id=row["agent_configuration_version_id"],
            prompt_version_id=row["prompt_version_id"],
            tool_set_version_id=row["tool_set_version_id"],
            retrieval_configuration_version_id=row["retrieval_configuration_version_id"],
            model_policy_version_id=row["model_policy_version_id"],
            provider_alias=row["provider_alias"],
            model_alias=row["model_alias"],
            fallback_provider_alias=row["fallback_provider_alias"],
            fallback_model_alias=row["fallback_model_alias"],
            maximum_input_tokens=row["maximum_input_tokens"],
            maximum_output_tokens=row["maximum_output_tokens"],
            maximum_tool_calls=row["maximum_tool_calls"],
            per_user_requests_per_minute=request_limit,
            budget_remaining=bool(limits["budget_remaining"]),
        )

    async def start_run(
        self,
        context: RequestContext,
        conversation_id: UUID,
        policy: EffectiveAIPolicy,
    ) -> UUID:
        if context.tenant_id is None:
            raise AIPolicyUnavailableError("Authenticated AI context is required")
        value = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.agent_run(
                      tenant_id, conversation_id, provider_name, model_name, run_status,
                      agent_configuration_version_id, prompt_version_id, tool_set_version_id,
                      model_policy_version_id, retrieval_configuration_version_id,
                      feature_policy_id
                    ) VALUES (
                      :tenant_id, :conversation_id, :provider, :model, 'RUNNING',
                      :agent_version, :prompt_version, :tool_version, :model_version,
                      :retrieval_version, :feature_policy
                    ) RETURNING agent_run_id
                    """
                ),
                {
                    "tenant_id": context.tenant_id,
                    "conversation_id": conversation_id,
                    "provider": policy.provider_alias,
                    "model": policy.model_alias,
                    "agent_version": policy.agent_configuration_version_id,
                    "prompt_version": policy.prompt_version_id,
                    "tool_version": policy.tool_set_version_id,
                    "model_version": policy.model_policy_version_id,
                    "retrieval_version": policy.retrieval_configuration_version_id,
                    "feature_policy": policy.feature_policy_id,
                },
            )
        ).scalar_one()
        if not isinstance(value, UUID):
            raise AIPolicyUnavailableError("Database returned an invalid AI run identifier")
        return value

    async def complete_run(
        self,
        context: RequestContext,
        run_id: UUID,
        policy: EffectiveAIPolicy,
        result: LLMResult,
        *,
        latency_ms: int,
    ) -> None:
        await self._session.execute(
            text(
                """
                UPDATE ai.agent_run SET run_status = 'COMPLETED', completed_at = now(),
                  provider_name = :provider, model_name = :model,
                  input_tokens = :input_tokens, output_tokens = :output_tokens,
                  latency_ms = :latency_ms, estimated_cost = :cost
                WHERE agent_run_id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "provider": result.provider,
                "model": result.model,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "latency_ms": latency_ms,
                "cost": result.usage.cost_estimate,
            },
        )
        await self._session.execute(
            text(
                """
                INSERT INTO ai.usage_ledger(
                  tenant_id, agent_run_id, agent_configuration_id, user_id,
                  provider_alias, model_alias, use_case_code, input_tokens,
                  output_tokens, cached_tokens, tool_call_count, estimated_cost, currency_code
                ) VALUES (
                  :tenant_id, :run_id, :agent_id, :user_id, :provider, :model,
                  :use_case, :input_tokens, :output_tokens, :cached_tokens,
                  :tool_calls, :cost, :currency
                )
                """
            ),
            {
                "tenant_id": context.tenant_id,
                "run_id": run_id,
                "agent_id": policy.agent_configuration_id,
                "user_id": context.user_id,
                "provider": result.provider,
                "model": result.model,
                "use_case": "PROVIDER_CALL",
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "cached_tokens": result.usage.cached_tokens,
                "tool_calls": len(result.tool_requests),
                "cost": result.usage.cost_estimate,
                "currency": result.usage.currency_code,
            },
        )

    async def fail_run(self, run_id: UUID, error_code: str) -> None:
        await self._session.execute(
            text(
                """
                UPDATE ai.agent_run SET run_status = 'FAILED', completed_at = now(),
                  error_code = :error_code, error_message = NULL
                WHERE agent_run_id = :run_id
                """
            ),
            {"run_id": run_id, "error_code": error_code[:100]},
        )

    async def cancel_run(self, run_id: UUID) -> None:
        await self._session.execute(
            text(
                """
                UPDATE ai.agent_run SET run_status = 'CANCELLED', completed_at = now(),
                  error_code = 'CANCELLED', error_message = NULL
                WHERE agent_run_id = :run_id
                """
            ),
            {"run_id": run_id},
        )

    async def audit_tool(self, context: RequestContext, record: ToolAuditRecord) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO ai.tool_call(
                  agent_run_id, tool_name, request_json, response_json,
                  authorization_decision, execution_status, completed_at
                ) VALUES (
                  :run_id, :tool_name, CAST(:request AS jsonb), CAST(:response AS jsonb),
                  :decision, :status, now()
                )
                """
            ),
            {
                "run_id": record.agent_run_id,
                "tool_name": record.tool_name,
                "request": _json(record.request),
                "response": _json(record.response) if record.response is not None else None,
                "decision": record.authorization_decision,
                "status": record.execution_status,
            },
        )
        await self._session.execute(
            text(
                """
                INSERT INTO audit.audit_event(
                  tenant_id, actor_id, actor_type, action_code, resource_type,
                  resource_id, new_values_json, correlation_id, request_id,
                  source_channel, outcome_code
                ) VALUES (
                  :tenant_id, :actor_id, 'USER', 'AI_TOOL_CALL_RECORDED', 'ai.tool_call',
                  :run_id, CAST(:values AS jsonb), CAST(:correlation_id AS uuid), :request_id,
                  'AI_TOOL', :outcome_code
                )
                """
            ),
            {
                "tenant_id": context.tenant_id,
                "actor_id": str(context.user_id),
                "run_id": str(record.agent_run_id),
                "values": _json(
                    {
                        "tool_name": record.tool_name,
                        "authorization_decision": record.authorization_decision,
                        "execution_status": record.execution_status,
                        "duration_ms": record.duration_ms,
                    }
                ),
                "correlation_id": context.correlation_id,
                "request_id": context.request_id,
                "outcome_code": (
                    "SUCCESS"
                    if record.execution_status == "COMPLETED"
                    else "DENIED"
                    if record.authorization_decision == "DENIED"
                    else "FAILED"
                ),
            },
        )

    async def audit_tool_requested(
        self, context: RequestContext, agent_run_id: UUID, tool_name: str
    ) -> None:
        """Persist the pre-execution event without exposing raw arguments."""
        await self._session.execute(
            text(
                """
                INSERT INTO audit.audit_event(
                  tenant_id, actor_id, actor_type, action_code, resource_type,
                  resource_id, new_values_json, correlation_id, request_id,
                  source_channel, outcome_code
                ) VALUES (
                  :tenant_id, :actor_id, 'USER', 'AI_TOOL_CALL_REQUESTED', 'ai.agent_run',
                  :run_id, CAST(:values AS jsonb), CAST(:correlation_id AS uuid), :request_id,
                  'AI_TOOL', 'SUCCESS'
                )
                """
            ),
            {
                "tenant_id": context.tenant_id,
                "actor_id": str(context.user_id),
                "run_id": str(agent_run_id),
                "values": _json({"tool_name": tool_name}),
                "correlation_id": context.correlation_id,
                "request_id": context.request_id,
            },
        )


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)
