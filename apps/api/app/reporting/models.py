"""Read-model rows backing the analyst dashboard aggregates."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class TicketCounts:
    open_now: int
    new_today: int
    new_yesterday_same_elapsed_window: int
    resolved_today: int
    resolved_yesterday_same_elapsed_window: int


@dataclass(frozen=True, slots=True)
class StatusRow:
    status_name: str
    count: int


@dataclass(frozen=True, slots=True)
class SlaWeekRow:
    met: int
    breached: int


@dataclass(frozen=True, slots=True)
class ActivityRow:
    event_id: int
    ticket_key: str
    event_type: str
    actor_name: str | None
    created_at: datetime
