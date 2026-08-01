"""Append-only security-event persistence with deliberately minimal payloads."""

import json
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.context import RequestContext

_INSERT_SECURITY_EVENT = text(
    """
    INSERT INTO audit.security_event (
        tenant_id, user_id, event_type, resource_type, resource_id,
        decision_code, event_data_json
    ) VALUES (
        :tenant_id, :user_id, :event_type, :resource_type, :resource_id,
        :decision_code, CAST(:event_data_json AS jsonb)
    )
    """
)


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    event_type: str
    decision_code: str
    tenant_id: UUID | None = None
    user_id: UUID | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict[str, str] = field(default_factory=dict)
    authentication_mode: str = "developer_header"


class _SecurityEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: SecurityEvent, request_context: RequestContext) -> None:
        safe_details = {
            "correlation_id": request_context.correlation_id,
            "request_id": request_context.request_id,
            "authentication_mode": event.authentication_mode,
            **event.details,
        }
        await self._session.execute(
            _INSERT_SECURITY_EVENT,
            {
                "tenant_id": event.tenant_id,
                "user_id": event.user_id,
                "event_type": event.event_type,
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "decision_code": event.decision_code,
                "event_data_json": json.dumps(safe_details, separators=(",", ":")),
            },
        )


class SecurityEventService:
    """Public audit application service for append-only security events."""

    def __init__(self, session: AsyncSession) -> None:
        self._repository = _SecurityEventRepository(session)

    async def record(self, event: SecurityEvent, request_context: RequestContext) -> None:
        await self._repository.append(event, request_context)
