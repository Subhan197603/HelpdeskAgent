"""Stable contracts for the analyst dashboard.

All day windows are computed in UTC on the server: with T the request
timestamp and D0 the UTC midnight of T's date, "today" means [D0, T) and the
yesterday comparison windows mean [D0 - 24h, T - 24h). Counts are raw values;
the client derives any percentage presentation. The open-ticket count has no
historical comparison because resolution timestamps are clearable on reopen,
which makes point-in-time reconstruction unreliable.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardCountsResponse(BaseModel):
    open_now: int
    new_today: int
    new_yesterday_same_elapsed_window: int
    resolved_today: int
    resolved_yesterday_same_elapsed_window: int
    sla_breached_open: int = Field(
        description="Distinct open tickets with at least one breached SLA row."
    )
    due_today: int = Field(
        description=(
            "Distinct open tickets with at least one running, unpaused, "
            "unbreached SLA row targeting the current UTC day."
        )
    )


class StatusSliceResponse(BaseModel):
    status_name: str
    count: int


class SlaComplianceWeekResponse(BaseModel):
    met: int
    breached: int


class DashboardActivityResponse(BaseModel):
    id: str
    ticket_key: str
    event_type: str
    actor_name: str | None
    created_at: datetime


class PrimaryQueueResponse(BaseModel):
    id: UUID
    name: str


class AnalystDashboardResponse(BaseModel):
    counts: DashboardCountsResponse
    status_distribution: list[StatusSliceResponse]
    sla_compliance_week: SlaComplianceWeekResponse
    recent_activity: list[DashboardActivityResponse]
    primary_queue: PrimaryQueueResponse | None
    generated_at: datetime
