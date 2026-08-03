"""Tenant- and owner-scoped employee conversation persistence."""

import json
from dataclasses import asdict
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.context import RequestContext
from apps.api.app.employee_agent.models import (
    AgentAnswer,
    AgentState,
    Conversation,
    StartedTurn,
)
from apps.api.app.retrieval.models import RetrievalEvidence


class ConversationNotFoundError(LookupError):
    pass


class ActiveTurnError(RuntimeError):
    pass


class ConversationClosedError(RuntimeError):
    pass


class FeedbackConflictError(RuntimeError):
    pass


class EmployeeAgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, context: RequestContext) -> Conversation:
        tenant_id, user_id = _identity(context)
        row = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.conversation(
                      tenant_id,conversation_type,user_id,status_code,metadata_json)
                    VALUES (
                      :tenant_id,'EMPLOYEE_HELPDESK',:user_id,'OPEN',
                      jsonb_build_object('state','NEW'))
                    RETURNING conversation_id
                    """
                ),
                {"tenant_id": tenant_id, "user_id": user_id},
            )
        ).scalar_one()
        if not isinstance(row, UUID):
            raise RuntimeError("Database returned an invalid conversation identifier")
        await self._audit(context, "AI_CONVERSATION_CREATED", row, "SUCCESS")
        return Conversation(row, AgentState.NEW)

    async def owned(self, context: RequestContext, conversation_id: UUID) -> Conversation:
        tenant_id, user_id = _identity(context)
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT conversation_id,COALESCE(metadata_json->>'state','NEW') AS state
                        FROM ai.conversation
                        WHERE conversation_id=:conversation_id AND tenant_id=:tenant_id
                          AND user_id=:user_id AND conversation_type='EMPLOYEE_HELPDESK'
                          AND status_code='OPEN'
                        """
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ConversationNotFoundError
        return Conversation(row["conversation_id"], AgentState(row["state"]))

    async def start_turn(
        self,
        context: RequestContext,
        conversation_id: UUID,
        content: str,
        *,
        history_limit: int,
    ) -> StartedTurn:
        tenant_id, user_id = _identity(context)
        conversation = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT COALESCE(metadata_json->>'state','NEW') AS state
                        FROM ai.conversation
                        WHERE conversation_id=:conversation_id AND tenant_id=:tenant_id
                          AND user_id=:user_id AND conversation_type='EMPLOYEE_HELPDESK'
                          AND status_code='OPEN'
                        FOR UPDATE
                        """
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if conversation is None:
            raise ConversationNotFoundError
        current = AgentState(conversation["state"])
        if current in {
            AgentState.RESOLVED_WITHOUT_TICKET,
            AgentState.TICKET_SUBMITTED,
            AgentState.TICKET_DRAFT_READY,
            AgentState.AWAITING_USER_CONFIRMATION,
        }:
            raise ConversationClosedError
        active = (
            await self._session.execute(
                text(
                    """
                    SELECT 1 FROM ai.conversation_turn
                    WHERE conversation_id=:conversation_id AND turn_status='ACTIVE'
                    """
                ),
                {"conversation_id": conversation_id},
            )
        ).scalar_one_or_none()
        if active is not None:
            raise ActiveTurnError
        message_id = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.message(conversation_id,role_code,content_text)
                    VALUES (:conversation_id,'USER',:content) RETURNING message_id
                    """
                ),
                {"conversation_id": conversation_id, "content": content},
            )
        ).scalar_one()
        turn_id = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.conversation_turn(
                      tenant_id,conversation_id,user_message_id,state_code,turn_status)
                    VALUES (
                      :tenant_id,:conversation_id,:message_id,'COLLECTING_INFORMATION','ACTIVE')
                    RETURNING conversation_turn_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                },
            )
        ).scalar_one()
        await self._session.execute(
            text(
                """
                UPDATE ai.conversation
                SET metadata_json=jsonb_set(metadata_json,'{state}',
                  to_jsonb('COLLECTING_INFORMATION'::text),true)
                WHERE conversation_id=:conversation_id
                """
            ),
            {"conversation_id": conversation_id},
        )
        history_rows = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT role_code,content_text FROM ai.message
                        WHERE conversation_id=:conversation_id AND content_text IS NOT NULL
                        ORDER BY created_at DESC,message_id DESC LIMIT :history_limit
                        """
                    ),
                    {"conversation_id": conversation_id, "history_limit": history_limit},
                )
            )
            .mappings()
            .all()
        )
        if not isinstance(message_id, UUID) or not isinstance(turn_id, UUID):
            raise RuntimeError("Database returned an invalid turn identifier")
        history = tuple(
            {"role": _role(row["role_code"]), "content": row["content_text"]}
            for row in reversed(history_rows)
        )
        return StartedTurn(turn_id, message_id, history)

    async def finish_turn(
        self,
        context: RequestContext,
        conversation_id: UUID,
        turn_id: UUID,
        answer: AgentAnswer,
    ) -> UUID:
        tenant_id, user_id = _identity(context)
        assistant_message_id = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.message(conversation_id,role_code,content_text,content_json)
                    SELECT :conversation_id,'ASSISTANT',:content,CAST(:content_json AS jsonb)
                    WHERE EXISTS (
                      SELECT 1 FROM ai.conversation WHERE conversation_id=:conversation_id
                        AND tenant_id=:tenant_id AND user_id=:user_id)
                    RETURNING message_id
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "content": answer.text,
                    "content_json": json.dumps(
                        {
                            "outcome": answer.outcome.value,
                            "citations": [asdict(citation) for citation in answer.citations],
                        },
                        default=str,
                    ),
                },
            )
        ).scalar_one_or_none()
        if not isinstance(assistant_message_id, UUID):
            raise ConversationNotFoundError
        update_result = cast(
            CursorResult[Any],
            await self._session.execute(
                text(
                    """
                    UPDATE ai.conversation_turn SET
                      assistant_message_id=:assistant_message_id,
                      agent_run_id=:agent_run_id,
                      state_code=:state_code,
                      turn_status='COMPLETED',outcome_code=:outcome_code,
                      retrieval_configuration_version_id=:retrieval_version,
                      completed_at=now()
                    WHERE conversation_turn_id=:turn_id AND tenant_id=:tenant_id
                      AND conversation_id=:conversation_id AND turn_status='ACTIVE'
                    """
                ),
                {
                    "assistant_message_id": assistant_message_id,
                    "agent_run_id": answer.agent_run_id,
                    "state_code": answer.state.value,
                    "outcome_code": answer.outcome.value,
                    "retrieval_version": answer.retrieval_configuration_version_id,
                    "turn_id": turn_id,
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                },
            ),
        )
        if update_result.rowcount != 1:
            raise ActiveTurnError
        await self._session.execute(
            text(
                """
                UPDATE ai.conversation SET metadata_json=jsonb_set(
                  metadata_json,'{state}',to_jsonb(CAST(:state_code AS text)),true)
                WHERE conversation_id=:conversation_id AND tenant_id=:tenant_id
                  AND user_id=:user_id
                """
            ),
            {
                "state_code": answer.state.value,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
            },
        )
        if answer.agent_run_id is not None:
            for evidence in answer.evidence:
                await self._append_evidence(answer.agent_run_id, evidence)
        await self._audit(context, "AI_CONVERSATION_TURN_COMPLETED", turn_id, "SUCCESS")
        return assistant_message_id

    async def cancel_turn(
        self, context: RequestContext, conversation_id: UUID, turn_id: UUID
    ) -> None:
        tenant_id, user_id = _identity(context)
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                text(
                    """
                UPDATE ai.conversation_turn t SET turn_status='CANCELLED',
                  cancellation_requested_at=COALESCE(cancellation_requested_at,now()),
                  completed_at=now(),safe_failure_code='CLIENT_CANCELLED'
                FROM ai.conversation c
                WHERE t.conversation_turn_id=:turn_id AND t.conversation_id=:conversation_id
                  AND t.tenant_id=:tenant_id AND t.turn_status='ACTIVE'
                  AND c.conversation_id=t.conversation_id AND c.user_id=:user_id
                    """
                ),
                {
                    "turn_id": turn_id,
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            ),
        )
        if result.rowcount != 1:
            raise ConversationNotFoundError
        await self._audit(context, "AI_CONVERSATION_TURN_CANCELLED", turn_id, "SUCCESS")

    async def turn_active(
        self, context: RequestContext, conversation_id: UUID, turn_id: UUID
    ) -> bool:
        tenant_id, user_id = _identity(context)
        value = (
            await self._session.execute(
                text(
                    """
                    SELECT 1 FROM ai.conversation_turn t
                    JOIN ai.conversation c ON c.conversation_id=t.conversation_id
                    WHERE t.conversation_turn_id=:turn_id
                      AND t.conversation_id=:conversation_id AND t.tenant_id=:tenant_id
                      AND t.turn_status='ACTIVE' AND c.user_id=:user_id
                    """
                ),
                {
                    "turn_id": turn_id,
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                },
            )
        ).scalar_one_or_none()
        return value is not None

    async def record_resolution_feedback(
        self,
        context: RequestContext,
        conversation_id: UUID,
        *,
        helpful: bool,
        resolved: bool,
        comment: str | None,
    ) -> AgentState:
        tenant_id, user_id = _identity(context)
        conversation = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT COALESCE(metadata_json->>'state','NEW') state
                        FROM ai.conversation
                        WHERE conversation_id=:conversation_id AND tenant_id=:tenant_id
                          AND user_id=:user_id AND conversation_type='EMPLOYEE_HELPDESK'
                        FOR UPDATE
                        """
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if conversation is None:
            raise ConversationNotFoundError
        current = AgentState(conversation["state"])
        allowed = {
            AgentState.AWAITING_RESOLUTION_CONFIRMATION,
            AgentState.COLLECTING_TICKET_FIELDS,
            AgentState.AWAITING_USER_CONFIRMATION,
            AgentState.RESOLVED_WITHOUT_TICKET,
        }
        if current not in allowed:
            raise ConversationClosedError
        if resolved and current is AgentState.COLLECTING_TICKET_FIELDS:
            raise ConversationClosedError
        target = (
            AgentState.RESOLVED_WITHOUT_TICKET if resolved else AgentState.COLLECTING_TICKET_FIELDS
        )
        run_id = await self._session.scalar(
            text(
                """
                SELECT agent_run_id FROM ai.conversation_turn
                WHERE conversation_id=:conversation_id AND agent_run_id IS NOT NULL
                ORDER BY completed_at DESC NULLS LAST,started_at DESC LIMIT 1
                """
            ),
            {"conversation_id": conversation_id},
        )
        inserted = (
            await self._session.execute(
                text(
                    """
                    INSERT INTO ai.feedback(
                      tenant_id,conversation_id,agent_run_id,user_id,feedback_type,
                      rating_value,comment_text,resolved_issue_flag)
                    VALUES (
                      :tenant_id,:conversation_id,:agent_run_id,:user_id,'RESOLUTION_OUTCOME',
                      :rating_value,:comment,:resolved)
                    ON CONFLICT (conversation_id,user_id,feedback_type)
                      WHERE feedback_type='RESOLUTION_OUTCOME' DO NOTHING
                    RETURNING feedback_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "agent_run_id": run_id,
                    "user_id": user_id,
                    "rating_value": 5 if helpful else 1,
                    "comment": comment,
                    "resolved": resolved,
                },
            )
        ).scalar_one_or_none()
        if inserted is None:
            existing = (
                (
                    await self._session.execute(
                        text(
                            """
                            SELECT rating_value,comment_text,resolved_issue_flag FROM ai.feedback
                            WHERE conversation_id=:conversation_id AND user_id=:user_id
                              AND feedback_type='RESOLUTION_OUTCOME'
                            """
                        ),
                        {"conversation_id": conversation_id, "user_id": user_id},
                    )
                )
                .mappings()
                .one()
            )
            if (
                existing["rating_value"] != (5 if helpful else 1)
                or existing["comment_text"] != comment
                or existing["resolved_issue_flag"] != resolved
            ):
                raise FeedbackConflictError
        await self._session.execute(
            text(
                """
                UPDATE ai.conversation SET metadata_json=jsonb_set(
                  metadata_json,'{state}',to_jsonb(CAST(:state AS text)),true)
                WHERE conversation_id=:conversation_id
                """
            ),
            {"conversation_id": conversation_id, "state": target.value},
        )
        await self._audit(context, "AI_RESOLUTION_FEEDBACK_RECORDED", conversation_id, "SUCCESS")
        return target

    async def user_message_summary(
        self, context: RequestContext, conversation_id: UUID, *, limit: int
    ) -> tuple[str, ...]:
        tenant_id, user_id = _identity(context)
        rows = (
            (
                await self._session.execute(
                    text(
                        """
                    SELECT message.content_text FROM ai.message message
                    JOIN ai.conversation conversation USING(conversation_id)
                    WHERE message.conversation_id=:conversation_id
                      AND conversation.tenant_id=:tenant_id AND conversation.user_id=:user_id
                      AND message.role_code='USER' AND message.content_text IS NOT NULL
                    ORDER BY message.created_at DESC,message.message_id DESC LIMIT :limit
                    """
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "limit": limit,
                    },
                )
            )
            .scalars()
            .all()
        )
        return tuple(reversed(rows))

    async def link_draft(
        self, context: RequestContext, conversation_id: UUID, draft_id: UUID
    ) -> None:
        tenant_id, user_id = _identity(context)
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                text(
                    """
                    UPDATE ai.conversation conversation SET metadata_json=jsonb_set(
                      jsonb_set(conversation.metadata_json,'{state}',
                        to_jsonb('AWAITING_USER_CONFIRMATION'::text),true),
                      '{ticket_draft_id}',to_jsonb(CAST(:draft_id AS text)),true)
                    FROM itsm.ticket_draft draft
                    WHERE conversation.conversation_id=:conversation_id
                      AND conversation.tenant_id=:tenant_id AND conversation.user_id=:user_id
                      AND draft.draft_id=:draft_id AND draft.tenant_id=:tenant_id
                      AND draft.owner_user_id=:user_id
                      AND draft.source_conversation_id=conversation.conversation_id
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "draft_id": draft_id,
                },
            ),
        )
        if result.rowcount != 1:
            raise ConversationNotFoundError
        await self._audit(context, "AI_TICKET_DRAFT_LINKED", conversation_id, "SUCCESS")

    async def linked_draft(
        self, context: RequestContext, conversation_id: UUID
    ) -> tuple[UUID, AgentState]:
        tenant_id, user_id = _identity(context)
        row = (
            (
                await self._session.execute(
                    text(
                        """
                        SELECT draft.draft_id,conversation.metadata_json->>'state' state
                        FROM ai.conversation conversation
                        JOIN itsm.ticket_draft draft
                          ON draft.source_conversation_id=conversation.conversation_id
                        WHERE conversation.conversation_id=:conversation_id
                          AND conversation.tenant_id=:tenant_id AND conversation.user_id=:user_id
                          AND draft.owner_user_id=:user_id
                        """
                    ),
                    {
                        "conversation_id": conversation_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ConversationNotFoundError
        return row["draft_id"], AgentState(row["state"])

    async def link_ticket(
        self,
        context: RequestContext,
        conversation_id: UUID,
        draft_id: UUID,
        ticket_id: UUID,
    ) -> None:
        tenant_id, user_id = _identity(context)
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                text(
                    """
                    UPDATE ai.conversation conversation SET ticket_id=:ticket_id,
                      metadata_json=jsonb_set(conversation.metadata_json,'{state}',
                        to_jsonb('TICKET_SUBMITTED'::text),true)
                    FROM itsm.ticket_draft draft,itsm.ticket ticket
                    WHERE conversation.conversation_id=:conversation_id
                      AND conversation.tenant_id=:tenant_id AND conversation.user_id=:user_id
                      AND draft.draft_id=:draft_id
                      AND draft.source_conversation_id=conversation.conversation_id
                      AND draft.submitted_ticket_id=:ticket_id
                      AND ticket.ticket_id=:ticket_id
                      AND ticket.source_conversation_id=conversation.conversation_id
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "draft_id": draft_id,
                    "ticket_id": ticket_id,
                },
            ),
        )
        if result.rowcount != 1:
            raise ConversationNotFoundError
        await self._audit(context, "AI_CONFIRMED_TICKET_LINKED", ticket_id, "SUCCESS")

    async def fail_turn(
        self,
        context: RequestContext,
        conversation_id: UUID,
        turn_id: UUID,
        failure_code: str,
    ) -> None:
        tenant_id, user_id = _identity(context)
        await self._session.execute(
            text(
                """
                UPDATE ai.conversation_turn t SET turn_status='FAILED',completed_at=now(),
                  safe_failure_code=:failure_code
                FROM ai.conversation c
                WHERE t.conversation_turn_id=:turn_id AND t.conversation_id=:conversation_id
                  AND t.tenant_id=:tenant_id AND t.turn_status='ACTIVE'
                  AND c.conversation_id=t.conversation_id AND c.user_id=:user_id
                """
            ),
            {
                "turn_id": turn_id,
                "conversation_id": conversation_id,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "failure_code": failure_code[:100],
            },
        )
        await self._audit(context, "AI_CONVERSATION_TURN_FAILED", turn_id, "FAILED")

    async def _append_evidence(self, agent_run_id: UUID, item: RetrievalEvidence) -> None:
        source_type = (
            "ORACLE_DOCUMENTATION"
            if item.source_type == "ORACLE_PUBLIC_DOCUMENTATION"
            else "KNOWLEDGE_CHUNK"
        )
        await self._session.execute(
            text(
                """
                INSERT INTO ai.retrieval_evidence(
                  agent_run_id,chunk_id,source_type,semantic_score,lexical_score,
                  rerank_score,citation_label,selected_flag)
                VALUES (
                  :agent_run_id,:chunk_id,:source_type,:semantic_score,:lexical_score,
                  :rerank_score,:citation_label,true)
                """
            ),
            {
                "agent_run_id": agent_run_id,
                "chunk_id": item.chunk_id,
                "source_type": source_type,
                "semantic_score": item.components.vector,
                "lexical_score": item.components.lexical,
                "rerank_score": item.components.rerank,
                "citation_label": item.document_title[:300],
            },
        )

    async def _audit(
        self, context: RequestContext, action: str, resource_id: UUID, outcome: str
    ) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (
                  :tenant_id,CAST(:actor_id AS varchar),'USER',:action,'AI_CONVERSATION',
                  CAST(:resource_id AS varchar),'{}'::jsonb,CAST(:correlation_id AS uuid),
                  :request_id,'ASSISTANT',:outcome)
                """
            ),
            {
                "tenant_id": context.tenant_id,
                "actor_id": context.user_id,
                "action": action,
                "resource_id": resource_id,
                "correlation_id": context.correlation_id,
                "request_id": context.request_id,
                "outcome": outcome,
            },
        )


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise ConversationNotFoundError
    return context.tenant_id, context.user_id


def _role(value: str) -> str:
    return {"USER": "user", "ASSISTANT": "assistant"}.get(value, "system")
