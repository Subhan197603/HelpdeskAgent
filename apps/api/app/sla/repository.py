"""Narrow PostgreSQL persistence for SLA configuration and runtime state."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.sla.models import (
    BusinessCalendarVersion,
    CalendarException,
    CalendarExceptionType,
    SlaDefinitionVersion,
    SlaGoalVersion,
    SlaMetric,
    SlaState,
    TicketFacts,
    TicketSla,
    WorkingPeriod,
)


class SlaRepository:
    """SQL adapter constrained to calendar and SLA use cases."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ticket(self, tenant_id: UUID, ticket_id: UUID) -> TicketFacts | None:
        row = (
            (
                await self._session.execute(
                    text("""
                    SELECT ticket.ticket_id,ticket.tenant_id,ticket.project_id,
                           ticket.service_node_id,work_type.work_type_code,
                           ticket.priority_code,status.status_code,status.status_category,
                           ticket.created_at,ticket.first_response_at,ticket.resolved_at
                    FROM itsm.ticket AS ticket
                    JOIN config.work_type AS work_type
                      ON work_type.work_type_id=ticket.work_type_id
                    JOIN config.workflow_status AS status
                      ON status.status_id=ticket.status_id
                    WHERE ticket.tenant_id=:tenant_id AND ticket.ticket_id=:ticket_id
                """),
                    {"tenant_id": tenant_id, "ticket_id": ticket_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _ticket(row) if row else None

    async def status_category(self, ticket_id: UUID, status_code: str) -> str | None:
        return (
            await self._session.execute(
                text("""
                    SELECT status.status_category
                    FROM itsm.ticket AS ticket
                    JOIN config.workflow_status AS status
                      ON status.workflow_version_id=ticket.workflow_version_id
                    WHERE ticket.ticket_id=:ticket_id AND status.status_code=:status_code
                """),
                {"ticket_id": ticket_id, "status_code": status_code},
            )
        ).scalar_one_or_none()

    async def definitions(
        self, tenant_id: UUID, project_id: UUID, effective_at: datetime
    ) -> list[SlaDefinitionVersion]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT definition.sla_definition_id,
                           version.sla_definition_version_id,
                           version.metric_code,version.pause_condition_json
                    FROM config.sla_definition AS definition
                    JOIN config.sla_definition_version AS version
                      ON version.sla_definition_id=definition.sla_definition_id
                    WHERE definition.tenant_id=:tenant_id
                      AND definition.project_id=:project_id
                      AND definition.active_flag
                      AND version.version_status='PUBLISHED'
                      AND (version.effective_from IS NULL OR version.effective_from<=:effective_at)
                      AND (version.effective_to IS NULL OR version.effective_to>:effective_at)
                    ORDER BY definition.sla_definition_id,version.version_number DESC
                """),
                {
                    "tenant_id": tenant_id,
                    "project_id": project_id,
                    "effective_at": effective_at,
                },
            )
        ).mappings()
        return [
            SlaDefinitionVersion(
                sla_definition_id=row.sla_definition_id,
                sla_definition_version_id=row.sla_definition_version_id,
                metric=SlaMetric(row.metric_code),
                pause_conditions=row.pause_condition_json,
            )
            for row in rows
            if row.metric_code in {SlaMetric.FIRST_RESPONSE, SlaMetric.RESOLUTION}
        ]

    async def goals(
        self, definition_version_id: UUID, effective_at: datetime
    ) -> list[SlaGoalVersion]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT goal.sla_goal_id,version.sla_goal_version_id,
                           version.sla_definition_version_id,
                           version.business_calendar_version_id,
                           version.match_condition_json,version.target_minutes,
                           version.warning_minutes,version.priority_order
                    FROM config.sla_goal_version AS version
                    JOIN config.sla_goal AS goal ON goal.sla_goal_id=version.sla_goal_id
                    WHERE version.sla_definition_version_id=:definition_version_id
                      AND goal.active_flag
                      AND version.version_status='PUBLISHED'
                      AND (version.effective_from IS NULL OR version.effective_from<=:effective_at)
                      AND (version.effective_to IS NULL OR version.effective_to>:effective_at)
                    ORDER BY version.priority_order,goal.sla_goal_id,version.version_number DESC
                """),
                {
                    "definition_version_id": definition_version_id,
                    "effective_at": effective_at,
                },
            )
        ).mappings()
        return [_goal(row) for row in rows]

    async def calendar(self, version_id: UUID) -> BusinessCalendarVersion | None:
        parent = (
            (
                await self._session.execute(
                    text("""
                    SELECT version.business_calendar_version_id,version.calendar_id,
                           version.timezone_name,version.twenty_four_seven_flag
                    FROM config.business_calendar_version AS version
                    WHERE version.business_calendar_version_id=:version_id
                      AND version.version_status IN ('PUBLISHED','RETIRED')
                """),
                    {"version_id": version_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if parent is None:
            return None
        periods = (
            await self._session.execute(
                text("""
                    SELECT iso_day_of_week,start_local_time,end_local_time
                    FROM config.calendar_working_period
                    WHERE business_calendar_version_id=:version_id
                    ORDER BY iso_day_of_week,start_local_time,end_local_time
                """),
                {"version_id": version_id},
            )
        ).mappings()
        exceptions = (
            await self._session.execute(
                text("""
                    SELECT exception_date,exception_type,start_local_time,end_local_time
                    FROM config.calendar_exception
                    WHERE business_calendar_version_id=:version_id
                    ORDER BY exception_date,start_local_time NULLS FIRST
                """),
                {"version_id": version_id},
            )
        ).mappings()
        return BusinessCalendarVersion(
            business_calendar_version_id=parent.business_calendar_version_id,
            calendar_id=parent.calendar_id,
            timezone_name=parent.timezone_name,
            twenty_four_seven=parent.twenty_four_seven_flag,
            working_periods=tuple(
                WorkingPeriod(row.iso_day_of_week, row.start_local_time, row.end_local_time)
                for row in periods
            ),
            exceptions=tuple(
                CalendarException(
                    row.exception_date,
                    CalendarExceptionType(row.exception_type),
                    row.start_local_time,
                    row.end_local_time,
                )
                for row in exceptions
            ),
        )

    async def ticket_slas(
        self, tenant_id: UUID, ticket_id: UUID, *, lock: bool = False
    ) -> list[TicketSla]:
        lock_sql = " FOR UPDATE OF runtime" if lock else ""
        rows = (
            await self._session.execute(
                text(
                    _SLA_SELECT
                    + " WHERE runtime.tenant_id=:tenant_id AND runtime.ticket_id=:ticket_id"
                    + lock_sql
                ),
                {"tenant_id": tenant_id, "ticket_id": ticket_id},
            )
        ).mappings()
        return [_sla(row) for row in rows]

    async def due_slas(self, tenant_id: UUID, due_at: datetime, limit: int) -> list[TicketSla]:
        rows = (
            await self._session.execute(
                text(
                    _SLA_SELECT
                    + """
                    WHERE runtime.tenant_id=:tenant_id
                      AND runtime.state_code='RUNNING'
                      AND (
                        runtime.target_at<=:due_at OR
                        (runtime.warning_emitted_at IS NULL AND runtime.warning_at<=:due_at)
                      )
                    ORDER BY runtime.target_at,runtime.ticket_sla_id
                    LIMIT :limit FOR UPDATE OF runtime SKIP LOCKED
                    """
                ),
                {"tenant_id": tenant_id, "due_at": due_at, "limit": limit},
            )
        ).mappings()
        return [_sla(row) for row in rows]

    async def create_sla(
        self,
        ticket: TicketFacts,
        definition: SlaDefinitionVersion,
        goal: SlaGoalVersion,
        started_at: datetime,
        target_at: datetime,
        warning_at: datetime | None,
    ) -> TicketSla | None:
        ticket_sla_id = (
            await self._session.execute(
                text("""
                    INSERT INTO itsm.ticket_sla(
                      tenant_id,ticket_id,sla_definition_id,sla_goal_id,
                      sla_goal_version_id,business_calendar_version_id,state_code,
                      started_at,target_at,warning_at,elapsed_working_seconds,
                      remaining_working_seconds,last_calculated_at)
                    VALUES (:tenant_id,:ticket_id,:definition_id,:goal_id,:goal_version_id,
                      :calendar_version_id,'RUNNING',:started_at,:target_at,:warning_at,
                      0,:remaining,:started_at)
                    ON CONFLICT (ticket_id,sla_definition_id) DO NOTHING
                    RETURNING ticket_sla_id
                """),
                {
                    "tenant_id": ticket.tenant_id,
                    "ticket_id": ticket.ticket_id,
                    "definition_id": definition.sla_definition_id,
                    "goal_id": goal.sla_goal_id,
                    "goal_version_id": goal.sla_goal_version_id,
                    "calendar_version_id": goal.business_calendar_version_id,
                    "started_at": started_at,
                    "target_at": target_at,
                    "warning_at": warning_at,
                    "remaining": goal.target_seconds,
                },
            )
        ).scalar_one_or_none()
        if ticket_sla_id is None:
            return None
        rows = await self.ticket_slas(ticket.tenant_id, ticket.ticket_id, lock=True)
        return next(row for row in rows if row.ticket_sla_id == ticket_sla_id)

    async def save(self, sla: TicketSla, expected_row_version: int) -> TicketSla:
        updated = (
            await self._session.execute(
                text("""
                    UPDATE itsm.ticket_sla SET
                      sla_goal_id=:goal_id,
                      sla_goal_version_id=:goal_version_id,
                      business_calendar_version_id=:calendar_version_id,
                      state_code=:state_code,target_at=:target_at,warning_at=:warning_at,
                      paused_at=:paused_at,
                      accumulated_pause_seconds=:accumulated_pause_seconds,
                      completed_at=:completed_at,breached_at=:breached_at,
                      elapsed_working_seconds=:elapsed_working_seconds,
                      remaining_working_seconds=:remaining_working_seconds,
                      last_calculated_at=:last_calculated_at,
                      warning_emitted_at=:warning_emitted_at,row_version=row_version+1
                    WHERE ticket_sla_id=:ticket_sla_id AND tenant_id=:tenant_id
                      AND row_version=:expected_row_version
                    RETURNING row_version
                """),
                {
                    "ticket_sla_id": sla.ticket_sla_id,
                    "tenant_id": sla.tenant_id,
                    "goal_id": sla.goal.sla_goal_id,
                    "goal_version_id": sla.goal.sla_goal_version_id,
                    "calendar_version_id": sla.goal.business_calendar_version_id,
                    "state_code": sla.state,
                    "target_at": sla.target_at,
                    "warning_at": sla.warning_at,
                    "paused_at": sla.paused_at,
                    "accumulated_pause_seconds": sla.accumulated_pause_seconds,
                    "completed_at": sla.completed_at,
                    "breached_at": sla.breached_at,
                    "elapsed_working_seconds": sla.elapsed_working_seconds,
                    "remaining_working_seconds": sla.remaining_working_seconds,
                    "last_calculated_at": sla.last_calculated_at,
                    "warning_emitted_at": sla.warning_emitted_at,
                    "expected_row_version": expected_row_version,
                },
            )
        ).scalar_one_or_none()
        if updated is None:
            raise RuntimeError("Concurrent SLA update detected.")
        return TicketSla(
            ticket_sla_id=sla.ticket_sla_id,
            tenant_id=sla.tenant_id,
            ticket_id=sla.ticket_id,
            definition=sla.definition,
            goal=sla.goal,
            state=sla.state,
            started_at=sla.started_at,
            target_at=sla.target_at,
            warning_at=sla.warning_at,
            paused_at=sla.paused_at,
            accumulated_pause_seconds=sla.accumulated_pause_seconds,
            completed_at=sla.completed_at,
            breached_at=sla.breached_at,
            elapsed_working_seconds=sla.elapsed_working_seconds,
            remaining_working_seconds=sla.remaining_working_seconds,
            last_calculated_at=sla.last_calculated_at,
            warning_emitted_at=sla.warning_emitted_at,
            row_version=updated,
        )

    async def record_event(
        self,
        sla: TicketSla,
        event_type: str,
        event_at: datetime,
        event_key: str,
        data: dict[str, Any],
    ) -> bool:
        inserted = (
            await self._session.execute(
                text("""
                    SELECT itsm.record_sla_event(
                      :ticket_sla_id,CAST(:event_type AS varchar),:event_at,
                      CAST(:event_key AS varchar),CAST(:data AS jsonb))
                """),
                {
                    "ticket_sla_id": sla.ticket_sla_id,
                    "event_type": event_type,
                    "event_at": event_at,
                    "event_key": event_key,
                    "data": json.dumps(data),
                },
            )
        ).scalar_one()
        return bool(inserted)

    async def emit_outbox(
        self, sla: TicketSla, event_type: str, payload: dict[str, Any], deduplication_key: str
    ) -> None:
        await self._session.execute(
            text("""
                INSERT INTO integration.outbox_event(
                  tenant_id,aggregate_type,aggregate_id,event_type,payload_json,
                  deduplication_key)
                VALUES (:tenant_id,'TICKET_SLA',CAST(:sla_id AS varchar),:event_type,
                  CAST(:payload AS jsonb),:deduplication_key)
                ON CONFLICT DO NOTHING
            """),
            {
                "tenant_id": sla.tenant_id,
                "sla_id": sla.ticket_sla_id,
                "event_type": event_type,
                "payload": json.dumps(payload),
                "deduplication_key": deduplication_key,
            },
        )

    async def mark_first_response(
        self, tenant_id: UUID, ticket_id: UUID, responded_at: datetime
    ) -> None:
        await self._session.execute(
            text("""
                SELECT itsm.record_first_response(:tenant_id,:ticket_id,:responded_at)
            """),
            {"tenant_id": tenant_id, "ticket_id": ticket_id, "responded_at": responded_at},
        )


_SLA_SELECT = """
    SELECT runtime.ticket_sla_id,runtime.tenant_id,runtime.ticket_id,
           runtime.state_code,runtime.started_at,runtime.target_at,runtime.warning_at,
           runtime.paused_at,runtime.accumulated_pause_seconds,runtime.completed_at,
           runtime.breached_at,runtime.elapsed_working_seconds,
           runtime.remaining_working_seconds,runtime.last_calculated_at,
           runtime.warning_emitted_at,runtime.row_version,
           definition.sla_definition_id,definition_version.sla_definition_version_id,
           definition_version.metric_code,definition_version.pause_condition_json,
           goal.sla_goal_id,goal_version.sla_goal_version_id,
           goal_version.business_calendar_version_id,goal_version.match_condition_json,
           goal_version.target_minutes,goal_version.warning_minutes,
           goal_version.priority_order
    FROM itsm.ticket_sla AS runtime
    JOIN config.sla_definition AS definition
      ON definition.sla_definition_id=runtime.sla_definition_id
    JOIN config.sla_goal_version AS goal_version
      ON goal_version.sla_goal_version_id=runtime.sla_goal_version_id
    JOIN config.sla_definition_version AS definition_version
      ON definition_version.sla_definition_version_id=goal_version.sla_definition_version_id
    JOIN config.sla_goal AS goal ON goal.sla_goal_id=runtime.sla_goal_id
"""


def _ticket(row: Any) -> TicketFacts:
    return TicketFacts(
        ticket_id=row.ticket_id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        service_node_id=row.service_node_id,
        work_type_code=row.work_type_code,
        priority_code=row.priority_code,
        status_code=row.status_code,
        status_category=row.status_category,
        created_at=row.created_at,
        first_response_at=row.first_response_at,
        resolved_at=row.resolved_at,
    )


def _goal(row: Any) -> SlaGoalVersion:
    return SlaGoalVersion(
        sla_goal_id=row.sla_goal_id,
        sla_goal_version_id=row.sla_goal_version_id,
        sla_definition_version_id=row.sla_definition_version_id,
        business_calendar_version_id=row.business_calendar_version_id,
        match_conditions=row.match_condition_json,
        target_seconds=row.target_minutes * 60,
        warning_seconds=row.warning_minutes * 60 if row.warning_minutes is not None else None,
        priority_order=row.priority_order,
    )


def _sla(row: Any) -> TicketSla:
    definition = SlaDefinitionVersion(
        sla_definition_id=row.sla_definition_id,
        sla_definition_version_id=row.sla_definition_version_id,
        metric=SlaMetric(row.metric_code),
        pause_conditions=row.pause_condition_json,
    )
    return TicketSla(
        ticket_sla_id=row.ticket_sla_id,
        tenant_id=row.tenant_id,
        ticket_id=row.ticket_id,
        definition=definition,
        goal=_goal(row),
        state=SlaState(row.state_code),
        started_at=row.started_at,
        target_at=row.target_at,
        warning_at=row.warning_at,
        paused_at=row.paused_at,
        accumulated_pause_seconds=row.accumulated_pause_seconds,
        completed_at=row.completed_at,
        breached_at=row.breached_at,
        elapsed_working_seconds=row.elapsed_working_seconds,
        remaining_working_seconds=row.remaining_working_seconds,
        last_calculated_at=row.last_calculated_at,
        warning_emitted_at=row.warning_emitted_at,
        row_version=row.row_version,
    )
