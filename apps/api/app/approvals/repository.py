"""Transactional PostgreSQL approval persistence."""

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.approvals.models import (
    ApprovalDefinition,
    ApprovalTicket,
    ApprovalView,
    LockedApproval,
)


class ApprovalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ticket(self, tenant_id: UUID, ticket_id: UUID) -> ApprovalTicket | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT ticket_id,tenant_id,ticket_key,project_id,reporter_user_id,
                      requested_for_user_id
                    FROM itsm.ticket
                    WHERE tenant_id=:tenant_id AND ticket_id=:ticket_id
                """),
                {"tenant_id": tenant_id, "ticket_id": ticket_id},
            )
        ).one_or_none()
        return ApprovalTicket(*tuple(row)) if row is not None else None

    async def published_definition(
        self, tenant_id: UUID, project_id: UUID, approval_code: str
    ) -> ApprovalDefinition | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT definition.approval_definition_id,
                      version.approval_definition_version_id,definition.tenant_id,
                      definition.project_id,definition.approval_code,
                      definition.approval_name,version.approval_mode,
                      version.approver_rule_json,version.on_approved_transition_id,
                      version.on_rejected_transition_id,
                      version.allow_requester_self_approval,
                      version.expires_after_minutes
                    FROM config.approval_definition AS definition
                    JOIN config.approval_definition_version AS version
                      ON version.approval_definition_id=definition.approval_definition_id
                    WHERE definition.tenant_id=:tenant_id
                      AND definition.project_id=:project_id
                      AND definition.approval_code=:approval_code
                      AND definition.active_flag AND version.version_status='PUBLISHED'
                      AND (version.effective_from IS NULL OR version.effective_from<=now())
                      AND (version.effective_to IS NULL OR version.effective_to>now())
                    ORDER BY version.version_number DESC LIMIT 1
                """),
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "approval_code": approval_code,
                },
            )
        ).one_or_none()
        return ApprovalDefinition(*tuple(row)) if row is not None else None

    async def active_users(self, tenant_id: UUID, user_ids: list[UUID]) -> set[UUID]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT user_id FROM identity.app_user
                    WHERE tenant_id=:tenant_id AND active_flag
                      AND user_id=ANY(CAST(:user_ids AS uuid[]))
                """),
                {"tenant_id": tenant_id, "user_ids": user_ids},
            )
        ).all()
        return {row.user_id for row in rows}

    async def manager_for(self, tenant_id: UUID, user_id: UUID) -> UUID | None:
        return cast(
            "UUID | None",
            await self._session.scalar(
                text("""
                SELECT manager.user_id
                FROM identity.app_user AS subject
                JOIN identity.app_user AS manager
                  ON manager.user_id=subject.manager_user_id
                 AND manager.tenant_id=subject.tenant_id AND manager.active_flag
                WHERE subject.tenant_id=:tenant_id AND subject.user_id=:user_id
                  AND subject.active_flag
                """),
                {"tenant_id": tenant_id, "user_id": user_id},
            ),
        )

    async def create(
        self,
        ticket: ApprovalTicket,
        definition: ApprovalDefinition,
        approver_ids: list[UUID],
        actor_user_id: UUID,
        correlation_id: str,
        request_id: str,
    ) -> UUID:
        approval_id = uuid4()
        await self._session.execute(
            text("""
                INSERT INTO itsm.ticket_approval(
                  ticket_approval_id,tenant_id,ticket_id,approval_definition_id,
                  approval_definition_version_id,approval_status,created_by,expires_at)
                VALUES (:approval_id,:tenant_id,:ticket_id,:definition_id,:version_id,
                  'PENDING',:actor_user_id,
                  CASE WHEN :expires_after IS NULL THEN NULL
                    ELSE now()+make_interval(mins=>:expires_after) END)
            """),
            {
                "approval_id": approval_id,
                "tenant_id": ticket.tenant_id,
                "ticket_id": ticket.ticket_id,
                "definition_id": definition.definition_id,
                "version_id": definition.version_id,
                "actor_user_id": actor_user_id,
                "expires_after": definition.expires_after_minutes,
            },
        )
        for sequence, approver_id in enumerate(approver_ids, start=1):
            await self._session.execute(
                text("""
                    INSERT INTO itsm.ticket_approver(
                      ticket_approval_id,approver_user_id,sequence_number,tenant_id)
                    VALUES (:approval_id,:approver_id,:sequence,:tenant_id)
                """),
                {
                    "approval_id": approval_id,
                    "approver_id": approver_id,
                    "sequence": sequence,
                    "tenant_id": ticket.tenant_id,
                },
            )
        payload = {
            "approval_id": str(approval_id),
            "ticket_id": str(ticket.ticket_id),
            "ticket_key": ticket.ticket_key,
            "approval_code": definition.code,
            "approval_definition_version_id": str(definition.version_id),
            "approval_mode": definition.mode,
            "approver_user_ids": [str(value) for value in approver_ids],
        }
        await self._record_fact(
            ticket.tenant_id,
            ticket.ticket_id,
            actor_user_id,
            approval_id,
            "APPROVAL_REQUESTED",
            payload,
            correlation_id,
            request_id,
        )
        return approval_id

    async def list_for_user(self, tenant_id: UUID, user_id: UUID) -> list[ApprovalView]:
        rows = (
            await self._session.execute(
                text(
                    _VIEW_SELECT
                    + """
                    WHERE approval.tenant_id=:tenant_id
                      AND approver.approver_user_id=:user_id
                    ORDER BY approval.requested_at DESC,approval.ticket_approval_id DESC
                """
                ),
                {"tenant_id": tenant_id, "user_id": user_id},
            )
        ).all()
        return [ApprovalView(*tuple(row)) for row in rows]

    async def view_for_user(
        self, tenant_id: UUID, approval_id: UUID, user_id: UUID
    ) -> ApprovalView | None:
        row = (
            await self._session.execute(
                text(
                    _VIEW_SELECT
                    + """
                    WHERE approval.tenant_id=:tenant_id
                      AND approval.ticket_approval_id=:approval_id
                      AND approver.approver_user_id=:user_id
                """
                ),
                {"tenant_id": tenant_id, "approval_id": approval_id, "user_id": user_id},
            )
        ).one_or_none()
        return ApprovalView(*tuple(row)) if row is not None else None

    async def lock_for_decision(
        self, tenant_id: UUID, approval_id: UUID, user_id: UUID
    ) -> LockedApproval | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT approval.ticket_approval_id,approval.tenant_id,
                      approval.ticket_id,ticket.ticket_key,
                      coalesce(ticket.requested_for_user_id,ticket.reporter_user_id),
                      approval.approval_status,approval.row_version,version.approval_mode,
                      version.approver_rule_json,
                      version.on_approved_transition_id,version.on_rejected_transition_id,
                      version.allow_requester_self_approval,approval.expires_at,
                      approver.approver_user_id,approver.decision_code
                    FROM itsm.ticket_approval AS approval
                    JOIN itsm.ticket AS ticket ON ticket.ticket_id=approval.ticket_id
                    JOIN config.approval_definition_version AS version
                      ON version.approval_definition_version_id=
                         approval.approval_definition_version_id
                    JOIN itsm.ticket_approver AS approver
                      ON approver.ticket_approval_id=approval.ticket_approval_id
                    WHERE approval.tenant_id=:tenant_id
                      AND approval.ticket_approval_id=:approval_id
                      AND approver.approver_user_id=:user_id
                    FOR UPDATE OF approval,approver
                """),
                {"tenant_id": tenant_id, "approval_id": approval_id, "user_id": user_id},
            )
        ).one_or_none()
        return LockedApproval(*tuple(row)) if row is not None else None

    async def claim_idempotency(
        self, tenant_id: UUID, user_id: UUID, key: str, request_hash: str
    ) -> Any:
        await self._session.execute(
            text("""
                INSERT INTO integration.idempotency_record(
                  tenant_id,principal_type,principal_id,operation_code,idempotency_key,
                  request_hash,lease_expires_at,expires_at)
                VALUES (:tenant_id,'USER',CAST(:user_id AS varchar),'APPROVAL_DECISION',:key,
                  :request_hash,now()+interval '60 seconds',now()+interval '24 hours')
                ON CONFLICT (tenant_id,operation_code,idempotency_key) DO NOTHING
            """),
            {"tenant_id": tenant_id, "user_id": user_id, "key": key, "request_hash": request_hash},
        )
        return (
            await self._session.execute(
                text("""
                    SELECT * FROM integration.idempotency_record
                    WHERE tenant_id=:tenant_id AND operation_code='APPROVAL_DECISION'
                      AND idempotency_key=:key FOR UPDATE
                """),
                {"tenant_id": tenant_id, "key": key},
            )
        ).one()

    async def decision_counts(self, approval_id: UUID) -> tuple[int, int, int]:
        row = (
            await self._session.execute(
                text("""
                    SELECT count(*) total,
                      count(*) FILTER (WHERE decision_code='APPROVED') approved,
                      count(*) FILTER (WHERE decision_code='REJECTED') rejected
                    FROM itsm.ticket_approver WHERE ticket_approval_id=:approval_id
                """),
                {"approval_id": approval_id},
            )
        ).one()
        return int(row.total), int(row.approved), int(row.rejected)

    async def record_decision(
        self,
        approval: LockedApproval,
        user_id: UUID,
        decision: str,
        comment: str | None,
        terminal_status: str | None,
        correlation_id: str,
        request_id: str,
    ) -> int:
        await self._session.execute(
            text("""
                INSERT INTO itsm.ticket_approval_decision(
                  tenant_id,ticket_approval_id,approver_user_id,decision_code,
                  decision_comment,correlation_id)
                VALUES (:tenant_id,:approval_id,:user_id,:decision,:comment,
                  CAST(:correlation_id AS uuid))
            """),
            {
                "tenant_id": approval.tenant_id,
                "approval_id": approval.approval_id,
                "user_id": user_id,
                "decision": decision,
                "comment": comment,
                "correlation_id": correlation_id,
            },
        )
        await self._session.execute(
            text("""
                UPDATE itsm.ticket_approver SET decision_code=:decision,
                  decision_comment=:comment,decided_at=now()
                WHERE ticket_approval_id=:approval_id AND approver_user_id=:user_id
                  AND decision_code IS NULL
            """),
            {
                "approval_id": approval.approval_id,
                "user_id": user_id,
                "decision": decision,
                "comment": comment,
            },
        )
        row = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket_approval
                    SET approval_status=coalesce(:terminal_status,approval_status),
                      completed_at=CASE WHEN :terminal_status IS NULL
                        THEN completed_at ELSE now() END,
                      row_version=row_version+1
                    WHERE ticket_approval_id=:approval_id AND row_version=:row_version
                    RETURNING row_version
                """),
                {
                    "approval_id": approval.approval_id,
                    "row_version": approval.row_version,
                    "terminal_status": terminal_status,
                },
            )
        ).one()
        payload = {
            "approval_id": str(approval.approval_id),
            "ticket_id": str(approval.ticket_id),
            "ticket_key": approval.ticket_key,
            "approver_user_id": str(user_id),
            "decision": decision,
            "approval_status": terminal_status or "PENDING",
            "comment_present": comment is not None,
            "row_version": row.row_version,
        }
        await self._record_fact(
            approval.tenant_id,
            approval.ticket_id,
            user_id,
            approval.approval_id,
            "APPROVAL_DECIDED",
            payload,
            correlation_id,
            request_id,
        )
        return int(row.row_version)

    async def continue_workflow(
        self,
        approval: LockedApproval,
        transition_id: UUID,
        actor_user_id: UUID,
        correlation_id: str,
        request_id: str,
    ) -> None:
        row = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket AS ticket
                    SET status_id=transition.to_status_id,updated_by=:actor_user_id
                    FROM config.workflow_transition AS transition
                    WHERE ticket.ticket_id=:ticket_id AND ticket.tenant_id=:tenant_id
                      AND transition.transition_id=:transition_id
                      AND transition.workflow_version_id=ticket.workflow_version_id
                      AND transition.from_status_id=ticket.status_id
                      AND transition.active_flag
                      AND transition.action_json @> '[{"type":"APPROVAL_CONTINUATION"}]'::jsonb
                    RETURNING ticket.row_version,transition.from_status_id,
                      transition.to_status_id,transition.transition_code
                """),
                {
                    "actor_user_id": actor_user_id,
                    "ticket_id": approval.ticket_id,
                    "tenant_id": approval.tenant_id,
                    "transition_id": transition_id,
                },
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError("Approval continuation transition is invalid for the ticket state.")
        payload = {
            "ticket_key": approval.ticket_key,
            "approval_id": str(approval.approval_id),
            "transition_id": str(transition_id),
            "transition_code": row.transition_code,
            "from_status_id": str(row.from_status_id),
            "to_status_id": str(row.to_status_id),
            "row_version": row.row_version,
            "correlation_id": correlation_id,
            "request_id": request_id,
        }
        rendered = json.dumps(payload)
        await self._session.execute(
            text("""
                INSERT INTO itsm.ticket_event(
                  tenant_id,ticket_id,event_type,actor_type,actor_user_id,
                  old_values_json,new_values_json,event_data_json)
                VALUES (:tenant_id,:ticket_id,'WORKFLOW_TRANSITION_EXECUTED','USER',
                  :actor_user_id,
                  jsonb_build_object('status_id',CAST(:from_status_id AS varchar)),
                  jsonb_build_object('status_id',CAST(:to_status_id AS varchar),
                    'row_version',:row_version),
                  CAST(:payload AS jsonb))
            """),
            {
                "tenant_id": approval.tenant_id,
                "ticket_id": approval.ticket_id,
                "actor_user_id": actor_user_id,
                "from_status_id": str(row.from_status_id),
                "to_status_id": str(row.to_status_id),
                "row_version": row.row_version,
                "payload": rendered,
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO integration.outbox_event(
                  tenant_id,aggregate_type,aggregate_id,event_type,payload_json,
                  deduplication_key)
                VALUES (:tenant_id,'TICKET',CAST(:ticket_id AS varchar),
                  'TICKET_WORKFLOW_TRANSITIONED',CAST(:payload AS jsonb),
                  :deduplication_key)
            """),
            {
                "tenant_id": approval.tenant_id,
                "ticket_id": approval.ticket_id,
                "payload": rendered,
                "deduplication_key": f"approval-workflow:{approval.approval_id}",
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
                "tenant_id": approval.tenant_id,
                "actor_user_id": actor_user_id,
                "ticket_id": approval.ticket_id,
                "payload": rendered,
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )

    async def complete_idempotency(
        self, record_id: UUID, approval_id: UUID, payload: dict[str, Any]
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE integration.idempotency_record
                SET processing_status='COMPLETED',result_resource_type='APPROVAL',
                  result_resource_id=CAST(:approval_id AS varchar),response_status=200,
                  response_payload_json=CAST(:payload AS jsonb),completed_at=now(),
                  lease_expires_at=NULL
                WHERE idempotency_record_id=:record_id
            """),
            {"record_id": record_id, "approval_id": approval_id, "payload": json.dumps(payload)},
        )

    async def expire_if_due(
        self, approval: LockedApproval, actor_user_id: UUID, correlation_id: str, request_id: str
    ) -> bool:
        if approval.expires_at is None or approval.expires_at > datetime.now(UTC):
            return False
        row = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket_approval SET approval_status='EXPIRED',
                      completed_at=now(),row_version=row_version+1
                    WHERE ticket_approval_id=:approval_id AND approval_status='PENDING'
                    RETURNING ticket_approval_id
                """),
                {"approval_id": approval.approval_id},
            )
        ).one_or_none()
        if row is not None:
            await self._record_fact(
                approval.tenant_id,
                approval.ticket_id,
                actor_user_id,
                approval.approval_id,
                "APPROVAL_EXPIRED",
                {"approval_id": str(approval.approval_id)},
                correlation_id,
                request_id,
            )
        return row is not None

    async def cancel_pending(
        self,
        tenant_id: UUID,
        ticket_id: UUID,
        actor_user_id: UUID,
        correlation_id: str,
        request_id: str,
    ) -> int:
        rows = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket_approval
                    SET approval_status='CANCELLED',completed_at=now(),
                      row_version=row_version+1
                    WHERE tenant_id=:tenant_id AND ticket_id=:ticket_id
                      AND approval_status='PENDING'
                    RETURNING ticket_approval_id
                """),
                {"tenant_id": tenant_id, "ticket_id": ticket_id},
            )
        ).all()
        for row in rows:
            await self._record_fact(
                tenant_id,
                ticket_id,
                actor_user_id,
                row.ticket_approval_id,
                "APPROVAL_CANCELLED",
                {"approval_id": str(row.ticket_approval_id)},
                correlation_id,
                request_id,
            )
        return len(rows)

    async def _record_fact(
        self,
        tenant_id: UUID,
        ticket_id: UUID,
        actor_user_id: UUID,
        approval_id: UUID,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str,
        request_id: str,
    ) -> None:
        rendered = json.dumps(payload)
        await self._session.execute(
            text("""
                INSERT INTO itsm.ticket_event(
                  tenant_id,ticket_id,event_type,actor_type,actor_user_id,event_data_json)
                VALUES (:tenant_id,:ticket_id,:event_type,'USER',:actor_user_id,
                  CAST(:payload AS jsonb))
            """),
            {
                "tenant_id": tenant_id,
                "ticket_id": ticket_id,
                "event_type": event_type,
                "actor_user_id": actor_user_id,
                "payload": rendered,
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO integration.outbox_event(
                  tenant_id,aggregate_type,aggregate_id,event_type,payload_json,
                  deduplication_key)
                VALUES (:tenant_id,'APPROVAL',CAST(:approval_id AS varchar),:event_type,
                  CAST(:payload AS jsonb),:deduplication_key)
                ON CONFLICT DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "approval_id": approval_id,
                "event_type": event_type,
                "payload": rendered,
                "deduplication_key": f"{event_type}:{approval_id}:{payload.get('row_version', 1)}",
            },
        )
        await self._session.execute(
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (:tenant_id,CAST(:actor_user_id AS varchar),'USER',:event_type,
                  'APPROVAL',CAST(:approval_id AS varchar),CAST(:payload AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "event_type": event_type,
                "approval_id": approval_id,
                "payload": rendered,
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )


_VIEW_SELECT = """
SELECT approval.ticket_approval_id,approval.ticket_id,ticket.ticket_key,ticket.summary,
 approval.approval_definition_version_id,definition.approval_code,
 definition.approval_name,version.approval_mode,approval.approval_status,
 approval.requested_at,approval.completed_at,approval.expires_at,approval.row_version,
 approver.approver_user_id,approver.sequence_number,approver.decision_code,
 approver.decision_comment,approver.decided_at
FROM itsm.ticket_approval AS approval
JOIN itsm.ticket AS ticket ON ticket.ticket_id=approval.ticket_id
JOIN config.approval_definition AS definition
  ON definition.approval_definition_id=approval.approval_definition_id
JOIN config.approval_definition_version AS version
  ON version.approval_definition_version_id=approval.approval_definition_version_id
JOIN itsm.ticket_approver AS approver
  ON approver.ticket_approval_id=approval.ticket_approval_id
"""
