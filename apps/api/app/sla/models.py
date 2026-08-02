"""Transport-independent business-calendar and SLA runtime records."""

from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Any
from uuid import UUID


class CalendarExceptionType(StrEnum):
    CLOSED = "CLOSED"
    CUSTOM_HOURS = "CUSTOM_HOURS"


class SlaMetric(StrEnum):
    FIRST_RESPONSE = "TIME_TO_FIRST_RESPONSE"
    RESOLUTION = "TIME_TO_RESOLUTION"


class SlaState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True, slots=True)
class WorkingPeriod:
    iso_day_of_week: int
    start_local_time: time
    end_local_time: time


@dataclass(frozen=True, slots=True)
class CalendarException:
    exception_date: date
    exception_type: CalendarExceptionType
    start_local_time: time | None = None
    end_local_time: time | None = None


@dataclass(frozen=True, slots=True)
class BusinessCalendarVersion:
    business_calendar_version_id: UUID
    calendar_id: UUID
    timezone_name: str
    twenty_four_seven: bool
    working_periods: tuple[WorkingPeriod, ...]
    exceptions: tuple[CalendarException, ...]


@dataclass(frozen=True, slots=True)
class SlaDefinitionVersion:
    sla_definition_id: UUID
    sla_definition_version_id: UUID
    metric: SlaMetric
    pause_conditions: Any


@dataclass(frozen=True, slots=True)
class SlaGoalVersion:
    sla_goal_id: UUID
    sla_goal_version_id: UUID
    sla_definition_version_id: UUID
    business_calendar_version_id: UUID
    match_conditions: Any
    target_seconds: int
    warning_seconds: int | None
    priority_order: int


@dataclass(frozen=True, slots=True)
class TicketFacts:
    ticket_id: UUID
    tenant_id: UUID
    project_id: UUID
    service_node_id: UUID | None
    work_type_code: str
    priority_code: str
    status_code: str
    status_category: str
    created_at: datetime
    first_response_at: datetime | None
    resolved_at: datetime | None

    def rule_values(self) -> dict[str, str | None]:
        return {
            "priority_code": self.priority_code,
            "service_node_id": str(self.service_node_id) if self.service_node_id else None,
            "work_type_code": self.work_type_code,
        }


@dataclass(frozen=True, slots=True)
class TicketSla:
    ticket_sla_id: UUID
    tenant_id: UUID
    ticket_id: UUID
    definition: SlaDefinitionVersion
    goal: SlaGoalVersion
    state: SlaState
    started_at: datetime
    target_at: datetime
    warning_at: datetime | None
    paused_at: datetime | None
    accumulated_pause_seconds: int
    completed_at: datetime | None
    breached_at: datetime | None
    elapsed_working_seconds: int
    remaining_working_seconds: int
    last_calculated_at: datetime
    warning_emitted_at: datetime | None
    row_version: int


@dataclass(frozen=True, slots=True)
class SlaInputEvent:
    outbox_event_id: UUID
    tenant_id: UUID
    ticket_id: UUID
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime
