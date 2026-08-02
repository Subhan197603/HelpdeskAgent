"""Retry-safe outbox consumer and periodic SLA deadline scanner."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.app.core.context import RequestContext
from apps.api.app.db.transaction_context import apply_transaction_context
from apps.api.app.sla.models import SlaInputEvent
from apps.api.app.sla.repository import SlaRepository
from apps.api.app.sla.service import SlaEngine, SlaMetrics
from apps.worker.worker.settings import WorkerSettings

logger = logging.getLogger(__name__)
_SLA_INPUT_TYPES = (
    "START_SLA",
    "AGENT_PUBLIC_RESPONSE_ADDED",
    "CUSTOMER_COMMENT_ADDED",
    "TICKET_WORKFLOW_TRANSITIONED",
    "TICKET_PRIORITY_CHANGED",
)


class SlaWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: WorkerSettings,
        metrics: SlaMetrics | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self.metrics = metrics or SlaMetrics()

    async def process_one(self) -> bool:
        event_id: UUID | None = None
        try:
            async with self._sessions() as session, session.begin():
                event = await _claim_event(session, self._settings.worker_id)
                if event is None:
                    return False
                event_id = event.outbox_event_id
                await apply_transaction_context(
                    session,
                    RequestContext(
                        tenant_id=event.tenant_id,
                        user_id=None,
                        external_subject=None,
                        roles=frozenset(),
                        support_group_ids=frozenset(),
                        business_unit_id=None,
                        correlation_id=str(event.outbox_event_id),
                        request_id=f"sla-worker:{event.outbox_event_id}",
                    ),
                    rls_enabled=True,
                )
                await SlaEngine(SlaRepository(session), self.metrics).process(event)
                await session.execute(
                    text("""
                        UPDATE integration.outbox_event
                        SET status_code='PROCESSED',processed_at=clock_timestamp(),
                            locked_at=NULL,locked_by=NULL,last_error=NULL
                        WHERE outbox_event_id=:event_id AND status_code='PROCESSING'
                    """),
                    {"event_id": event.outbox_event_id},
                )
            return True
        except Exception as error:
            logger.exception(
                "SLA outbox processing failed",
                extra={"event_id": str(event_id) if event_id else None},
            )
            if event_id is not None:
                await self._mark_failed(event_id, type(error).__name__)
            return True

    async def process_due(self, now: datetime | None = None) -> int:
        due_at = (now or datetime.now(UTC)).astimezone(UTC)
        tenant_ids = await self._tenant_ids()
        processed = 0
        for tenant_id in tenant_ids:
            async with self._sessions() as session, session.begin():
                await apply_transaction_context(
                    session,
                    RequestContext(
                        tenant_id=tenant_id,
                        user_id=None,
                        external_subject=None,
                        roles=frozenset(),
                        support_group_ids=frozenset(),
                        business_unit_id=None,
                        correlation_id=str(tenant_id),
                        request_id=f"sla-due:{due_at.isoformat()}",
                    ),
                    rls_enabled=True,
                )
                processed += await SlaEngine(SlaRepository(session), self.metrics).evaluate_due(
                    tenant_id, due_at, self._settings.worker_batch_size
                )
        return processed

    async def run_forever(self) -> None:
        next_due_scan = datetime.now(UTC)
        while True:
            handled = 0
            for _ in range(self._settings.worker_batch_size):
                if not await self.process_one():
                    break
                handled += 1
            now = datetime.now(UTC)
            if now >= next_due_scan:
                await self.process_due(now)
                next_due_scan = now + timedelta(seconds=self._settings.worker_due_scan_seconds)
            if handled == 0:
                await asyncio.sleep(self._settings.worker_poll_seconds)

    async def _tenant_ids(self) -> list[UUID]:
        async with self._sessions() as session, session.begin():
            return list(
                (
                    await session.execute(
                        text(
                            "SELECT tenant_id FROM identity.tenant "
                            "WHERE active_flag ORDER BY tenant_id"
                        )
                    )
                ).scalars()
            )

    async def _mark_failed(self, event_id: UUID, error_code: str) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                text("""
                    UPDATE integration.outbox_event
                    SET retry_count=retry_count+1,
                        status_code=CASE WHEN retry_count+1>=:max_attempts
                                         THEN 'DEAD_LETTER' ELSE 'FAILED' END,
                        available_at=clock_timestamp()
                          + make_interval(secs=>LEAST(300,POWER(2,retry_count)::integer)),
                        locked_at=NULL,locked_by=NULL,last_error=:error_code
                    WHERE outbox_event_id=:event_id
                      AND status_code IN ('PENDING','FAILED','PROCESSING')
                """),
                {
                    "event_id": event_id,
                    "max_attempts": self._settings.worker_max_attempts,
                    "error_code": error_code[:100],
                },
            )


async def _claim_event(session: AsyncSession, worker_id: str) -> SlaInputEvent | None:
    row = (
        (
            await session.execute(
                text("""
                WITH candidate AS (
                  SELECT outbox_event_id
                  FROM integration.outbox_event
                  WHERE status_code IN ('PENDING','FAILED')
                    AND available_at<=clock_timestamp()
                    AND event_type=ANY(CAST(:event_types AS varchar[]))
                  ORDER BY created_at,outbox_event_id
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                UPDATE integration.outbox_event AS event
                SET status_code='PROCESSING',locked_at=clock_timestamp(),locked_by=:worker_id
                FROM candidate
                WHERE event.outbox_event_id=candidate.outbox_event_id
                RETURNING event.outbox_event_id,event.tenant_id,event.aggregate_id,
                          event.event_type,event.payload_json,event.created_at
            """),
                {"event_types": list(_SLA_INPUT_TYPES), "worker_id": worker_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    if row.tenant_id is None:
        raise ValueError("SLA outbox event must be tenant-scoped")
    payload: dict[str, Any] = dict(row.payload_json)
    ticket_value = payload.get("ticket_id", row.aggregate_id)
    return SlaInputEvent(
        outbox_event_id=row.outbox_event_id,
        tenant_id=row.tenant_id,
        ticket_id=UUID(str(ticket_value)),
        event_type=row.event_type,
        payload=payload,
        occurred_at=row.created_at,
    )


def create_worker(settings: WorkerSettings) -> tuple[SlaWorker, AsyncEngine]:
    engine = create_async_engine(
        settings.worker_database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    return SlaWorker(sessions, settings), engine
