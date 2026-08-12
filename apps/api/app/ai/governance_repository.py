"""Bounded, tenant-safe PostgreSQL reads for AI governance."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.ai.governance_models import (
    GovernanceModelAssignment,
    GovernancePolicy,
    GovernanceRetrievalConfiguration,
    GovernanceUsage,
)

_ASSIGNMENTS = text(
    """
    SELECT DISTINCT ON (configuration.agent_code)
      configuration.agent_code,configuration.agent_name,
      configuration.tenant_id IS NOT NULL AS tenant_specific,
      version.agent_configuration_version_id,version.prompt_version_id,
      version.tool_set_version_id,version.retrieval_configuration_version_id,
      version.model_policy_version_id,model.provider_alias,model.model_alias,
      model.fallback_provider_alias,model.fallback_model_alias
    FROM ai.agent_configuration configuration
    JOIN LATERAL (
      SELECT candidate.* FROM ai.agent_configuration_version candidate
      WHERE candidate.agent_configuration_id=configuration.agent_configuration_id
        AND candidate.version_status='PUBLISHED'
        AND COALESCE(candidate.effective_from,'-infinity')<=now()
        AND COALESCE(candidate.effective_to,'infinity')>now()
      ORDER BY candidate.version_number DESC LIMIT 1
    ) version ON true
    JOIN ai.model_policy_version model
      ON model.model_policy_version_id=version.model_policy_version_id
     AND model.version_status='PUBLISHED'
     AND COALESCE(model.effective_from,'-infinity')<=now()
     AND COALESCE(model.effective_to,'infinity')>now()
    WHERE configuration.active_flag
      AND (configuration.tenant_id=:tenant_id OR configuration.tenant_id IS NULL)
    ORDER BY configuration.agent_code,
      (configuration.tenant_id IS NOT NULL) DESC,version.version_number DESC
    """
)

_RETRIEVAL = text(
    """
    SELECT version.retrieval_configuration_version_id,
      configuration.tenant_id IS NOT NULL AS tenant_specific,
      version.version_number,version.effective_from,version.effective_to,
      version.embedding_configuration_version_id
    FROM ai.retrieval_configuration configuration
    JOIN ai.retrieval_configuration_version version
      ON version.retrieval_configuration_id=configuration.retrieval_configuration_id
    WHERE configuration.active_flag
      AND configuration.retrieval_code='HYBRID_EVIDENCE'
      AND (configuration.tenant_id=:tenant_id OR configuration.tenant_id IS NULL)
      AND version.version_status='PUBLISHED'
      AND COALESCE(version.effective_from,'-infinity')<=now()
      AND COALESCE(version.effective_to,'infinity')>now()
    ORDER BY (configuration.tenant_id IS NOT NULL) DESC,version.version_number DESC
    LIMIT 1
    """
)

_POLICY_SELECT = """
WITH spend AS (
  SELECT COALESCE(sum(estimated_cost) FILTER (
           WHERE occurred_at>=date_trunc('day',now())),0) AS daily_spend,
         COALESCE(sum(estimated_cost) FILTER (
           WHERE occurred_at>=date_trunc('month',now())),0) AS monthly_spend,
         count(DISTINCT currency_code) AS currency_count
  FROM ai.usage_ledger WHERE tenant_id=:tenant_id
)
SELECT policy.feature_policy_id,policy.tenant_id IS NOT NULL AS tenant_specific,
  policy.scope_type,policy.enabled_flag,policy.approval_status,
  environment.environment_code,configuration.agent_code,policy.use_case_code,
  policy.daily_budget,policy.monthly_budget,policy.budget_currency,
  policy.warning_threshold_percent,policy.hard_stop_threshold_percent,
  policy.maximum_input_tokens,policy.maximum_output_tokens,
  policy.maximum_context_tokens,policy.maximum_tool_calls,
  policy.maximum_retrieved_chunks,policy.per_user_requests_per_minute,
  policy.effective_from,policy.effective_to,policy.row_version,policy.updated_at,
  spend.daily_spend,spend.monthly_spend,spend.currency_count
FROM ai.feature_policy policy CROSS JOIN spend
LEFT JOIN ai.agent_configuration configuration
  ON configuration.agent_configuration_id=policy.agent_configuration_id
LEFT JOIN config.application_environment environment
  ON environment.application_environment_id=policy.application_environment_id
WHERE (policy.tenant_id=:tenant_id OR policy.tenant_id IS NULL)
  AND (configuration.agent_configuration_id IS NULL
       OR configuration.tenant_id=:tenant_id OR configuration.tenant_id IS NULL)
  AND (environment.application_environment_id IS NULL
       OR environment.tenant_id=:tenant_id)
"""

_POLICIES = text(
    _POLICY_SELECT
    + """
    ORDER BY CASE policy.scope_type WHEN 'AGENT' THEN 1 WHEN 'USE_CASE' THEN 2
      WHEN 'ENVIRONMENT' THEN 3 WHEN 'TENANT' THEN 4 ELSE 5 END,
      policy.updated_at DESC,policy.feature_policy_id
    LIMIT :limit OFFSET :offset
    """
)

_POLICY = text(_POLICY_SELECT + " AND policy.feature_policy_id=:policy_id")

_USAGE = text(
    """
    WITH scoped AS MATERIALIZED (
      SELECT ledger.*,COALESCE(configuration.agent_code,'UNASSIGNED') AS agent_code
      FROM ai.usage_ledger ledger
      LEFT JOIN ai.agent_configuration configuration
        ON configuration.agent_configuration_id=ledger.agent_configuration_id
      WHERE ledger.tenant_id=:tenant_id
        AND ledger.occurred_at>=:occurred_from AND ledger.occurred_at<:occurred_to
    ), outcomes AS MATERIALIZED (
      SELECT run_status,count(*) AS runs FROM ai.agent_run
      WHERE tenant_id=:tenant_id
        AND started_at>=:occurred_from AND started_at<:occurred_to
      GROUP BY run_status
    )
    SELECT
      COALESCE((SELECT jsonb_agg(to_jsonb(item) ORDER BY item.currency_code)
        FROM (SELECT currency_code,count(*) AS requests,sum(input_tokens) AS input_tokens,
          sum(output_tokens) AS output_tokens,sum(cached_tokens) AS cached_tokens,
          sum(tool_call_count) AS tool_calls,sum(estimated_cost) AS estimated_cost
          FROM scoped GROUP BY currency_code) item),'[]'::jsonb) AS totals,
      COALESCE((SELECT jsonb_agg(to_jsonb(item) ORDER BY item.day,item.currency_code)
        FROM (SELECT date_trunc('day',occurred_at) AS day,currency_code,
          count(*) AS requests,sum(input_tokens) AS input_tokens,
          sum(output_tokens) AS output_tokens,sum(cached_tokens) AS cached_tokens,
          sum(tool_call_count) AS tool_calls,sum(estimated_cost) AS estimated_cost
          FROM scoped GROUP BY date_trunc('day',occurred_at),currency_code) item),
        '[]'::jsonb) AS daily,
      COALESCE((SELECT jsonb_agg(to_jsonb(item)
        ORDER BY item.provider_alias,item.model_alias,item.currency_code)
        FROM (SELECT provider_alias,model_alias,currency_code,count(*) AS requests,
          sum(input_tokens) AS input_tokens,sum(output_tokens) AS output_tokens,
          sum(cached_tokens) AS cached_tokens,sum(tool_call_count) AS tool_calls,
          sum(estimated_cost) AS estimated_cost FROM scoped
          GROUP BY provider_alias,model_alias,currency_code) item),'[]'::jsonb) AS providers,
      COALESCE((SELECT jsonb_agg(to_jsonb(item) ORDER BY item.agent_code,item.currency_code)
        FROM (SELECT agent_code,currency_code,count(*) AS requests,
          sum(input_tokens) AS input_tokens,sum(output_tokens) AS output_tokens,
          sum(cached_tokens) AS cached_tokens,sum(tool_call_count) AS tool_calls,
          sum(estimated_cost) AS estimated_cost FROM scoped
          GROUP BY agent_code,currency_code) item),'[]'::jsonb) AS agents,
      COALESCE((SELECT jsonb_agg(to_jsonb(outcomes) ORDER BY run_status)
        FROM outcomes),'[]'::jsonb) AS outcomes
    """
)


class AIGovernanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def assignments(self, tenant_id: UUID) -> tuple[GovernanceModelAssignment, ...]:
        rows = (await self._session.execute(_ASSIGNMENTS, {"tenant_id": tenant_id})).mappings()
        return tuple(
            GovernanceModelAssignment(
                agent_code=row["agent_code"],
                agent_name=row["agent_name"],
                tenant_specific=bool(row["tenant_specific"]),
                agent_configuration_version_id=row["agent_configuration_version_id"],
                prompt_version_id=row["prompt_version_id"],
                tool_set_version_id=row["tool_set_version_id"],
                retrieval_configuration_version_id=row["retrieval_configuration_version_id"],
                model_policy_version_id=row["model_policy_version_id"],
                provider_alias=row["provider_alias"],
                model_alias=row["model_alias"],
                fallback_provider_alias=row["fallback_provider_alias"],
                fallback_model_alias=row["fallback_model_alias"],
            )
            for row in rows
        )

    async def retrieval(self, tenant_id: UUID) -> GovernanceRetrievalConfiguration | None:
        row = (
            (await self._session.execute(_RETRIEVAL, {"tenant_id": tenant_id}))
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return GovernanceRetrievalConfiguration(
            retrieval_configuration_version_id=row["retrieval_configuration_version_id"],
            tenant_specific=bool(row["tenant_specific"]),
            version_number=row["version_number"],
            effective_from=row["effective_from"],
            effective_to=row["effective_to"],
            embedding_configuration_version_id=row["embedding_configuration_version_id"],
        )

    async def policies(
        self, tenant_id: UUID, *, limit: int, offset: int
    ) -> tuple[GovernancePolicy, ...]:
        rows = (
            await self._session.execute(
                _POLICIES, {"tenant_id": tenant_id, "limit": limit, "offset": offset}
            )
        ).mappings()
        return tuple(_policy(row) for row in rows)

    async def policy(self, tenant_id: UUID, policy_id: UUID) -> GovernancePolicy | None:
        row = (
            (await self._session.execute(_POLICY, {"tenant_id": tenant_id, "policy_id": policy_id}))
            .mappings()
            .one_or_none()
        )
        return _policy(row) if row is not None else None

    async def usage(
        self, tenant_id: UUID, occurred_from: datetime, occurred_to: datetime
    ) -> GovernanceUsage:
        row = (
            (
                await self._session.execute(
                    _USAGE,
                    {
                        "tenant_id": tenant_id,
                        "occurred_from": occurred_from,
                        "occurred_to": occurred_to,
                    },
                )
            )
            .mappings()
            .one()
        )
        return GovernanceUsage(
            list(row["totals"]),
            list(row["daily"]),
            list(row["providers"]),
            list(row["agents"]),
            list(row["outcomes"]),
        )


def _policy(row: Any) -> GovernancePolicy:
    return GovernancePolicy(
        feature_policy_id=row["feature_policy_id"],
        tenant_specific=bool(row["tenant_specific"]),
        scope_type=row["scope_type"],
        enabled=bool(row["enabled_flag"]),
        approval_status=row["approval_status"],
        environment_code=row["environment_code"],
        agent_code=row["agent_code"],
        use_case_code=row["use_case_code"],
        daily_budget=row["daily_budget"],
        monthly_budget=row["monthly_budget"],
        budget_currency=row["budget_currency"],
        warning_threshold_percent=row["warning_threshold_percent"],
        hard_stop_threshold_percent=row["hard_stop_threshold_percent"],
        maximum_input_tokens=row["maximum_input_tokens"],
        maximum_output_tokens=row["maximum_output_tokens"],
        maximum_context_tokens=row["maximum_context_tokens"],
        maximum_tool_calls=row["maximum_tool_calls"],
        maximum_retrieved_chunks=row["maximum_retrieved_chunks"],
        per_user_requests_per_minute=row["per_user_requests_per_minute"],
        effective_from=row["effective_from"],
        effective_to=row["effective_to"],
        row_version=row["row_version"],
        updated_at=row["updated_at"],
        daily_enforcement_spend=row["daily_spend"],
        monthly_enforcement_spend=row["monthly_spend"],
        ledger_currency_count=row["currency_count"],
    )
