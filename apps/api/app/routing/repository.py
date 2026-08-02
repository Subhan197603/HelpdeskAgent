"""Transactional PostgreSQL persistence for routing and assignment."""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.routing.models import AssignmentResult, RoutingRuleVersion, RoutingTicket


class RoutingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ticket(
        self,
        tenant_id: UUID,
        ticket_key: str,
        support_group_ids: frozenset[UUID],
        *,
        include_all: bool,
        lock: bool,
    ) -> RoutingTicket | None:
        lock_clause = " FOR UPDATE OF ticket" if lock else ""
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT ticket.ticket_id,ticket.tenant_id,ticket.ticket_key,
                      ticket.project_id,project.project_key,
                      ticket.service_node_id,node.node_code,
                      CASE WHEN node.parent_node_id IS NULL THEN node.node_code
                           ELSE parent.node_code END AS service_code,
                      CASE WHEN node.parent_node_id IS NULL THEN NULL
                           ELSE node.node_code END AS module_code,
                      environment.environment_code,work_type.work_type_code,
                      ticket.priority_code,status.status_code,ticket.summary,ticket.description,
                      ticket.assignment_group_id,ticket.assignee_user_id,ticket.row_version
                    FROM itsm.ticket AS ticket
                    JOIN config.service_project AS project ON project.project_id=ticket.project_id
                    JOIN config.work_type AS work_type ON work_type.work_type_id=ticket.work_type_id
                    JOIN config.workflow_status AS status ON status.status_id=ticket.status_id
                    LEFT JOIN config.service_node AS node
                      ON node.service_node_id=ticket.service_node_id
                    LEFT JOIN config.service_node AS parent
                      ON parent.service_node_id=node.parent_node_id
                    LEFT JOIN config.application_environment AS environment
                      ON environment.application_environment_id=ticket.application_environment_id
                    WHERE ticket.tenant_id=:tenant_id AND ticket.ticket_key=:ticket_key
                      AND (:include_all OR ticket.assignment_group_id IS NULL
                        OR ticket.assignment_group_id=ANY(CAST(:support_group_ids AS uuid[])))
                    """
                    + lock_clause
                ),
                {
                    "tenant_id": tenant_id,
                    "ticket_key": ticket_key,
                    "include_all": include_all,
                    "support_group_ids": list(support_group_ids),
                },
            )
        ).one_or_none()
        if row is None:
            return None
        custom_fields = await self._custom_fields(row.ticket_id)
        return RoutingTicket(
            ticket_id=row.ticket_id,
            tenant_id=row.tenant_id,
            ticket_key=row.ticket_key,
            project_id=row.project_id,
            project_code=row.project_key,
            service_node_id=row.service_node_id,
            service_node_code=row.node_code,
            service_code=row.service_code,
            module_code=row.module_code,
            environment_code=row.environment_code,
            work_type_code=row.work_type_code,
            priority_code=row.priority_code,
            status_code=row.status_code,
            summary=row.summary,
            description=row.description,
            assignment_group_id=row.assignment_group_id,
            assignee_user_id=row.assignee_user_id,
            row_version=row.row_version,
            custom_fields=custom_fields,
        )

    async def _custom_fields(self, ticket_id: UUID) -> dict[str, Any]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT field.field_code,value.text_value,value.number_value,
                      value.date_value,value.timestamp_value,value.boolean_value,
                      value.user_value,value.group_value,value.service_value,
                      option.option_code,value.json_value
                    FROM itsm.ticket_custom_value AS value
                    JOIN config.custom_field AS field
                      ON field.custom_field_id=value.custom_field_id
                    LEFT JOIN config.custom_field_option AS option
                      ON option.option_id=value.option_value
                    WHERE value.ticket_id=:ticket_id
                """),
                {"ticket_id": ticket_id},
            )
        ).all()
        result: dict[str, Any] = {}
        for row in rows:
            values = tuple(row)[1:]
            result[row.field_code] = next(
                (_json_value(value) for value in values if value is not None), None
            )
        return result

    async def rule_versions(self, ticket: RoutingTicket) -> list[RoutingRuleVersion]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT rule.routing_rule_id,version.routing_rule_version_id,
                      version.version_number,version.rule_priority,version.condition_json,
                      version.assignment_group_id,version.assignment_method,
                      version.assignee_user_id,version.effective_from,group_.group_code
                    FROM config.routing_rule AS rule
                    JOIN config.routing_rule_version AS version
                      ON version.routing_rule_id=rule.routing_rule_id
                    JOIN identity.support_group AS group_
                      ON group_.support_group_id=version.assignment_group_id
                     AND group_.tenant_id=rule.tenant_id AND group_.active_flag
                    WHERE rule.tenant_id=:tenant_id AND rule.project_id=:project_id
                      AND rule.active_flag
                      AND (rule.effective_start_at IS NULL OR rule.effective_start_at <= now())
                      AND (rule.effective_end_at IS NULL OR rule.effective_end_at > now())
                      AND version.version_status='PUBLISHED'
                      AND version.published_at IS NOT NULL AND version.published_at <= now()
                      AND (version.effective_from IS NULL OR version.effective_from <= now())
                      AND (version.effective_to IS NULL OR version.effective_to > now())
                """),
                {"tenant_id": ticket.tenant_id, "project_id": ticket.project_id},
            )
        ).all()
        return [RoutingRuleVersion(*tuple(row)) for row in rows]

    async def target(
        self, tenant_id: UUID, group_id: UUID, assignee_id: UUID | None
    ) -> tuple[str, UUID | None] | None:
        group_code = await self._session.scalar(
            text("""
                SELECT group_code FROM identity.support_group
                WHERE tenant_id=:tenant_id AND support_group_id=:group_id AND active_flag
            """),
            {"tenant_id": tenant_id, "group_id": group_id},
        )
        if group_code is None:
            return None
        if assignee_id is None:
            return str(group_code), None
        valid = await self._session.scalar(
            text("""
                SELECT EXISTS(
                  SELECT 1 FROM identity.support_group_member AS member
                  JOIN identity.app_user AS user_ ON user_.user_id=member.user_id
                  WHERE member.support_group_id=:group_id AND member.user_id=:assignee_id
                    AND member.active_flag AND user_.tenant_id=:tenant_id AND user_.active_flag)
            """),
            {"tenant_id": tenant_id, "group_id": group_id, "assignee_id": assignee_id},
        )
        return (str(group_code), assignee_id) if valid else None

    async def round_robin_assignee(self, tenant_id: UUID, group_id: UUID) -> UUID | None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:group_id AS text),0))"),
            {"group_id": group_id},
        )
        row = (
            await self._session.execute(
                text("""
                    SELECT member.user_id,count(history.assignment_history_id) assignment_count
                    FROM identity.support_group_member AS member
                    JOIN identity.app_user AS user_ ON user_.user_id=member.user_id
                    LEFT JOIN itsm.assignment_history AS history
                      ON history.to_group_id=member.support_group_id
                     AND history.to_assignee_id=member.user_id
                    WHERE member.support_group_id=:group_id AND member.active_flag
                      AND member.member_role IN ('AGENT','LEAD','MANAGER')
                      AND user_.tenant_id=:tenant_id AND user_.active_flag
                    GROUP BY member.user_id
                    ORDER BY count(history.assignment_history_id),member.user_id
                    LIMIT 1
                """),
                {"tenant_id": tenant_id, "group_id": group_id},
            )
        ).one_or_none()
        return cast("UUID", row.user_id) if row is not None else None

    async def assign(
        self,
        ticket: RoutingTicket,
        group_id: UUID,
        group_code: str,
        assignee_id: UUID | None,
        actor_user_id: UUID,
    ) -> AssignmentResult | None:
        row = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket
                    SET assignment_group_id=:group_id,assignee_user_id=:assignee_id,
                      updated_by=:actor_user_id
                    WHERE ticket_id=:ticket_id AND row_version=:row_version
                      AND assignment_group_id IS NOT DISTINCT FROM CAST(:old_group_id AS uuid)
                      AND assignee_user_id IS NOT DISTINCT FROM CAST(:old_assignee_id AS uuid)
                    RETURNING row_version
                """),
                {
                    "ticket_id": ticket.ticket_id,
                    "row_version": ticket.row_version,
                    "old_group_id": ticket.assignment_group_id,
                    "old_assignee_id": ticket.assignee_user_id,
                    "group_id": group_id,
                    "assignee_id": assignee_id,
                    "actor_user_id": actor_user_id,
                },
            )
        ).one_or_none()
        if row is None:
            return None
        return AssignmentResult(group_id, group_code, assignee_id, row.row_version)

    async def record_assignment(
        self,
        ticket: RoutingTicket,
        result: AssignmentResult,
        actor_user_id: UUID,
        reason: str,
        correlation_id: str,
        request_id: str,
        *,
        rule: RoutingRuleVersion | None,
        fallback: bool,
        routing_trace: dict[str, Any] | None,
    ) -> None:
        await self._session.execute(
            text("""
                INSERT INTO itsm.assignment_history(
                  ticket_id,from_group_id,to_group_id,from_assignee_id,to_assignee_id,
                  assignment_reason,routing_rule_id,routing_rule_version_id,assigned_by)
                VALUES (:ticket_id,:from_group_id,:to_group_id,:from_assignee_id,
                  :to_assignee_id,:reason,:routing_rule_id,:routing_rule_version_id,
                  :actor_user_id)
            """),
            {
                "ticket_id": ticket.ticket_id,
                "from_group_id": ticket.assignment_group_id,
                "to_group_id": result.assignment_group_id,
                "from_assignee_id": ticket.assignee_user_id,
                "to_assignee_id": result.assignee_user_id,
                "reason": reason,
                "routing_rule_id": rule.routing_rule_id if rule else None,
                "routing_rule_version_id": rule.routing_rule_version_id if rule else None,
                "actor_user_id": actor_user_id,
            },
        )
        payload = {
            "ticket_key": ticket.ticket_key,
            "from_group_id": str(ticket.assignment_group_id)
            if ticket.assignment_group_id
            else None,
            "to_group_id": str(result.assignment_group_id),
            "from_assignee_id": str(ticket.assignee_user_id) if ticket.assignee_user_id else None,
            "to_assignee_id": str(result.assignee_user_id) if result.assignee_user_id else None,
            "routing_rule_id": str(rule.routing_rule_id) if rule else None,
            "routing_rule_version_id": str(rule.routing_rule_version_id) if rule else None,
            "fallback": fallback,
            "reason": reason,
            "old_row_version": ticket.row_version,
            "new_row_version": result.new_row_version,
            "correlation_id": correlation_id,
            "request_id": request_id,
            "routing_trace": routing_trace,
        }
        event_type = "TICKET_ROUTED" if rule else "TICKET_REASSIGNED"
        await self._session.execute(
            text("""
                INSERT INTO itsm.ticket_event(
                  tenant_id,ticket_id,event_type,actor_type,actor_user_id,event_data_json)
                VALUES (:tenant_id,:ticket_id,:event_type,'AGENT',:actor_user_id,
                  CAST(:payload AS jsonb))
            """),
            {
                "tenant_id": ticket.tenant_id,
                "ticket_id": ticket.ticket_id,
                "event_type": event_type,
                "actor_user_id": actor_user_id,
                "payload": json.dumps(payload),
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO integration.outbox_event(
                  tenant_id,aggregate_type,aggregate_id,event_type,payload_json)
                VALUES (:tenant_id,'TICKET',CAST(:ticket_id AS varchar),
                  'TICKET_ASSIGNED',CAST(:payload AS jsonb))
            """),
            {
                "tenant_id": ticket.tenant_id,
                "ticket_id": ticket.ticket_id,
                "payload": json.dumps(payload),
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO integration.outbox_event(
                  tenant_id,aggregate_type,aggregate_id,event_type,payload_json,
                  deduplication_key)
                SELECT :tenant_id,'TICKET',CAST(:ticket_id AS varchar),
                  'NOTIFY_TICKET_ASSIGNED',CAST(:payload AS jsonb),
                  'notify-assigned:' || CAST(:ticket_id AS varchar) || ':' ||
                    CAST(:new_row_version AS varchar)
                WHERE CAST(:assignee_user_id AS uuid) IS NOT NULL
                ON CONFLICT DO NOTHING
            """),
            {
                "tenant_id": ticket.tenant_id,
                "ticket_id": ticket.ticket_id,
                "new_row_version": result.new_row_version,
                "assignee_user_id": result.assignee_user_id,
                "payload": json.dumps(payload),
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (:tenant_id,CAST(:actor_user_id AS varchar),'USER',:action_code,
                  'TICKET',CAST(:ticket_id AS varchar),CAST(:payload AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": ticket.tenant_id,
                "actor_user_id": actor_user_id,
                "action_code": event_type,
                "ticket_id": ticket.ticket_id,
                "payload": json.dumps(payload),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )

    async def claim_idempotency(
        self, tenant_id: UUID, user_id: UUID, operation: str, key: str, request_hash: str
    ) -> Any:
        await self._session.execute(
            text("""
                INSERT INTO integration.idempotency_record(
                  tenant_id,principal_type,principal_id,operation_code,idempotency_key,
                  request_hash,lease_expires_at,expires_at)
                VALUES (:tenant_id,'USER',CAST(:user_id AS varchar),:operation,:key,
                  :request_hash,now()+interval '60 seconds',now()+interval '24 hours')
                ON CONFLICT (tenant_id,operation_code,idempotency_key) DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "operation": operation,
                "key": key,
                "request_hash": request_hash,
            },
        )
        return (
            await self._session.execute(
                text("""
                    SELECT * FROM integration.idempotency_record
                    WHERE tenant_id=:tenant_id AND operation_code=:operation
                      AND idempotency_key=:key FOR UPDATE
                """),
                {"tenant_id": tenant_id, "operation": operation, "key": key},
            )
        ).one()

    async def complete_idempotency(
        self, record_id: UUID, ticket_id: UUID, payload: dict[str, Any]
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE integration.idempotency_record
                SET processing_status='COMPLETED',result_resource_type='TICKET',
                  result_resource_id=CAST(:ticket_id AS varchar),response_status=200,
                  response_payload_json=CAST(:payload AS jsonb),completed_at=now(),
                  lease_expires_at=NULL
                WHERE idempotency_record_id=:record_id
            """),
            {"record_id": record_id, "ticket_id": ticket_id, "payload": json.dumps(payload)},
        )


def _json_value(value: Any) -> Any:
    if isinstance(value, (UUID, Decimal, date, datetime)):
        return str(value)
    return value
