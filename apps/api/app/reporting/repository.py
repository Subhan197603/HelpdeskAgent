"""Aggregate queries for the analyst dashboard.

Every query is tenant-scoped and indexed; the endpoint budget is at most six
SQL statements per request (five here plus the primary-queue lookup performed
by the queue service).
"""

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.reporting.models import (
    ActivityRow,
    SlaWeekRow,
    StatusRow,
    TicketCounts,
)


def _day_start(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ticket_counts(self, tenant_id: UUID, now: datetime) -> TicketCounts:
        day_start = _day_start(now)
        row = (
            await self._session.execute(
                text("""
                    SELECT
                      count(*) FILTER (WHERE NOT status.terminal_flag) AS open_now,
                      count(*) FILTER (
                        WHERE ticket.created_at >= :day_start AND ticket.created_at < :now
                      ) AS new_today,
                      count(*) FILTER (
                        WHERE ticket.created_at >= :previous_day_start
                          AND ticket.created_at < :previous_now
                      ) AS new_previous,
                      count(*) FILTER (
                        WHERE ticket.resolved_at >= :day_start AND ticket.resolved_at < :now
                      ) AS resolved_today,
                      count(*) FILTER (
                        WHERE ticket.resolved_at >= :previous_day_start
                          AND ticket.resolved_at < :previous_now
                      ) AS resolved_previous
                    FROM itsm.ticket AS ticket
                    JOIN config.workflow_status AS status
                      ON status.status_id = ticket.status_id
                    WHERE ticket.tenant_id = :tenant_id
                """),
                {
                    "tenant_id": tenant_id,
                    "now": now,
                    "day_start": day_start,
                    "previous_now": now - timedelta(hours=24),
                    "previous_day_start": day_start - timedelta(hours=24),
                },
            )
        ).one()
        return TicketCounts(
            open_now=row.open_now,
            new_today=row.new_today,
            new_yesterday_same_elapsed_window=row.new_previous,
            resolved_today=row.resolved_today,
            resolved_yesterday_same_elapsed_window=row.resolved_previous,
        )

    async def sla_ticket_counts(self, tenant_id: UUID, now: datetime) -> tuple[int, int]:
        """Distinct open tickets: (with any breached SLA row, due today)."""
        day_start = _day_start(now)
        row = (
            await self._session.execute(
                text("""
                    SELECT
                      count(*) FILTER (
                        WHERE EXISTS (
                          SELECT 1 FROM itsm.ticket_sla AS sla
                          WHERE sla.ticket_id = ticket.ticket_id
                            AND sla.tenant_id = ticket.tenant_id
                            AND sla.breached_at IS NOT NULL
                        )
                      ) AS breached_open,
                      count(*) FILTER (
                        WHERE EXISTS (
                          SELECT 1 FROM itsm.ticket_sla AS sla
                          WHERE sla.ticket_id = ticket.ticket_id
                            AND sla.tenant_id = ticket.tenant_id
                            AND sla.completed_at IS NULL
                            AND sla.breached_at IS NULL
                            AND sla.paused_at IS NULL
                            AND sla.target_at >= :day_start
                            AND sla.target_at < :day_end
                        )
                      ) AS due_today
                    FROM itsm.ticket AS ticket
                    JOIN config.workflow_status AS status
                      ON status.status_id = ticket.status_id
                    WHERE ticket.tenant_id = :tenant_id
                      AND NOT status.terminal_flag
                """),
                {
                    "tenant_id": tenant_id,
                    "day_start": day_start,
                    "day_end": day_start + timedelta(hours=24),
                },
            )
        ).one()
        return (row.breached_open, row.due_today)

    async def status_distribution(self, tenant_id: UUID) -> list[StatusRow]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT status.status_name, count(*) AS ticket_count
                    FROM itsm.ticket AS ticket
                    JOIN config.workflow_status AS status
                      ON status.status_id = ticket.status_id
                    WHERE ticket.tenant_id = :tenant_id
                      AND NOT status.terminal_flag
                    GROUP BY status.status_name
                    ORDER BY ticket_count DESC, status.status_name
                """),
                {"tenant_id": tenant_id},
            )
        ).all()
        return [StatusRow(status_name=row.status_name, count=row.ticket_count) for row in rows]

    async def sla_compliance_week(self, tenant_id: UUID, now: datetime) -> SlaWeekRow:
        week_start = _day_start(now) - timedelta(days=6)
        row = (
            await self._session.execute(
                text("""
                    SELECT
                      count(*) FILTER (
                        WHERE completed_at IS NOT NULL AND breached_at IS NULL
                          AND completed_at >= :week_start AND completed_at < :now
                      ) AS met,
                      count(*) FILTER (
                        WHERE breached_at IS NOT NULL
                          AND breached_at >= :week_start AND breached_at < :now
                      ) AS breached
                    FROM itsm.ticket_sla
                    WHERE tenant_id = :tenant_id
                """),
                {"tenant_id": tenant_id, "week_start": week_start, "now": now},
            )
        ).one()
        return SlaWeekRow(met=row.met, breached=row.breached)

    async def recent_activity(self, tenant_id: UUID, limit: int) -> list[ActivityRow]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT event.event_id, event.event_type, event.created_at,
                      ticket.ticket_key, actor.display_name AS actor_name
                    FROM itsm.ticket_event AS event
                    JOIN itsm.ticket AS ticket
                      ON ticket.ticket_id = event.ticket_id
                     AND ticket.tenant_id = event.tenant_id
                    LEFT JOIN identity.app_user AS actor
                      ON actor.user_id = event.actor_user_id
                     AND actor.tenant_id = event.tenant_id
                    WHERE event.tenant_id = :tenant_id
                    ORDER BY event.event_id DESC
                    LIMIT :limit
                """),
                {"tenant_id": tenant_id, "limit": limit},
            )
        ).all()
        return [
            ActivityRow(
                event_id=cast("int", row.event_id),
                ticket_key=row.ticket_key,
                event_type=row.event_type,
                actor_name=row.actor_name,
                created_at=row.created_at,
            )
            for row in rows
        ]
