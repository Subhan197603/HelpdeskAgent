"""Tenant-scoped administration reads over identity, ticket, kb, and audit data."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_OVERVIEW = text("""
SELECT
  (SELECT count(*) FROM identity.app_user app_user
    WHERE app_user.tenant_id=:tenant_id AND app_user.active_flag) AS active_users,
  (SELECT count(*) FROM identity.support_group support_group
    WHERE support_group.tenant_id=:tenant_id AND support_group.active_flag) AS support_groups,
  (SELECT count(*) FROM itsm.ticket ticket
    JOIN config.workflow_status status ON status.status_id=ticket.status_id
    WHERE ticket.tenant_id=:tenant_id AND NOT status.terminal_flag) AS open_tickets,
  (SELECT count(*) FROM kb.document document
    JOIN kb.document_version version ON version.document_id=document.document_id
      AND version.current_version_flag
      AND version.published_processing_version_id IS NOT NULL
    WHERE (document.tenant_id IS NULL OR document.tenant_id=:tenant_id)
      AND document.active_flag
      AND document.approval_status='APPROVED') AS published_knowledge_documents
""")

_AUDIT_EVENTS = text("""
SELECT audit_event_id,actor_id,actor_type,action_code,resource_type,resource_id,
  outcome_code,failure_reason,change_summary_json,correlation_id,request_id,occurred_at
FROM audit.audit_event
WHERE tenant_id=:tenant_id
  AND (CAST(:resource_type AS text) IS NULL OR resource_type=:resource_type)
  AND (CAST(:action_code AS text) IS NULL OR action_code=:action_code)
  AND (CAST(:outcome_code AS text) IS NULL OR outcome_code=:outcome_code)
  AND (CAST(:occurred_from AS timestamptz) IS NULL OR occurred_at>=:occurred_from)
  AND (CAST(:occurred_to AS timestamptz) IS NULL OR occurred_at<=:occurred_to)
ORDER BY occurred_at DESC,audit_event_id DESC
LIMIT :result_limit OFFSET :result_offset
""")

_SECURITY_EVENTS = text("""
SELECT security_event_id,event_type,decision_code,user_id,resource_type,resource_id,
  event_data_json,occurred_at
FROM audit.security_event
WHERE tenant_id=:tenant_id
  AND (CAST(:event_type AS text) IS NULL OR event_type=:event_type)
  AND (CAST(:decision_code AS text) IS NULL OR decision_code=:decision_code)
  AND (CAST(:occurred_from AS timestamptz) IS NULL OR occurred_at>=:occurred_from)
  AND (CAST(:occurred_to AS timestamptz) IS NULL OR occurred_at<=:occurred_to)
ORDER BY occurred_at DESC,security_event_id DESC
LIMIT :result_limit OFFSET :result_offset
""")


@dataclass(frozen=True, slots=True)
class OverviewCounts:
    active_users: int
    support_groups: int
    open_tickets: int
    published_knowledge_documents: int


@dataclass(frozen=True, slots=True)
class AuditEventRow:
    id: int
    actor_id: str | None
    actor_type: str
    action_code: str
    resource_type: str
    resource_id: str | None
    outcome_code: str
    failure_reason: str | None
    change_summary: dict[str, Any]
    correlation_id: UUID | None
    request_id: str | None
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class SecurityEventRow:
    id: int
    event_type: str
    decision_code: str
    user_id: UUID | None
    resource_type: str | None
    resource_id: str | None
    details: dict[str, Any]
    occurred_at: datetime


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


class AdminRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def overview(self, tenant_id: UUID) -> OverviewCounts:
        row = (await self._session.execute(_OVERVIEW, {"tenant_id": tenant_id})).one()
        return OverviewCounts(
            active_users=int(row.active_users),
            support_groups=int(row.support_groups),
            open_tickets=int(row.open_tickets),
            published_knowledge_documents=int(row.published_knowledge_documents),
        )

    async def audit_events(
        self,
        tenant_id: UUID,
        *,
        resource_type: str | None,
        action_code: str | None,
        outcome_code: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[AuditEventRow, ...]:
        rows = (
            await self._session.execute(
                _AUDIT_EVENTS,
                {
                    "tenant_id": tenant_id,
                    "resource_type": resource_type,
                    "action_code": action_code,
                    "outcome_code": outcome_code,
                    "occurred_from": occurred_from,
                    "occurred_to": occurred_to,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            AuditEventRow(
                id=int(row.audit_event_id),
                actor_id=row.actor_id,
                actor_type=row.actor_type,
                action_code=row.action_code,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                outcome_code=row.outcome_code,
                failure_reason=row.failure_reason,
                change_summary=_mapping(row.change_summary_json),
                correlation_id=row.correlation_id,
                request_id=row.request_id,
                occurred_at=row.occurred_at,
            )
            for row in rows
        )

    async def security_events(
        self,
        tenant_id: UUID,
        *,
        event_type: str | None,
        decision_code: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        limit: int,
        offset: int,
    ) -> tuple[SecurityEventRow, ...]:
        rows = (
            await self._session.execute(
                _SECURITY_EVENTS,
                {
                    "tenant_id": tenant_id,
                    "event_type": event_type,
                    "decision_code": decision_code,
                    "occurred_from": occurred_from,
                    "occurred_to": occurred_to,
                    "result_limit": limit,
                    "result_offset": offset,
                },
            )
        ).all()
        return tuple(
            SecurityEventRow(
                id=int(row.security_event_id),
                event_type=row.event_type,
                decision_code=row.decision_code,
                user_id=row.user_id,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                details=_mapping(row.event_data_json),
                occurred_at=row.occurred_at,
            )
            for row in rows
        )
