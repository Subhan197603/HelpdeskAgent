"""Business-calendar arithmetic and deterministic SLA lifecycle tests."""

from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import cast
from uuid import UUID, uuid4

import pytest

from apps.api.app.sla.calendar import BusinessCalendar, CalendarConfigurationError
from apps.api.app.sla.models import (
    BusinessCalendarVersion,
    CalendarException,
    CalendarExceptionType,
    SlaDefinitionVersion,
    SlaGoalVersion,
    SlaInputEvent,
    SlaMetric,
    SlaState,
    TicketFacts,
    TicketSla,
    WorkingPeriod,
)
from apps.api.app.sla.repository import SlaRepository
from apps.api.app.sla.service import SlaConfigurationError, SlaEngine

TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("20000000-0000-0000-0000-000000000001")
TICKET_ID = UUID("30000000-0000-0000-0000-000000000001")
CALENDAR_ID = UUID("40000000-0000-0000-0000-000000000001")
CALENDAR_VERSION_ID = UUID("41000000-0000-0000-0000-000000000001")
MONDAY = datetime(2026, 1, 5, 9, tzinfo=UTC)


def _calendar(
    *,
    periods: tuple[WorkingPeriod, ...] | None = None,
    exceptions: tuple[CalendarException, ...] = (),
    timezone: str = "Europe/London",
    always_open: bool = False,
) -> BusinessCalendarVersion:
    return BusinessCalendarVersion(
        business_calendar_version_id=CALENDAR_VERSION_ID,
        calendar_id=CALENDAR_ID,
        timezone_name=timezone,
        twenty_four_seven=always_open,
        working_periods=periods
        or tuple(WorkingPeriod(day, time(9), time(17)) for day in range(1, 6)),
        exceptions=exceptions,
    )


def test_business_hours_skip_lunch_weekends_holiday_and_start_outside_hours() -> None:
    calendar = BusinessCalendar(
        _calendar(
            periods=tuple(
                period
                for day in range(1, 6)
                for period in (
                    WorkingPeriod(day, time(9), time(12)),
                    WorkingPeriod(day, time(13), time(17)),
                )
            ),
            exceptions=(
                CalendarException(date(2026, 1, 5), CalendarExceptionType.CLOSED),
                CalendarException(
                    date(2026, 1, 6),
                    CalendarExceptionType.CUSTOM_HOURS,
                    time(10),
                    time(14),
                ),
            ),
        )
    )
    friday_after_hours = datetime(2026, 1, 2, 18, tzinfo=UTC)
    assert calendar.add_business_seconds(friday_after_hours, 3 * 3600) == datetime(
        2026, 1, 6, 13, tzinfo=UTC
    )
    assert (
        calendar.business_seconds_between(
            datetime(2026, 1, 6, 9, tzinfo=UTC),
            datetime(2026, 1, 6, 15, tzinfo=UTC),
        )
        == 4 * 3600
    )


def test_dst_boundaries_use_real_elapsed_seconds_and_24x7_is_continuous() -> None:
    transition_period = (WorkingPeriod(7, time(0), time(4)),)
    calendar = BusinessCalendar(_calendar(periods=transition_period))
    assert (
        calendar.business_seconds_between(
            datetime(2026, 3, 29, 0, tzinfo=UTC),
            datetime(2026, 3, 29, 4, tzinfo=UTC),
        )
        == 3 * 3600
    )
    assert (
        calendar.business_seconds_between(
            datetime(2026, 10, 24, 23, tzinfo=UTC),
            datetime(2026, 10, 25, 4, tzinfo=UTC),
        )
        == 5 * 3600
    )

    always_open = BusinessCalendar(_calendar(always_open=True))
    start = datetime(2026, 3, 28, 12, tzinfo=UTC)
    assert always_open.add_business_seconds(start, 24 * 3600) == datetime(
        2026, 3, 29, 12, tzinfo=UTC
    )


def test_invalid_timezone_and_overlapping_periods_fail_closed() -> None:
    with pytest.raises(CalendarConfigurationError, match="timezone"):
        BusinessCalendar(_calendar(timezone="Invalid/Timezone"))
    with pytest.raises(CalendarConfigurationError, match="overlap"):
        BusinessCalendar(
            _calendar(
                periods=(
                    WorkingPeriod(1, time(9), time(12)),
                    WorkingPeriod(1, time(11), time(13)),
                )
            )
        )


class FakeSlaRepository:
    def __init__(self) -> None:
        self.ticket_value = TicketFacts(
            TICKET_ID,
            TENANT_ID,
            PROJECT_ID,
            None,
            "INCIDENT",
            "P2",
            "IN_PROGRESS",
            "IN_PROGRESS",
            MONDAY,
            None,
            None,
        )
        self.first_definition = _definition(SlaMetric.FIRST_RESPONSE, 1)
        self.resolution_definition = _definition(
            SlaMetric.RESOLUTION, 2, [{"status_code": "WAITING_FOR_CUSTOMER"}]
        )
        self.first_goal = _goal(self.first_definition, 1, 4 * 3600, 3600, 999)
        self.resolution_goal = _goal(self.resolution_definition, 2, 8 * 3600, 2 * 3600, 999)
        self.p1_resolution_goal = _goal(
            self.resolution_definition,
            3,
            4 * 3600,
            3600,
            10,
            {"priority_code": "P1"},
        )
        self.slas: list[TicketSla] = []
        self.event_keys: set[tuple[UUID, str]] = set()
        self.events: list[tuple[str, str]] = []
        self.outbox: list[tuple[str, str]] = []
        self.statuses = {
            "IN_PROGRESS": "IN_PROGRESS",
            "WAITING_FOR_CUSTOMER": "WAITING",
            "RESOLVED": "DONE",
        }

    async def ticket(self, tenant_id: UUID, ticket_id: UUID) -> TicketFacts | None:
        return self.ticket_value if (tenant_id, ticket_id) == (TENANT_ID, TICKET_ID) else None

    async def status_category(self, ticket_id: UUID, status_code: str) -> str | None:
        return self.statuses.get(status_code) if ticket_id == TICKET_ID else None

    async def definitions(
        self, tenant_id: UUID, project_id: UUID, effective_at: datetime
    ) -> list[SlaDefinitionVersion]:
        del effective_at
        return (
            [self.first_definition, self.resolution_definition]
            if (tenant_id, project_id) == (TENANT_ID, PROJECT_ID)
            else []
        )

    async def goals(
        self, definition_version_id: UUID, effective_at: datetime
    ) -> list[SlaGoalVersion]:
        del effective_at
        if definition_version_id == self.first_definition.sla_definition_version_id:
            return [self.first_goal]
        return [self.p1_resolution_goal, self.resolution_goal]

    async def calendar(self, version_id: UUID) -> BusinessCalendarVersion | None:
        return _calendar() if version_id == CALENDAR_VERSION_ID else None

    async def ticket_slas(
        self, tenant_id: UUID, ticket_id: UUID, *, lock: bool = False
    ) -> list[TicketSla]:
        del lock
        return [
            sla for sla in self.slas if sla.tenant_id == tenant_id and sla.ticket_id == ticket_id
        ]

    async def due_slas(self, tenant_id: UUID, due_at: datetime, limit: int) -> list[TicketSla]:
        return [
            sla
            for sla in self.slas
            if sla.tenant_id == tenant_id
            and sla.state is SlaState.RUNNING
            and (sla.target_at <= due_at or (sla.warning_at or sla.target_at) <= due_at)
        ][:limit]

    async def create_sla(
        self,
        ticket: TicketFacts,
        definition: SlaDefinitionVersion,
        goal: SlaGoalVersion,
        started_at: datetime,
        target_at: datetime,
        warning_at: datetime | None,
    ) -> TicketSla | None:
        if any(
            item.definition.sla_definition_id == definition.sla_definition_id for item in self.slas
        ):
            return None
        value = TicketSla(
            uuid4(),
            ticket.tenant_id,
            ticket.ticket_id,
            definition,
            goal,
            SlaState.RUNNING,
            started_at,
            target_at,
            warning_at,
            None,
            0,
            None,
            None,
            0,
            goal.target_seconds,
            started_at,
            None,
            1,
        )
        self.slas.append(value)
        return value

    async def save(self, sla: TicketSla, expected_row_version: int) -> TicketSla:
        current = next(item for item in self.slas if item.ticket_sla_id == sla.ticket_sla_id)
        if current.row_version != expected_row_version:
            raise RuntimeError("conflict")
        saved = replace(sla, row_version=expected_row_version + 1)
        self.slas[self.slas.index(current)] = saved
        return saved

    async def record_event(
        self,
        sla: TicketSla,
        event_type: str,
        event_at: datetime,
        event_key: str,
        data: dict[str, object],
    ) -> bool:
        del event_at, data
        key = (sla.ticket_sla_id, event_key)
        if key in self.event_keys:
            return False
        if event_type in {"WARNING", "BREACHED"} and any(
            item[0] == event_type and item[1] == str(sla.ticket_sla_id) for item in self.events
        ):
            return False
        self.event_keys.add(key)
        self.events.append((event_type, str(sla.ticket_sla_id)))
        return True

    async def emit_outbox(
        self,
        sla: TicketSla,
        event_type: str,
        payload: dict[str, object],
        deduplication_key: str,
    ) -> None:
        del sla, payload
        if (event_type, deduplication_key) not in self.outbox:
            self.outbox.append((event_type, deduplication_key))

    async def mark_first_response(
        self, tenant_id: UUID, ticket_id: UUID, responded_at: datetime
    ) -> None:
        if (tenant_id, ticket_id) == (TENANT_ID, TICKET_ID):
            self.ticket_value = replace(self.ticket_value, first_response_at=responded_at)


@pytest.mark.anyio
async def test_sla_start_is_idempotent_and_pins_exact_versions() -> None:
    repo = FakeSlaRepository()
    engine = SlaEngine(cast(SlaRepository, repo))
    event = _event("START_SLA", MONDAY)
    await engine.process(event)
    await engine.process(event)
    assert len(repo.slas) == 2
    assert {sla.goal.sla_goal_version_id for sla in repo.slas} == {
        repo.first_goal.sla_goal_version_id,
        repo.resolution_goal.sla_goal_version_id,
    }
    assert all(sla.goal.business_calendar_version_id == CALENDAR_VERSION_ID for sla in repo.slas)
    assert [event_type for event_type, _ in repo.events].count("STARTED") == 2


@pytest.mark.anyio
async def test_first_response_and_resolution_pause_resume_stop_and_met() -> None:
    repo = FakeSlaRepository()
    engine = SlaEngine(cast(SlaRepository, repo))
    await engine.process(_event("START_SLA", MONDAY))
    await engine.process(_event("AGENT_PUBLIC_RESPONSE_ADDED", MONDAY.replace(hour=10)))
    first = _runtime(repo, SlaMetric.FIRST_RESPONSE)
    assert first.state is SlaState.COMPLETED
    assert first.elapsed_working_seconds == 3600

    await engine.process(
        _event(
            "TICKET_WORKFLOW_TRANSITIONED",
            MONDAY.replace(hour=11),
            {"from_status": "IN_PROGRESS", "to_status": "WAITING_FOR_CUSTOMER"},
        )
    )
    paused = _runtime(repo, SlaMetric.RESOLUTION)
    assert paused.state is SlaState.PAUSED
    assert paused.elapsed_working_seconds == 2 * 3600

    tuesday = datetime(2026, 1, 6, 9, tzinfo=UTC)
    await engine.process(
        _event(
            "TICKET_WORKFLOW_TRANSITIONED",
            tuesday,
            {"from_status": "WAITING_FOR_CUSTOMER", "to_status": "IN_PROGRESS"},
        )
    )
    resumed = _runtime(repo, SlaMetric.RESOLUTION)
    assert resumed.state is SlaState.RUNNING
    assert resumed.target_at == datetime(2026, 1, 6, 15, tzinfo=UTC)
    assert resumed.accumulated_pause_seconds == 22 * 3600

    resolved_at = datetime(2026, 1, 6, 12, tzinfo=UTC)
    await engine.process(
        _event(
            "TICKET_WORKFLOW_TRANSITIONED",
            resolved_at,
            {"from_status": "IN_PROGRESS", "to_status": "RESOLVED"},
        )
    )
    completed = _runtime(repo, SlaMetric.RESOLUTION)
    assert completed.state is SlaState.COMPLETED
    assert completed.completed_at == resolved_at
    assert {"PAUSED", "RESUMED", "STOPPED", "MET"} <= {event_type for event_type, _ in repo.events}


@pytest.mark.anyio
async def test_warning_and_breach_are_emitted_once_across_retries() -> None:
    repo = FakeSlaRepository()
    engine = SlaEngine(cast(SlaRepository, repo))
    await engine.process(_event("START_SLA", MONDAY))
    resolution = _runtime(repo, SlaMetric.RESOLUTION)
    repo.slas = [resolution]
    await engine.evaluate_due(TENANT_ID, MONDAY.replace(hour=15))
    await engine.evaluate_due(TENANT_ID, MONDAY.replace(hour=15))
    await engine.evaluate_due(TENANT_ID, MONDAY.replace(hour=17))
    await engine.evaluate_due(TENANT_ID, MONDAY.replace(hour=17))
    assert [event_type for event_type, _ in repo.events].count("WARNING") == 1
    assert [event_type for event_type, _ in repo.events].count("BREACHED") == 1
    assert [event_type for event_type, _ in repo.outbox].count("SLA_WARNING") == 1
    assert [event_type for event_type, _ in repo.outbox].count("SLA_BREACHED") == 1
    assert _runtime(repo, SlaMetric.RESOLUTION).state is SlaState.BREACHED


@pytest.mark.anyio
async def test_priority_change_recalculates_goal_and_reopen_resumes_clock() -> None:
    repo = FakeSlaRepository()
    engine = SlaEngine(cast(SlaRepository, repo))
    await engine.process(_event("START_SLA", MONDAY))
    repo.ticket_value = replace(repo.ticket_value, priority_code="P1")
    await engine.process(_event("TICKET_PRIORITY_CHANGED", MONDAY.replace(hour=10)))
    resolution = _runtime(repo, SlaMetric.RESOLUTION)
    assert resolution.goal.sla_goal_version_id == repo.p1_resolution_goal.sla_goal_version_id
    assert resolution.target_at == MONDAY.replace(hour=13)

    await engine.process(
        _event(
            "TICKET_WORKFLOW_TRANSITIONED",
            MONDAY.replace(hour=11),
            {"from_status": "IN_PROGRESS", "to_status": "RESOLVED"},
        )
    )
    await engine.process(
        _event(
            "TICKET_WORKFLOW_TRANSITIONED",
            MONDAY.replace(hour=12),
            {"from_status": "RESOLVED", "to_status": "IN_PROGRESS"},
        )
    )
    reopened = _runtime(repo, SlaMetric.RESOLUTION)
    assert reopened.state is SlaState.RUNNING
    assert reopened.completed_at is None
    assert reopened.target_at == MONDAY.replace(hour=14)


@pytest.mark.anyio
async def test_ambiguous_goal_tie_fails_closed() -> None:
    repo = FakeSlaRepository()
    repo.resolution_goal = replace(repo.resolution_goal, priority_order=10)
    repo.ticket_value = replace(repo.ticket_value, priority_code="P1")
    with pytest.raises(SlaConfigurationError, match="ambiguous"):
        await SlaEngine(cast(SlaRepository, repo)).process(_event("START_SLA", MONDAY))


def _definition(metric: SlaMetric, suffix: int, pause: object = None) -> SlaDefinitionVersion:
    return SlaDefinitionVersion(
        UUID(f"50000000-0000-0000-0000-{suffix:012d}"),
        UUID(f"51000000-0000-0000-0000-{suffix:012d}"),
        metric,
        [] if pause is None else pause,
    )


def _goal(
    definition: SlaDefinitionVersion,
    suffix: int,
    target: int,
    warning: int,
    priority: int,
    conditions: object = None,
) -> SlaGoalVersion:
    return SlaGoalVersion(
        UUID(f"60000000-0000-0000-0000-{suffix:012d}"),
        UUID(f"61000000-0000-0000-0000-{suffix:012d}"),
        definition.sla_definition_version_id,
        CALENDAR_VERSION_ID,
        {} if conditions is None else conditions,
        target,
        warning,
        priority,
    )


def _event(
    event_type: str, occurred_at: datetime, payload: dict[str, object] | None = None
) -> SlaInputEvent:
    return SlaInputEvent(uuid4(), TENANT_ID, TICKET_ID, event_type, payload or {}, occurred_at)


def _runtime(repo: FakeSlaRepository, metric: SlaMetric) -> TicketSla:
    return next(sla for sla in repo.slas if sla.definition.metric is metric)
