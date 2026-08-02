"""Transactional PostgreSQL persistence for workflow execution."""

import json
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.workflows.models import WorkflowTicket, WorkflowTransition


class WorkflowRepository:
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
    ) -> WorkflowTicket | None:
        lock_clause = " FOR UPDATE OF ticket" if lock else ""
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT ticket.ticket_id,ticket.tenant_id,ticket.ticket_key,
                      ticket.workflow_version_id,version.version_status,ticket.status_id,
                      status.status_code,ticket.row_version,ticket.summary,ticket.description,
                      ticket.resolution_code,ticket.resolution_summary,
                      ticket.assignment_group_id,ticket.assignee_user_id,
                      ticket.first_response_at,ticket.resolved_at,ticket.closed_at
                    FROM itsm.ticket AS ticket
                    JOIN config.workflow_version AS version
                      ON version.workflow_version_id=ticket.workflow_version_id
                    JOIN config.workflow_status AS status ON status.status_id=ticket.status_id
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
        return WorkflowTicket(*tuple(row)) if row is not None else None

    async def transition(
        self, workflow_version_id: UUID, current_status_id: UUID, transition_code: str
    ) -> WorkflowTransition | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT transition.transition_id,transition.workflow_version_id,
                      transition.transition_code,transition.transition_name,
                      transition.from_status_id,from_status.status_code,
                      transition.to_status_id,to_status.status_code,to_status.status_name,
                      transition.condition_json,transition.validator_json,transition.action_json
                    FROM config.workflow_transition AS transition
                    JOIN config.workflow_status AS from_status
                      ON from_status.status_id=transition.from_status_id
                     AND from_status.workflow_version_id=transition.workflow_version_id
                    JOIN config.workflow_status AS to_status
                      ON to_status.status_id=transition.to_status_id
                     AND to_status.workflow_version_id=transition.workflow_version_id
                    WHERE transition.workflow_version_id=:workflow_version_id
                      AND transition.from_status_id=:current_status_id
                      AND transition.transition_code=:transition_code
                      AND transition.active_flag
                """),
                {
                    "workflow_version_id": workflow_version_id,
                    "current_status_id": current_status_id,
                    "transition_code": transition_code,
                },
            )
        ).one_or_none()
        return WorkflowTransition(*tuple(row)) if row is not None else None

    async def available(
        self, workflow_version_id: UUID, current_status_id: UUID
    ) -> list[WorkflowTransition]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT transition.transition_id,transition.workflow_version_id,
                      transition.transition_code,transition.transition_name,
                      transition.from_status_id,from_status.status_code,
                      transition.to_status_id,to_status.status_code,to_status.status_name,
                      transition.condition_json,transition.validator_json,transition.action_json
                    FROM config.workflow_transition AS transition
                    JOIN config.workflow_status AS from_status
                      ON from_status.status_id=transition.from_status_id
                     AND from_status.workflow_version_id=transition.workflow_version_id
                    JOIN config.workflow_status AS to_status
                      ON to_status.status_id=transition.to_status_id
                     AND to_status.workflow_version_id=transition.workflow_version_id
                    WHERE transition.workflow_version_id=:workflow_version_id
                      AND transition.from_status_id=:current_status_id
                      AND transition.active_flag
                    ORDER BY transition.display_order,transition.transition_code
                """),
                {
                    "workflow_version_id": workflow_version_id,
                    "current_status_id": current_status_id,
                },
            )
        ).all()
        return [WorkflowTransition(*tuple(row)) for row in rows]

    async def claim_idempotency(
        self, tenant_id: UUID, user_id: UUID, key: str, request_hash: str
    ) -> Any:
        await self._session.execute(
            text("""
                INSERT INTO integration.idempotency_record(
                  tenant_id,principal_type,principal_id,operation_code,idempotency_key,
                  request_hash,lease_expires_at,expires_at)
                VALUES (:tenant_id,'USER',CAST(:user_id AS varchar),'TICKET_TRANSITION',:key,
                  :request_hash,now()+interval '60 seconds',now()+interval '24 hours')
                ON CONFLICT (tenant_id,operation_code,idempotency_key) DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "key": key,
                "request_hash": request_hash,
            },
        )
        return (
            await self._session.execute(
                text("""
                    SELECT * FROM integration.idempotency_record
                    WHERE tenant_id=:tenant_id AND operation_code='TICKET_TRANSITION'
                      AND idempotency_key=:key FOR UPDATE
                """),
                {"tenant_id": tenant_id, "key": key},
            )
        ).one()

    async def resolution_code_exists(self, code: str) -> bool:
        return bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM config.resolution_code "
                    "WHERE resolution_code=:code)"
                ),
                {"code": code},
            )
        )

    async def apply_transition(
        self,
        ticket: WorkflowTicket,
        transition: WorkflowTransition,
        actor_user_id: UUID,
        updates: dict[str, Any],
    ) -> int | None:
        allowed = {
            "resolution_code",
            "resolution_summary",
            "first_response_at",
            "resolved_at",
            "closed_at",
        }
        if not set(updates) <= allowed:
            raise ValueError("Unsupported ticket update field.")
        assignments = ["status_id=:status_id", "updated_by=:actor_user_id"]
        parameters: dict[str, Any] = {
            "ticket_id": ticket.ticket_id,
            "workflow_version_id": ticket.workflow_version_id,
            "current_status_id": ticket.status_id,
            "row_version": ticket.row_version,
            "status_id": transition.to_status_id,
            "actor_user_id": actor_user_id,
        }
        for field, value in updates.items():
            assignments.append(f"{field}=:{field}")
            parameters[field] = value
        row = (
            await self._session.execute(
                text(
                    f"""
                    UPDATE itsm.ticket SET {", ".join(assignments)}
                    WHERE ticket_id=:ticket_id AND workflow_version_id=:workflow_version_id
                      AND status_id=:current_status_id AND row_version=:row_version
                    RETURNING row_version
                    """
                ),
                parameters,
            )
        ).one_or_none()
        return cast("int", row.row_version) if row is not None else None

    async def record_transition(
        self,
        ticket: WorkflowTicket,
        transition: WorkflowTransition,
        actor_user_id: UUID,
        new_row_version: int,
        correlation_id: str,
        request_id: str,
    ) -> None:
        payload = {
            "ticket_key": ticket.ticket_key,
            "transition_id": str(transition.transition_id),
            "transition_code": transition.transition_code,
            "workflow_version_id": str(ticket.workflow_version_id),
            "from_status": transition.from_status_code,
            "to_status": transition.to_status_code,
            "synchronous_actions": transition.actions,
            "old_row_version": ticket.row_version,
            "new_row_version": new_row_version,
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
        await self._session.execute(
            text("""
                INSERT INTO itsm.ticket_event(
                  tenant_id,ticket_id,event_type,actor_type,actor_user_id,
                  old_values_json,new_values_json,event_data_json)
                VALUES (:tenant_id,:ticket_id,'WORKFLOW_TRANSITION_EXECUTED','AGENT',:actor_user_id,
                  jsonb_build_object('status_id',CAST(:from_status_id AS varchar),
                    'row_version',:old_row_version),
                  jsonb_build_object('status_id',CAST(:to_status_id AS varchar),
                    'row_version',:new_row_version),CAST(:payload AS jsonb))
            """),
            {
                "tenant_id": ticket.tenant_id,
                "ticket_id": ticket.ticket_id,
                "actor_user_id": actor_user_id,
                "from_status_id": transition.from_status_id,
                "to_status_id": transition.to_status_id,
                "old_row_version": ticket.row_version,
                "new_row_version": new_row_version,
                "payload": json.dumps(payload),
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO integration.outbox_event(
                  tenant_id,aggregate_type,aggregate_id,event_type,payload_json)
                VALUES (:tenant_id,'TICKET',CAST(:ticket_id AS varchar),
                  'TICKET_WORKFLOW_TRANSITIONED',CAST(:payload AS jsonb))
            """),
            {
                "tenant_id": ticket.tenant_id,
                "ticket_id": ticket.ticket_id,
                "payload": json.dumps(payload),
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (:tenant_id,CAST(:actor_user_id AS varchar),'USER',
                  'TICKET_WORKFLOW_TRANSITIONED','TICKET',CAST(:ticket_id AS varchar),
                  CAST(:payload AS jsonb),CAST(:correlation_id AS uuid),:request_id,
                  'API','SUCCESS')
            """),
            {
                "tenant_id": ticket.tenant_id,
                "actor_user_id": actor_user_id,
                "ticket_id": ticket.ticket_id,
                "payload": json.dumps(payload),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )

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
