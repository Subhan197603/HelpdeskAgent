"""Tenant-, project-, and group-scoped analyst copilot persistence."""

import json
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.analyst_copilot.models import (
    CopilotVersionCapture,
    SimilarResolvedTicket,
    StoredDraft,
)
from apps.api.app.core.context import RequestContext
from apps.api.app.retrieval.models import RetrievalEvidence


class AnalystCopilotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def release_filters(
        self, context: RequestContext, ticket_id: UUID
    ) -> tuple[str | None, str | None]:
        tenant_id, _ = _identity(context)
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT release.release_family,release.release_code
                        FROM itsm.ticket ticket
                        LEFT JOIN config.application_environment environment
                          ON environment.application_environment_id=
                            ticket.application_environment_id
                        LEFT JOIN config.product_release release
                          ON release.product_release_id=environment.current_product_release_id
                        WHERE ticket.tenant_id=:tenant_id AND ticket.ticket_id=:ticket_id
                        """
                    ),
                    {"tenant_id": tenant_id, "ticket_id": ticket_id},
                )
            )
            .mappings()
            .one()
        )
        return row["release_family"], row["release_code"]

    async def similar_resolved_tickets(
        self,
        context: RequestContext,
        *,
        ticket_id: UUID,
        query: str,
        include_all: bool,
        limit: int,
    ) -> tuple[SimilarResolvedTicket, ...]:
        tenant_id, _ = _identity(context)
        rows = (
            await self._session.execute(
                text(
                    """
                    WITH current_ticket AS (
                      SELECT project_id FROM itsm.ticket
                      WHERE tenant_id=:tenant_id AND ticket_id=:ticket_id
                    ), candidates AS (
                      SELECT candidate.ticket_id,candidate.ticket_key,candidate.summary,
                        candidate.resolution_summary,status.status_code,candidate.resolved_at,
                        candidate.closed_at,
                        ts_rank_cd(
                          to_tsvector('simple',candidate.summary || ' ' ||
                            coalesce(candidate.description,'') || ' ' ||
                            coalesce(candidate.resolution_summary,'')),
                          plainto_tsquery('simple',:query)
                        ) + CASE WHEN candidate.service_node_id=current.service_node_id
                          THEN 0.15 ELSE 0 END
                          + CASE WHEN candidate.environment_code=current.environment_code
                          THEN 0.05 ELSE 0 END AS score
                      FROM itsm.ticket candidate
                      JOIN current_ticket scope ON scope.project_id=candidate.project_id
                      JOIN itsm.ticket current ON current.ticket_id=:ticket_id
                        AND current.tenant_id=:tenant_id
                      JOIN config.workflow_status status ON status.status_id=candidate.status_id
                      WHERE candidate.tenant_id=:tenant_id AND candidate.ticket_id<>:ticket_id
                        AND status.status_code IN ('RESOLVED','CLOSED')
                        AND candidate.resolution_summary IS NOT NULL
                        AND length(trim(candidate.resolution_summary))>0
                        AND (:include_all OR candidate.assignment_group_id IS NULL
                          OR candidate.assignment_group_id=ANY(
                            CAST(:support_group_ids AS uuid[])))
                    )
                    SELECT * FROM candidates WHERE score>0
                    ORDER BY score DESC,coalesce(closed_at,resolved_at) DESC NULLS LAST,ticket_id
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "ticket_id": ticket_id,
                    "query": query,
                    "include_all": include_all,
                    "support_group_ids": list(context.support_group_ids),
                    "limit": limit,
                },
            )
        ).all()
        return tuple(
            SimilarResolvedTicket(
                row.ticket_id,
                row.ticket_key,
                row.summary,
                row.resolution_summary,
                cast("Literal['RESOLVED', 'CLOSED']", row.status_code),
                row.resolved_at,
                row.closed_at,
                float(row.score),
            )
            for row in rows
        )

    async def create_conversation(
        self, context: RequestContext, ticket_id: UUID, safe_context: dict[str, object]
    ) -> UUID:
        tenant_id, user_id = _identity(context)
        conversation_id = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.conversation(
                      tenant_id,conversation_type,user_id,ticket_id,status_code,metadata_json)
                    SELECT
                      :tenant_id,'ANALYST_COPILOT',:user_id,:ticket_id,'OPEN',
                      jsonb_build_object('mode','TICKET_ANALYSIS')
                    FROM itsm.ticket
                    WHERE ticket_id=:ticket_id AND tenant_id=:tenant_id
                    RETURNING conversation_id
                    """
                ),
                {"tenant_id": tenant_id, "user_id": user_id, "ticket_id": ticket_id},
            )
        ).scalar_one()
        await self._session.execute(
            text(
                """
                INSERT INTO ai.message(conversation_id,role_code,content_text,content_json)
                VALUES (
                  :conversation_id,'USER','Analyze the authorized ticket context.',
                  CAST(:content_json AS jsonb))
                """
            ),
            {"conversation_id": conversation_id, "content_json": json.dumps(safe_context)},
        )
        await self._audit(context, conversation_id, "AI_ANALYST_COPILOT_STARTED")
        if not isinstance(conversation_id, UUID):
            raise RuntimeError("Database returned an invalid conversation identifier")
        return conversation_id

    async def complete_analysis(
        self,
        context: RequestContext,
        *,
        conversation_id: UUID,
        agent_run_id: UUID,
        recommendation: str | None,
        citation_ids: list[str],
        evidence: tuple[RetrievalEvidence, ...],
        similar: tuple[SimilarResolvedTicket, ...],
    ) -> CopilotVersionCapture:
        await self._session.execute(
            text(
                """
                INSERT INTO ai.message(conversation_id,role_code,content_text,content_json)
                VALUES (
                  :conversation_id,'ASSISTANT',:content,
                  jsonb_build_object(
                    'classification','INFERENCE','citation_ids',CAST(:citations AS jsonb)))
                """
            ),
            {
                "conversation_id": conversation_id,
                "content": recommendation,
                "citations": json.dumps(citation_ids),
            },
        )
        for evidence_item in evidence:
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.retrieval_evidence(
                      agent_run_id,chunk_id,source_type,semantic_score,lexical_score,
                      rerank_score,citation_label,selected_flag)
                    VALUES (
                      :agent_run_id,:chunk_id,:source_type,:score,:lexical,:rerank,
                      :label,true)
                    """
                ),
                {
                    "agent_run_id": agent_run_id,
                    "chunk_id": evidence_item.chunk_id,
                    "source_type": (
                        "ORACLE_DOCUMENTATION"
                        if evidence_item.source_type == "ORACLE_PUBLIC_DOCUMENTATION"
                        else "KNOWLEDGE_CHUNK"
                    ),
                    "score": evidence_item.score,
                    "lexical": evidence_item.components.lexical,
                    "rerank": evidence_item.components.rerank,
                    "label": f"knowledge:{evidence_item.chunk_id}",
                },
            )
        for ticket_item in similar:
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.retrieval_evidence(
                      agent_run_id,ticket_id,source_type,semantic_score,citation_label,selected_flag)
                    VALUES (
                      :agent_run_id,:ticket_id,'HISTORICAL_TICKET',:score,:label,true)
                    """
                ),
                {
                    "agent_run_id": agent_run_id,
                    "ticket_id": ticket_item.ticket_id,
                    "score": ticket_item.score,
                    "label": f"ticket:{ticket_item.ticket_key}",
                },
            )
        await self._session.execute(
            text(
                """
                UPDATE ai.conversation SET status_code='CLOSED',ended_at=now()
                WHERE conversation_id=:conversation_id
                """
            ),
            {"conversation_id": conversation_id},
        )
        tenant_id, user_id = _identity(context)
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT agent_run_id,provider_name,model_name,
                          agent_configuration_version_id,prompt_version_id,tool_set_version_id,
                          model_policy_version_id,retrieval_configuration_version_id
                        FROM ai.agent_run run
                        JOIN ai.conversation conversation
                          ON conversation.conversation_id=run.conversation_id
                        WHERE run.agent_run_id=:agent_run_id
                          AND run.conversation_id=:conversation_id
                          AND run.tenant_id=:tenant_id
                          AND conversation.user_id=:user_id
                        """
                    ),
                    {
                        "agent_run_id": agent_run_id,
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                    },
                )
            )
            .mappings()
            .one()
        )
        await self._audit(context, conversation_id, "AI_ANALYST_COPILOT_COMPLETED")
        return CopilotVersionCapture(
            row["agent_run_id"],
            row["provider_name"],
            row["model_name"],
            row["agent_configuration_version_id"],
            row["prompt_version_id"],
            row["tool_set_version_id"],
            row["model_policy_version_id"],
            row["retrieval_configuration_version_id"],
        )

    async def store_draft(
        self,
        context: RequestContext,
        *,
        conversation_id: UUID,
        kind: str,
        claims: list[dict[str, object]],
        citation_labels: dict[str, str],
    ) -> UUID:
        draft_id = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.message(conversation_id,role_code,content_text,content_json)
                    VALUES (
                      :conversation_id,'ASSISTANT',:content,
                      jsonb_build_object(
                        'classification','INFERENCE','draft_kind',CAST(:kind AS text),
                        'claims',CAST(:claims AS jsonb),
                        'citation_labels',CAST(:labels AS jsonb)))
                    RETURNING message_id
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "content": " ".join(str(claim.get("text", "")) for claim in claims)[:20_000],
                    "kind": kind,
                    "claims": json.dumps(claims),
                    "labels": json.dumps(citation_labels),
                },
            )
        ).scalar_one()
        await self._audit(context, conversation_id, "AI_ANALYST_COPILOT_DRAFTED")
        if not isinstance(draft_id, UUID):
            raise RuntimeError("Database returned an invalid draft identifier")
        return draft_id

    async def locked_draft(
        self, context: RequestContext, *, draft_id: UUID, ticket_id: UUID
    ) -> StoredDraft | None:
        tenant_id, user_id = _identity(context)
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT message.message_id,message.conversation_id,
                          conversation.ticket_id,message.content_json
                        FROM ai.message message
                        JOIN ai.conversation conversation
                          ON conversation.conversation_id=message.conversation_id
                        WHERE message.message_id=:draft_id
                          AND message.role_code='ASSISTANT'
                          AND message.content_json ? 'draft_kind'
                          AND conversation.conversation_type='ANALYST_COPILOT'
                          AND conversation.tenant_id=:tenant_id
                          AND conversation.user_id=:user_id
                          AND conversation.ticket_id=:ticket_id
                        FOR UPDATE OF conversation
                        """
                    ),
                    {
                        "draft_id": draft_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "ticket_id": ticket_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        content = row["content_json"]
        return StoredDraft(
            row["message_id"],
            row["conversation_id"],
            row["ticket_id"],
            str(content.get("draft_kind", "")),
            tuple(content.get("claims", ())),
            dict(content.get("citation_labels", {})),
        )

    async def draft_action_exists(self, draft_id: UUID) -> bool:
        count = (
            await self._session.execute(
                text(
                    """
                    SELECT count(*) FROM ai.message
                    WHERE role_code='SYSTEM'
                      AND content_json->>'actioned_draft_id'=CAST(:draft_id AS text)
                    """
                ),
                {"draft_id": draft_id},
            )
        ).scalar_one()
        return bool(count)

    async def record_draft_action(
        self,
        context: RequestContext,
        *,
        draft: StoredDraft,
        action: str,
        resource_type: str,
        resource_id: UUID,
        posted_body_matches_draft: bool,
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO ai.message(conversation_id,role_code,content_text,content_json)
                VALUES (
                  :conversation_id,'SYSTEM',:content,
                  jsonb_build_object(
                    'actioned_draft_id',CAST(:draft_id AS text),'action',CAST(:action AS text),
                    'resource_type',CAST(:resource_type AS text),
                    'resource_id',CAST(:resource_id AS text),
                    'analyst_edited',CAST(:edited AS boolean)))
                """
            ),
            {
                "conversation_id": draft.conversation_id,
                "content": f"Analyst {action.lower()} the copilot draft.",
                "draft_id": draft.draft_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "edited": not posted_body_matches_draft,
            },
        )
        await self._session.execute(
            text(
                """
                UPDATE ai.conversation SET status_code='CLOSED',ended_at=now()
                WHERE conversation_id=:conversation_id AND status_code='OPEN'
                """
            ),
            {"conversation_id": draft.conversation_id},
        )
        await self._audit(context, draft.conversation_id, f"AI_ANALYST_COPILOT_DRAFT_{action}")

    async def _audit(self, context: RequestContext, conversation_id: UUID, action: str) -> None:
        tenant_id, user_id = _identity(context)
        await self._session.execute(
            text(
                """
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (
                  :tenant_id,CAST(:user_id AS varchar),'USER',:action,'AI_CONVERSATION',
                  CAST(:conversation_id AS varchar),'{}'::jsonb,CAST(:correlation_id AS uuid),
                  :request_id,'API','SUCCESS')
                """
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "action": action,
                "conversation_id": conversation_id,
                "correlation_id": context.correlation_id,
                "request_id": context.request_id,
            },
        )


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise RuntimeError("Authenticated analyst copilot context is required")
    return context.tenant_id, context.user_id
