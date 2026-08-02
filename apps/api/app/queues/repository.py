"""Read-model persistence for queues and immutable ticket activity."""

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.queues.models import ActivityItem, QueueDefinition, QueueTicket


class QueueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def definitions(
        self, tenant_id: UUID, queue_id: UUID | None = None
    ) -> list[QueueDefinition]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT queue.queue_id,version.queue_definition_version_id,
                      queue.tenant_id,queue.project_id,project.project_key,
                      queue.queue_name,queue.description,version.filter_json,
                      version.sort_json,version.columns_json,version.visibility_type,
                      version.owner_group_id,queue.display_order
                    FROM config.queue_definition AS queue
                    JOIN config.queue_definition_version AS version
                      ON version.queue_id=queue.queue_id
                    JOIN config.service_project AS project
                      ON project.project_id=queue.project_id
                     AND project.tenant_id=queue.tenant_id AND project.active_flag
                    WHERE queue.tenant_id=:tenant_id AND queue.active_flag
                      AND (CAST(:queue_id AS uuid) IS NULL OR queue.queue_id=:queue_id)
                      AND version.version_status='PUBLISHED'
                      AND version.published_at IS NOT NULL AND version.published_at <= now()
                      AND (version.effective_from IS NULL OR version.effective_from <= now())
                      AND (version.effective_to IS NULL OR version.effective_to > now())
                    ORDER BY queue.display_order,queue.queue_name,version.version_number
                """),
                {"tenant_id": tenant_id, "queue_id": queue_id},
            )
        ).all()
        return [QueueDefinition(*tuple(row)) for row in rows]

    async def tickets(
        self,
        queue: QueueDefinition,
        predicate_sql: str,
        parameters: dict[str, Any],
        *,
        support_group_ids: frozenset[UUID],
        include_all: bool,
        limit: int,
    ) -> list[QueueTicket]:
        rows = (
            await self._session.execute(
                text(
                    """
                    SELECT ticket.ticket_id,ticket.ticket_key,ticket.summary,
                      project.project_key,ticket.priority_code,status.status_code,
                      status.status_name,reporter.display_name,
                      ticket.assignment_group_id,group_.group_name,
                      ticket.assignee_user_id,assignee.display_name,
                      ticket.created_at,ticket.updated_at,
                      first_response.target_at,resolution.target_at
                    FROM itsm.ticket AS ticket
                    JOIN config.service_project AS project ON project.project_id=ticket.project_id
                    JOIN config.workflow_status AS status ON status.status_id=ticket.status_id
                    JOIN identity.app_user AS reporter ON reporter.user_id=ticket.reporter_user_id
                     AND reporter.tenant_id=ticket.tenant_id
                    LEFT JOIN identity.support_group AS group_
                      ON group_.support_group_id=ticket.assignment_group_id
                     AND group_.tenant_id=ticket.tenant_id
                    LEFT JOIN identity.app_user AS assignee
                      ON assignee.user_id=ticket.assignee_user_id
                     AND assignee.tenant_id=ticket.tenant_id
                    LEFT JOIN LATERAL (
                      SELECT sla.target_at FROM itsm.ticket_sla AS sla
                      JOIN config.sla_definition AS definition
                        ON definition.sla_definition_id=sla.sla_definition_id
                      WHERE sla.ticket_id=ticket.ticket_id
                        AND definition.metric_code='TIME_TO_FIRST_RESPONSE'
                      ORDER BY sla.target_at LIMIT 1
                    ) AS first_response ON true
                    LEFT JOIN LATERAL (
                      SELECT sla.target_at FROM itsm.ticket_sla AS sla
                      JOIN config.sla_definition AS definition
                        ON definition.sla_definition_id=sla.sla_definition_id
                      WHERE sla.ticket_id=ticket.ticket_id
                        AND definition.metric_code='TIME_TO_RESOLUTION'
                      ORDER BY sla.target_at LIMIT 1
                    ) AS resolution ON true
                    WHERE ticket.tenant_id=:tenant_id AND ticket.project_id=:project_id
                      AND (:include_all OR ticket.assignment_group_id IS NULL OR
                        ticket.assignment_group_id=ANY(CAST(:support_group_ids AS uuid[])))
                      AND """
                    + predicate_sql
                    + """
                    ORDER BY ticket.created_at DESC,ticket.ticket_id DESC
                    LIMIT :limit
                    """
                ),
                {
                    **parameters,
                    "tenant_id": queue.tenant_id,
                    "project_id": queue.project_id,
                    "support_group_ids": list(support_group_ids),
                    "include_all": include_all,
                    "limit": limit,
                },
            )
        ).all()
        return [QueueTicket(*tuple(row)) for row in rows]

    async def timeline(self, ticket_id: UUID, *, include_internal: bool) -> list[ActivityItem]:
        visibility = "TRUE" if include_internal else "classification='PUBLIC'"
        rows = (
            await self._session.execute(
                text(
                    """
                    WITH activity AS (
                      SELECT 'event:' || event.event_id AS item_id,event.event_type AS item_type,
                        CASE
                          WHEN event.event_type IN ('TICKET_CREATED','STATUS_CHANGED')
                            THEN 'PUBLIC'
                          WHEN event.actor_type='SYSTEM' THEN 'SYSTEM'
                          ELSE 'INTERNAL'
                        END AS classification,event.actor_user_id,
                        actor.display_name AS actor_name,NULL::text AS body,
                        event.event_data_json AS details,event.created_at,
                        event.event_id AS stable_order
                      FROM itsm.ticket_event AS event
                      LEFT JOIN identity.app_user AS actor ON actor.user_id=event.actor_user_id
                       AND actor.tenant_id=event.tenant_id
                      WHERE event.ticket_id=:ticket_id
                        AND event.event_type NOT IN (
                          'PUBLIC_COMMENT_ADDED','INTERNAL_COMMENT_ADDED'
                        )
                      UNION ALL
                      SELECT 'comment:' || comment.comment_id,'COMMENT',
                        comment.visibility_code,comment.author_user_id,actor.display_name,
                        comment.comment_body,
                        jsonb_build_object('source_channel',comment.source_channel),
                        comment.created_at,0
                      FROM itsm.ticket_comment AS comment
                      JOIN itsm.ticket AS comment_ticket
                        ON comment_ticket.ticket_id=comment.ticket_id
                      LEFT JOIN identity.app_user AS actor ON actor.user_id=comment.author_user_id
                       AND actor.tenant_id=comment_ticket.tenant_id
                      WHERE comment.ticket_id=:ticket_id
                        AND comment.visibility_code IN ('PUBLIC','INTERNAL')
                    )
                    SELECT item_id,item_type,classification,actor_user_id,actor_name,body,
                      details,created_at FROM activity WHERE """
                    + visibility
                    + """
                    ORDER BY created_at,stable_order,item_id
                    LIMIT 500
                    """
                ),
                {"ticket_id": ticket_id},
            )
        ).all()
        return [
            ActivityItem(
                row.item_id,
                row.item_type,
                row.classification,
                row.actor_user_id,
                row.actor_name,
                row.body,
                dict(row.details or {}),
                row.created_at,
            )
            for row in rows
        ]

    async def add_comment(
        self,
        tenant_id: UUID,
        ticket_id: UUID,
        actor_user_id: UUID,
        visibility: str,
        body: str,
        correlation_id: str,
        request_id: str,
    ) -> UUID:
        row = (
            await self._session.execute(
                text("""
                    INSERT INTO itsm.ticket_comment(
                      ticket_id,author_user_id,visibility_code,comment_body,source_channel)
                    VALUES (:ticket_id,:actor_user_id,:visibility,:body,'API')
                    RETURNING comment_id
                """),
                {
                    "ticket_id": ticket_id,
                    "actor_user_id": actor_user_id,
                    "visibility": visibility,
                    "body": body,
                },
            )
        ).one()
        event_type = f"{visibility}_COMMENT_ADDED"
        payload = {
            "comment_id": str(row.comment_id),
            "visibility": visibility,
            "source_channel": "API",
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
        await self._session.execute(
            text("""
                INSERT INTO itsm.ticket_event(
                  tenant_id,ticket_id,event_type,actor_type,actor_user_id,event_data_json)
                VALUES (:tenant_id,:ticket_id,:event_type,'AGENT',:actor_user_id,
                  CAST(:payload AS jsonb))
            """),
            {
                "tenant_id": tenant_id,
                "ticket_id": ticket_id,
                "event_type": event_type,
                "actor_user_id": actor_user_id,
                "payload": json.dumps(payload),
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (:tenant_id,CAST(:actor_user_id AS varchar),'USER',:action_code,
                  'TICKET_COMMENT',CAST(:comment_id AS varchar),
                  jsonb_build_object('ticket_id',CAST(:ticket_id AS varchar),
                    'visibility',CAST(:visibility AS text)),CAST(:correlation_id AS uuid),
                  :request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "ticket_id": ticket_id,
                "actor_user_id": actor_user_id,
                "comment_id": row.comment_id,
                "visibility": visibility,
                "action_code": f"TICKET_{visibility}_COMMENT_ADDED",
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
        return cast("UUID", row.comment_id)

    async def comment(self, tenant_id: UUID, comment_id: UUID) -> ActivityItem | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT 'comment:' || comment.comment_id AS item_id,'COMMENT' item_type,
                      comment.visibility_code classification,comment.author_user_id,
                      actor.display_name actor_name,comment.comment_body body,
                      jsonb_build_object('source_channel',comment.source_channel) details,
                      comment.created_at
                    FROM itsm.ticket_comment AS comment
                    JOIN itsm.ticket AS ticket ON ticket.ticket_id=comment.ticket_id
                    LEFT JOIN identity.app_user AS actor ON actor.user_id=comment.author_user_id
                     AND actor.tenant_id=ticket.tenant_id
                    WHERE ticket.tenant_id=:tenant_id AND comment.comment_id=:comment_id
                      AND comment.visibility_code IN ('PUBLIC','INTERNAL')
                """),
                {"tenant_id": tenant_id, "comment_id": comment_id},
            )
        ).one_or_none()
        return ActivityItem(*tuple(row)) if row is not None else None
