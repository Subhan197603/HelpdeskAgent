"""Tenant-scoped PostgreSQL persistence for ticket drafts and submission."""
# ruff: noqa: E501

import json
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.tickets.models import (
    PublicComment,
    TicketAnalystExtras,
    TicketDraft,
    TicketSlaRow,
    TicketView,
    WatchedTicket,
)


class TicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_draft(self, values: dict[str, Any]) -> TicketDraft:
        row = (
            await self._session.execute(
                text("""
                    INSERT INTO itsm.ticket_draft(
                        tenant_id, owner_user_id, requested_for_user_id, project_id,
                        service_node_id, request_type_id, request_type_version_id,
                        work_type_id, application_environment_id, summary, description,
                        custom_values_json, impact_code, urgency_code, priority_code,
                        priority_matrix_id, expires_at, source_conversation_id
                    ) VALUES (
                        :tenant_id, :owner_user_id, :requested_for_user_id, :project_id,
                        :service_node_id, :request_type_id, :request_type_version_id,
                        :work_type_id, :application_environment_id, :summary, :description,
                        CAST(:custom_values AS jsonb), :impact_code, :urgency_code,
                        :priority_code, :priority_matrix_id, :expires_at,
                        :source_conversation_id
                    ) RETURNING *
                """),
                values,
            )
        ).one()
        return _draft(row)

    async def draft(
        self, tenant_id: UUID, draft_id: UUID, *, lock: bool = False
    ) -> TicketDraft | None:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            await self._session.execute(
                text(
                    f"SELECT * FROM itsm.ticket_draft WHERE tenant_id=:tenant_id AND draft_id=:draft_id{suffix}"
                ),
                {"tenant_id": tenant_id, "draft_id": draft_id},
            )
        ).one_or_none()
        return _draft(row) if row is not None else None

    async def draft_for_conversation(
        self, tenant_id: UUID, user_id: UUID, conversation_id: UUID
    ) -> TicketDraft | None:
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT draft.* FROM itsm.ticket_draft draft
                    JOIN ai.conversation conversation
                      ON conversation.conversation_id=draft.source_conversation_id
                    WHERE draft.tenant_id=:tenant_id AND draft.owner_user_id=:user_id
                      AND conversation.user_id=:user_id
                      AND draft.source_conversation_id=:conversation_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                },
            )
        ).one_or_none()
        return _draft(row) if row is not None else None

    async def update_draft(
        self, draft_id: UUID, row_version: int, values: dict[str, Any]
    ) -> TicketDraft | None:
        row = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket_draft SET
                        requested_for_user_id=:requested_for_user_id,
                        service_node_id=:service_node_id,
                        application_environment_id=:application_environment_id,
                        summary=:summary, description=:description,
                        custom_values_json=CAST(:custom_values AS jsonb),
                        impact_code=:impact_code, urgency_code=:urgency_code,
                        priority_code=:priority_code, priority_matrix_id=:priority_matrix_id,
                        draft_status='DRAFT'
                    WHERE draft_id=:draft_id AND row_version=:row_version
                      AND draft_status IN ('DRAFT','READY_FOR_REVIEW')
                    RETURNING *
                """),
                {"draft_id": draft_id, "row_version": row_version, **values},
            )
        ).one_or_none()
        return _draft(row) if row is not None else None

    async def set_ready(
        self, draft_id: UUID, row_version: int, priority: tuple[str, UUID]
    ) -> TicketDraft | None:
        row = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket_draft
                    SET draft_status='READY_FOR_REVIEW', priority_code=:priority_code,
                        priority_matrix_id=:priority_matrix_id
                    WHERE draft_id=:draft_id AND row_version=:row_version
                      AND draft_status IN ('DRAFT','READY_FOR_REVIEW')
                    RETURNING *
                """),
                {
                    "draft_id": draft_id,
                    "row_version": row_version,
                    "priority_code": priority[0],
                    "priority_matrix_id": priority[1],
                },
            )
        ).one_or_none()
        return _draft(row) if row is not None else None

    async def cancel(self, draft_id: UUID, row_version: int) -> TicketDraft | None:
        row = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket_draft SET draft_status='CANCELLED'
                    WHERE draft_id=:draft_id AND row_version=:row_version
                      AND draft_status IN ('DRAFT','READY_FOR_REVIEW') RETURNING *
                """),
                {"draft_id": draft_id, "row_version": row_version},
            )
        ).one_or_none()
        return _draft(row) if row is not None else None

    async def reference_user_exists(self, tenant_id: UUID, user_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                text("""
            SELECT EXISTS(SELECT 1 FROM identity.app_user
             WHERE tenant_id=:tenant_id AND user_id=:user_id AND active_flag)
        """),
                {"tenant_id": tenant_id, "user_id": user_id},
            )
        )

    async def environment_exists(
        self, tenant_id: UUID, environment_id: UUID, service_id: UUID | None
    ) -> bool:
        return bool(
            await self._session.scalar(
                text("""
            SELECT EXISTS(SELECT 1 FROM config.application_environment
             WHERE tenant_id=:tenant_id AND application_environment_id=:environment_id
               AND active_flag AND (:service_id IS NULL OR service_node_id=:service_id))
        """),
                {
                    "tenant_id": tenant_id,
                    "environment_id": environment_id,
                    "service_id": service_id,
                },
            )
        )

    async def priority(
        self, tenant_id: UUID, project_id: UUID, service_id: UUID | None, impact: str, urgency: str
    ) -> tuple[str, UUID] | None:
        rows = (
            await self._session.execute(
                text("""
            WITH candidates AS (
              SELECT matrix.priority_code, matrix.priority_matrix_id,
                     CASE WHEN matrix.service_node_id IS NOT NULL THEN 3
                          WHEN matrix.project_id IS NOT NULL THEN 2
                          WHEN matrix.tenant_id IS NOT NULL THEN 1 ELSE 0 END specificity,
                     matrix.evaluation_order
              FROM config.priority_matrix matrix
              JOIN config.impact impact ON impact.impact_code=matrix.impact_code AND impact.active_flag
              JOIN config.urgency urgency ON urgency.urgency_code=matrix.urgency_code AND urgency.active_flag
              JOIN config.priority priority ON priority.priority_code=matrix.priority_code AND priority.active_flag
              WHERE matrix.impact_code=:impact AND matrix.urgency_code=:urgency
                AND matrix.approval_status='APPROVED'
                AND matrix.effective_from <= now()
                AND (matrix.effective_to IS NULL OR matrix.effective_to > now())
                AND (matrix.tenant_id IS NULL OR matrix.tenant_id=:tenant_id)
                AND (matrix.project_id IS NULL OR matrix.project_id=:project_id)
                AND (matrix.service_node_id IS NULL OR matrix.service_node_id=:service_id)
            ), ranked AS (
              SELECT *, dense_rank() OVER (ORDER BY specificity DESC, evaluation_order) rank
              FROM candidates
            ) SELECT priority_code, priority_matrix_id FROM ranked WHERE rank=1
        """),
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "service_id": service_id,
                    "impact": impact,
                    "urgency": urgency,
                },
            )
        ).all()
        if not rows:
            return None
        if len(rows) != 1:
            raise RuntimeError("overlapping_priority_matrix")
        return rows[0].priority_code, rows[0].priority_matrix_id

    async def workflow_initial(self, workflow_id: UUID) -> tuple[UUID, UUID] | None:
        rows = (
            await self._session.execute(
                text("""
            WITH versions AS (
              SELECT workflow_version_id,
                     count(*) OVER () version_count
              FROM config.workflow_version
              WHERE workflow_id=:workflow_id AND version_status='PUBLISHED'
                AND published_at IS NOT NULL AND published_at <= now()
                AND (effective_from IS NULL OR effective_from <= now())
                AND (effective_to IS NULL OR effective_to > now())
            )
            SELECT version.workflow_version_id, status.status_id, version.version_count
            FROM versions version
            JOIN config.workflow_status status USING (workflow_version_id)
            WHERE status.initial_flag
        """),
                {"workflow_id": workflow_id},
            )
        ).all()
        if len(rows) != 1 or rows[0].version_count != 1:
            return None
        return rows[0].workflow_version_id, rows[0].status_id

    async def claim_idempotency(
        self,
        tenant_id: UUID,
        user_id: UUID,
        key: str,
        request_hash: str,
        operation_code: str = "TICKET_DRAFT_SUBMIT",
    ) -> Any:
        await self._session.execute(
            text("""
            INSERT INTO integration.idempotency_record(
              tenant_id, principal_type, principal_id, operation_code, idempotency_key,
              request_hash, lease_expires_at, expires_at)
            VALUES (:tenant_id,'USER',:principal_id,:operation_code,:key,
                    :request_hash, now()+interval '60 seconds', now()+interval '24 hours')
            ON CONFLICT (tenant_id, operation_code, idempotency_key) DO NOTHING
        """),
            {
                "tenant_id": tenant_id,
                "principal_id": str(user_id),
                "key": key,
                "request_hash": request_hash,
                "operation_code": operation_code,
            },
        )
        return (
            await self._session.execute(
                text("""
            SELECT * FROM integration.idempotency_record
            WHERE tenant_id=:tenant_id AND operation_code=:operation_code
              AND idempotency_key=:key FOR UPDATE
        """),
                {"tenant_id": tenant_id, "key": key, "operation_code": operation_code},
            )
        ).one()

    async def create_ticket(
        self,
        draft: TicketDraft,
        workflow: tuple[UUID, UUID],
        *,
        correlation_id: str,
        request_id: str,
    ) -> tuple[UUID, str]:
        await self._session.execute(
            text(
                "SELECT set_config('app.correlation_id',:correlation_id,true), "
                "set_config('app.request_id',:request_id,true)"
            ),
            {"correlation_id": correlation_id, "request_id": request_id},
        )
        row = (
            await self._session.execute(
                text("""
            INSERT INTO itsm.ticket(
              tenant_id, project_id, request_type_id, request_type_version_id, work_type_id,
              workflow_version_id, status_id, summary, description, reporter_user_id,
              requested_for_user_id, service_node_id, impact_code, urgency_code,
              priority_code, priority_matrix_id, channel_code, application_environment_id,
              environment_code, source_conversation_id, ai_created_flag, created_by, updated_by)
            SELECT :tenant_id,:project_id,:request_type_id,:request_type_version_id,:work_type_id,
              :workflow_version_id,:status_id,:summary,:description,:owner_user_id,
              :requested_for_user_id,:service_node_id,:impact_code,:urgency_code,
              :priority_code,:priority_matrix_id,
              CASE WHEN CAST(:source_conversation_id AS uuid) IS NULL
                THEN 'PORTAL' ELSE 'CHAT' END,
              :application_environment_id,environment.environment_code,
              CAST(:source_conversation_id AS uuid),
              (CAST(:source_conversation_id AS uuid) IS NOT NULL),
              :owner_user_id,:owner_user_id
            FROM (SELECT 1) one
            LEFT JOIN config.application_environment environment
              ON environment.application_environment_id=:application_environment_id
            RETURNING ticket_id, ticket_key
        """),
                {**asdict(draft), "workflow_version_id": workflow[0], "status_id": workflow[1]},
            )
        ).one()
        return row.ticket_id, row.ticket_key

    async def persist_custom_values(
        self, ticket_id: UUID, version_id: UUID, values: dict[str, Any]
    ) -> None:
        for code, value in values.items():
            if value is None:
                continue
            definition = (
                await self._session.execute(
                    text("""
                        SELECT field.custom_field_id, field.data_type,
                          (SELECT option_id FROM config.custom_field_option
                           WHERE custom_field_id=field.custom_field_id
                             AND option_code=:option_code AND active_flag) option_id
                        FROM config.request_type_field layout
                        JOIN config.custom_field field USING(custom_field_id)
                        WHERE layout.request_type_version_id=:version_id
                          AND field.field_code=:code
                    """),
                    {"version_id": version_id, "code": code, "option_code": str(value)},
                )
            ).one()
            typed: dict[str, Any] = {
                "text_value": None,
                "number_value": None,
                "date_value": None,
                "timestamp_value": None,
                "boolean_value": None,
                "user_value": None,
                "group_value": None,
                "service_value": None,
                "option_value": None,
                "json_value": None,
            }
            if definition.data_type in {"TEXT", "LONG_TEXT"}:
                typed["text_value"] = str(value)
            elif definition.data_type == "NUMBER":
                typed["number_value"] = Decimal(str(value))
            elif definition.data_type == "DATE":
                typed["date_value"] = date.fromisoformat(str(value))
            elif definition.data_type == "TIMESTAMP":
                typed["timestamp_value"] = datetime.fromisoformat(str(value))
            elif definition.data_type == "BOOLEAN":
                typed["boolean_value"] = bool(value)
            elif definition.data_type == "USER":
                typed["user_value"] = UUID(str(value))
            elif definition.data_type == "GROUP":
                typed["group_value"] = UUID(str(value))
            elif definition.data_type in {"SERVICE", "MODULE"}:
                typed["service_value"] = UUID(str(value))
            elif definition.data_type == "SINGLE_SELECT":
                typed["option_value"] = definition.option_id
            else:
                typed["json_value"] = json.dumps(value)
            await self._session.execute(
                text("""
                    INSERT INTO itsm.ticket_custom_value(
                      ticket_id,custom_field_id,text_value,number_value,date_value,
                      timestamp_value,boolean_value,user_value,group_value,
                      service_value,option_value,json_value)
                    VALUES (:ticket_id,:custom_field_id,:text_value,:number_value,:date_value,
                      :timestamp_value,:boolean_value,:user_value,:group_value,
                      :service_value,:option_value,CAST(:json_value AS jsonb))
                """),
                {"ticket_id": ticket_id, "custom_field_id": definition.custom_field_id, **typed},
            )

    async def finish_submission(
        self,
        draft_id: UUID,
        ticket_id: UUID,
        idem_id: UUID,
        ticket_key: str,
        response: dict[str, Any],
    ) -> None:
        parameters = {
            "draft_id": draft_id,
            "ticket_id": ticket_id,
            "aggregate_id": str(ticket_id),
            "ticket_key": ticket_key,
            "idem_id": idem_id,
            "response": __import__("json").dumps(response),
        }
        await self._session.execute(
            text("""
                UPDATE itsm.ticket_draft
                SET draft_status='SUBMITTED', submitted_ticket_id=:ticket_id
                WHERE draft_id=:draft_id
            """),
            parameters,
        )
        await self._session.execute(
            text("""
            INSERT INTO integration.outbox_event(tenant_id,aggregate_type,aggregate_id,event_type,payload_json)
            SELECT tenant_id,'TICKET',CAST(:aggregate_id AS varchar),event_type,
                   jsonb_build_object('ticket_id',CAST(:aggregate_id AS varchar),
                     'ticket_key',CAST(:ticket_key AS varchar),'processing','PENDING')
            FROM itsm.ticket_draft CROSS JOIN unnest(ARRAY['ROUTE_TICKET','START_SLA','NOTIFY_TICKET_CREATED']) event_type
            WHERE draft_id=:draft_id
            """),
            parameters,
        )
        await self._session.execute(
            text("""
            UPDATE integration.idempotency_record SET processing_status='COMPLETED',
              result_resource_type='TICKET', result_resource_id=:aggregate_id,
              response_status=201, response_payload_json=CAST(:response AS jsonb),
              completed_at=now(), lease_expires_at=NULL
            WHERE idempotency_record_id=:idem_id
            """),
            parameters,
        )

    async def audit(
        self,
        draft: TicketDraft,
        action: str,
        outcome: str,
        correlation_id: str,
        request_id: str,
        *,
        actor_user_id: UUID | None = None,
    ) -> None:
        await self._session.execute(
            text("""
            INSERT INTO audit.audit_event(tenant_id,actor_id,actor_type,action_code,
              resource_type,resource_id,change_summary_json,correlation_id,request_id,
              source_channel,outcome_code)
            VALUES (:tenant_id,:actor_id,'USER',:action,'TICKET_DRAFT',:resource_id,
              '{}'::jsonb,CAST(:correlation_id AS uuid),:request_id,'PORTAL',:outcome)
        """),
            {
                "tenant_id": draft.tenant_id,
                "actor_id": str(actor_user_id or draft.owner_user_id),
                "action": action,
                "resource_id": str(draft.draft_id),
                "outcome": outcome,
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )

    async def analyst_extras(self, ticket_id: UUID) -> TicketAnalystExtras:
        row = (
            await self._session.execute(
                text("""
                    SELECT ticket.impact_code,ticket.urgency_code,
                      ticket.assignment_group_id,group_.group_name,
                      ticket.assignee_user_id,assignee.display_name AS assignee_name
                    FROM itsm.ticket AS ticket
                    LEFT JOIN identity.support_group AS group_
                      ON group_.support_group_id=ticket.assignment_group_id
                    LEFT JOIN identity.app_user AS assignee
                      ON assignee.user_id=ticket.assignee_user_id
                    WHERE ticket.ticket_id=:ticket_id
                """),
                {"ticket_id": ticket_id},
            )
        ).one()
        return TicketAnalystExtras(
            impact_code=row.impact_code,
            urgency_code=row.urgency_code,
            assignment_group_id=row.assignment_group_id,
            assignment_group_name=row.group_name,
            assignee_user_id=row.assignee_user_id,
            assignee_name=row.assignee_name,
        )

    async def ticket_slas(self, ticket_id: UUID) -> list[TicketSlaRow]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT definition.sla_code,sla.state_code,sla.target_at,
                      sla.remaining_working_seconds,sla.paused_at,sla.breached_at,
                      sla.completed_at
                    FROM itsm.ticket_sla AS sla
                    JOIN config.sla_definition AS definition
                      ON definition.sla_definition_id=sla.sla_definition_id
                    WHERE sla.ticket_id=:ticket_id
                    ORDER BY sla.target_at NULLS LAST,definition.sla_code
                """),
                {"ticket_id": ticket_id},
            )
        ).all()
        return [
            TicketSlaRow(
                definition_code=row.sla_code,
                state_code=row.state_code,
                target_at=row.target_at,
                remaining_working_seconds=row.remaining_working_seconds,
                paused_at=row.paused_at,
                breached_at=row.breached_at,
                completed_at=row.completed_at,
            )
            for row in rows
        ]

    async def analyst_ticket(
        self,
        tenant_id: UUID,
        support_group_ids: frozenset[UUID],
        *,
        key: str,
        include_all: bool,
        lock: bool = False,
    ) -> TicketView | None:
        suffix = " FOR UPDATE OF ticket" if lock else ""
        row = (
            await self._session.execute(
                text(
                    _TICKET_SELECT
                    + """
          WHERE ticket.tenant_id=:tenant_id AND ticket.ticket_key=:key
            AND (:include_all OR ticket.assignment_group_id IS NULL
                 OR ticket.assignment_group_id = ANY(CAST(:support_group_ids AS uuid[])))
        """
                    + suffix
                ),
                {
                    "tenant_id": tenant_id,
                    "key": key,
                    "include_all": include_all,
                    "support_group_ids": list(support_group_ids),
                },
            )
        ).one_or_none()
        return _ticket(row) if row is not None else None

    async def analyst_tickets(
        self,
        tenant_id: UUID,
        support_group_ids: frozenset[UUID],
        limit: int,
        before_at: datetime | None,
        before_id: UUID | None,
        *,
        include_all: bool,
    ) -> list[TicketView]:
        rows = (
            await self._session.execute(
                text(
                    _TICKET_SELECT
                    + """
          WHERE ticket.tenant_id=:tenant_id
            AND (:include_all OR ticket.assignment_group_id IS NULL
                 OR ticket.assignment_group_id = ANY(CAST(:support_group_ids AS uuid[])))
            AND (CAST(:before_at AS timestamptz) IS NULL OR
                 (ticket.created_at,ticket.ticket_id) <
                 (CAST(:before_at AS timestamptz),CAST(:before_id AS uuid)))
          ORDER BY ticket.created_at DESC,ticket.ticket_id DESC LIMIT :limit
        """
                ),
                {
                    "tenant_id": tenant_id,
                    "support_group_ids": list(support_group_ids),
                    "include_all": include_all,
                    "limit": limit,
                    "before_at": before_at,
                    "before_id": before_id,
                },
            )
        ).all()
        return [_ticket(row) for row in rows]

    async def ticket_watched(self, tenant_id: UUID, owner_user_id: UUID, ticket_id: UUID) -> bool:
        value = await self._session.scalar(
            text("""
                SELECT EXISTS (
                  SELECT 1 FROM config.analyst_ticket_watchlist
                  WHERE tenant_id=:tenant_id AND owner_user_id=:owner_user_id
                    AND ticket_id=:ticket_id
                )
            """),
            {
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "ticket_id": ticket_id,
            },
        )
        return bool(value)

    async def watch_ticket(self, tenant_id: UUID, owner_user_id: UUID, ticket_id: UUID) -> datetime:
        watched_at = await self._session.scalar(
            text("""
                WITH inserted AS (
                  INSERT INTO config.analyst_ticket_watchlist(
                    tenant_id,owner_user_id,ticket_id)
                  VALUES (:tenant_id,:owner_user_id,:ticket_id)
                  ON CONFLICT DO NOTHING
                  RETURNING watched_at
                )
                SELECT watched_at FROM inserted
                UNION ALL
                SELECT watched_at FROM config.analyst_ticket_watchlist
                WHERE tenant_id=:tenant_id AND owner_user_id=:owner_user_id
                  AND ticket_id=:ticket_id
                LIMIT 1
            """),
            {
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "ticket_id": ticket_id,
            },
        )
        assert isinstance(watched_at, datetime)
        return watched_at

    async def unwatch_ticket(self, tenant_id: UUID, owner_user_id: UUID, ticket_id: UUID) -> None:
        await self._session.execute(
            text("""
                DELETE FROM config.analyst_ticket_watchlist
                WHERE tenant_id=:tenant_id AND owner_user_id=:owner_user_id
                  AND ticket_id=:ticket_id
            """),
            {
                "tenant_id": tenant_id,
                "owner_user_id": owner_user_id,
                "ticket_id": ticket_id,
            },
        )

    async def watched_tickets(
        self,
        tenant_id: UUID,
        owner_user_id: UUID,
        support_group_ids: frozenset[UUID],
        limit: int,
        before_at: datetime | None,
        before_id: UUID | None,
        *,
        include_all: bool,
    ) -> list[WatchedTicket]:
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT watch.watchlist_id,watch.watched_at,ticket_view.*
                    FROM config.analyst_ticket_watchlist AS watch
                    JOIN LATERAL (
                    """
                    + _TICKET_SELECT
                    + """
                      WHERE ticket.ticket_id=watch.ticket_id
                        AND ticket.tenant_id=:tenant_id
                        AND (:include_all OR ticket.assignment_group_id IS NULL
                             OR ticket.assignment_group_id =
                               ANY(CAST(:support_group_ids AS uuid[])))
                    ) AS ticket_view ON true
                    WHERE watch.tenant_id=:tenant_id
                      AND watch.owner_user_id=:owner_user_id
                      AND (CAST(:before_at AS timestamptz) IS NULL OR
                           (watch.watched_at,watch.watchlist_id) <
                           (CAST(:before_at AS timestamptz),CAST(:before_id AS uuid)))
                    ORDER BY watch.watched_at DESC,watch.watchlist_id DESC
                    LIMIT :limit
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "owner_user_id": owner_user_id,
                    "support_group_ids": list(support_group_ids),
                    "include_all": include_all,
                    "before_at": before_at,
                    "before_id": before_id,
                    "limit": limit,
                },
            )
        ).all()
        return [_watched_ticket(row) for row in rows]

    async def public_comments(self, ticket_id: UUID) -> list[PublicComment]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT comment.comment_id, comment.author_user_id,
                           author.display_name AS author_name,
                           comment.comment_body, comment.created_at
                    FROM itsm.ticket_comment AS comment
                    JOIN identity.app_user AS author ON author.user_id=comment.author_user_id
                    WHERE comment.ticket_id=:ticket_id AND comment.visibility_code='PUBLIC'
                    ORDER BY comment.created_at, comment.comment_id
                """),
                {"ticket_id": ticket_id},
            )
        ).all()
        return [
            PublicComment(
                row.comment_id,
                row.author_user_id,
                row.author_name,
                row.comment_body,
                row.created_at,
            )
            for row in rows
        ]

    async def add_public_comment(
        self,
        tenant_id: UUID,
        ticket_id: UUID,
        actor_user_id: UUID,
        body: str,
        correlation_id: str,
        request_id: str,
        *,
        sla_event_type: str,
    ) -> UUID:
        if sla_event_type not in {
            "AGENT_PUBLIC_RESPONSE_ADDED",
            "CUSTOMER_COMMENT_ADDED",
        }:
            raise ValueError("Unsupported SLA comment event type")
        notification_event_type = f"NOTIFY_{sla_event_type}"
        row = (
            await self._session.execute(
                text("""
                    INSERT INTO itsm.ticket_comment(
                      ticket_id,author_user_id,visibility_code,comment_body,source_channel)
                    VALUES (:ticket_id,:actor_user_id,'PUBLIC',:body,'PORTAL')
                    RETURNING comment_id
                """),
                {"ticket_id": ticket_id, "actor_user_id": actor_user_id, "body": body},
            )
        ).one()
        await self._session.execute(
            text("""
                INSERT INTO itsm.ticket_event(
                  tenant_id,ticket_id,event_type,actor_type,actor_user_id,event_data_json)
                VALUES (:tenant_id,:ticket_id,'PUBLIC_COMMENT_ADDED','USER',:actor_user_id,
                  jsonb_build_object('comment_id',CAST(:comment_id AS varchar),
                    'visibility','PUBLIC','source_channel','PORTAL',
                    'correlation_id',CAST(:correlation_id AS varchar),
                    'request_id',CAST(:request_id AS varchar)))
            """),
            {
                "tenant_id": tenant_id,
                "ticket_id": ticket_id,
                "actor_user_id": actor_user_id,
                "comment_id": row.comment_id,
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (:tenant_id,CAST(:actor_user_id AS varchar),'USER',
                  'TICKET_PUBLIC_COMMENT_ADDED','TICKET_COMMENT',CAST(:comment_id AS varchar),
                  jsonb_build_object('ticket_id',CAST(:ticket_id AS varchar),'visibility','PUBLIC'),
                  CAST(:correlation_id AS uuid),:request_id,'PORTAL','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "ticket_id": ticket_id,
                "actor_user_id": actor_user_id,
                "comment_id": row.comment_id,
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO integration.outbox_event(
                  tenant_id,aggregate_type,aggregate_id,event_type,payload_json,
                  deduplication_key)
                SELECT :tenant_id,'TICKET',CAST(:ticket_id AS varchar),generated.event_type,
                  jsonb_build_object(
                    'ticket_id',CAST(:ticket_id AS varchar),
                    'comment_id',CAST(:comment_id AS varchar),
                    'actor_user_id',CAST(:actor_user_id AS varchar),
                    'visibility','PUBLIC'),
                  'comment:' || CAST(:comment_id AS varchar) || ':' ||
                    generated.event_type
                FROM unnest(ARRAY[
                  CAST(:event_type AS varchar),CAST(:notification_event_type AS varchar)
                ]) AS generated(event_type)
                ON CONFLICT DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "ticket_id": ticket_id,
                "comment_id": row.comment_id,
                "event_type": sla_event_type,
                "notification_event_type": notification_event_type,
                "actor_user_id": actor_user_id,
            },
        )
        return cast("UUID", row.comment_id)

    async def complete_idempotency(
        self,
        idempotency_record_id: UUID,
        resource_type: str,
        resource_id: UUID,
        response_payload: dict[str, Any],
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE integration.idempotency_record
                SET processing_status='COMPLETED',result_resource_type=:resource_type,
                    result_resource_id=CAST(:resource_id AS varchar),response_status=201,
                    response_payload_json=CAST(:response_payload AS jsonb),completed_at=now(),
                    lease_expires_at=NULL
                WHERE idempotency_record_id=:idempotency_record_id
            """),
            {
                "idempotency_record_id": idempotency_record_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "response_payload": json.dumps(response_payload),
            },
        )

    async def ticket(
        self,
        tenant_id: UUID,
        user_id: UUID,
        *,
        key: str | None = None,
        ticket_id: UUID | None = None,
        lock: bool = False,
    ) -> TicketView | None:
        suffix = " FOR UPDATE OF ticket" if lock else ""
        row = (
            await self._session.execute(
                text(
                    _TICKET_SELECT
                    + """
          WHERE ticket.tenant_id=:tenant_id
            AND (CAST(:key AS varchar) IS NULL OR ticket.ticket_key=CAST(:key AS varchar))
            AND (CAST(:ticket_id AS uuid) IS NULL OR ticket.ticket_id=CAST(:ticket_id AS uuid))
            AND (ticket.reporter_user_id=:user_id OR ticket.requested_for_user_id=:user_id)
        """
                    + suffix
                ),
                {"tenant_id": tenant_id, "user_id": user_id, "key": key, "ticket_id": ticket_id},
            )
        ).one_or_none()
        return _ticket(row) if row is not None else None

    async def tickets(
        self,
        tenant_id: UUID,
        user_id: UUID,
        limit: int,
        before_at: datetime | None,
        before_id: UUID | None,
    ) -> list[TicketView]:
        rows = (
            await self._session.execute(
                text(
                    _TICKET_SELECT
                    + """
          WHERE ticket.tenant_id=:tenant_id
            AND (ticket.reporter_user_id=:user_id OR ticket.requested_for_user_id=:user_id)
            AND (CAST(:before_at AS timestamptz) IS NULL OR
                 (ticket.created_at,ticket.ticket_id) <
                 (CAST(:before_at AS timestamptz),CAST(:before_id AS uuid)))
          ORDER BY ticket.created_at DESC,ticket.ticket_id DESC LIMIT :limit
        """
                ),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "limit": limit,
                    "before_at": before_at,
                    "before_id": before_id,
                },
            )
        ).all()
        return [_ticket(row) for row in rows]


_TICKET_SELECT = """
SELECT ticket.ticket_id,ticket.ticket_key,ticket.summary,ticket.description,
 project.project_key project_code,project.project_name,
 request_type.request_type_code,request_type.request_type_name,
 service.node_name service_name,environment.environment_name,
 work_type.work_type_code,status.status_code,
 coalesce(status.customer_visible_name,status.status_name) status_name,
 ticket.priority_code,ticket.reporter_user_id,reporter.display_name reporter_name,
 ticket.requested_for_user_id,requested.display_name requested_for_name,
 ticket.created_at,ticket.updated_at,event.created_at created_event_at,ticket.row_version
FROM itsm.ticket ticket
JOIN config.service_project project ON project.project_id=ticket.project_id
JOIN config.request_type request_type ON request_type.request_type_id=ticket.request_type_id
JOIN config.work_type work_type ON work_type.work_type_id=ticket.work_type_id
JOIN config.workflow_status status ON status.status_id=ticket.status_id
JOIN identity.app_user reporter ON reporter.user_id=ticket.reporter_user_id
LEFT JOIN identity.app_user requested ON requested.user_id=ticket.requested_for_user_id
LEFT JOIN config.service_node service ON service.service_node_id=ticket.service_node_id
LEFT JOIN config.application_environment environment
  ON environment.application_environment_id=ticket.application_environment_id
LEFT JOIN LATERAL (SELECT created_at FROM itsm.ticket_event
 WHERE ticket_id=ticket.ticket_id AND event_type='TICKET_CREATED'
 ORDER BY event_id LIMIT 1) event ON true
"""


def _draft(row: Any) -> TicketDraft:
    return TicketDraft(
        row.draft_id,
        row.tenant_id,
        row.owner_user_id,
        row.requested_for_user_id,
        row.project_id,
        row.service_node_id,
        row.request_type_id,
        row.request_type_version_id,
        row.work_type_id,
        row.application_environment_id,
        row.summary,
        row.description,
        dict(row.custom_values_json),
        row.impact_code,
        row.urgency_code,
        row.priority_code,
        row.priority_matrix_id,
        row.draft_status,
        row.submitted_ticket_id,
        row.created_at,
        row.updated_at,
        row.row_version,
        row.expires_at,
        row.source_conversation_id,
    )


def _ticket(row: Any) -> TicketView:
    return TicketView(*tuple(row))


def _watched_ticket(row: Any) -> WatchedTicket:
    values = tuple(row)
    return WatchedTicket(values[0], values[1], TicketView(*values[2:]))
