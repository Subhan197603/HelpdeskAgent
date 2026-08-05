"""Analyst dashboard endpoint contract and service formatting tests."""

from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.reporting.models import (
    ActivityRow,
    SlaWeekRow,
    StatusRow,
    TicketCounts,
)
from apps.api.app.reporting.service import DashboardService

PATH = "/api/v1/agent/dashboard"

TENANT = UUID("20000000-0000-0000-0000-000000000001")
AGENT = UUID("22000000-0000-0000-0000-000000000004")


def _context(roles: frozenset[str] = frozenset({"AGENT"})) -> RequestContext:
    return RequestContext(
        tenant_id=TENANT,
        user_id=AGENT,
        external_subject="agent",
        roles=roles,
        support_group_ids=frozenset({UUID("23000000-0000-0000-0000-000000000002")}),
        business_unit_id=None,
        correlation_id="00000000-0000-0000-0000-000000000001",
        request_id="dashboard-test",
    )


def test_dashboard_requires_authentication(client: TestClient) -> None:
    assert client.get(PATH).status_code == 401


class _StubRepository:
    def __init__(self) -> None:
        self.received: dict[str, object] = {}

    async def ticket_counts(self, tenant_id: UUID, now: datetime) -> TicketCounts:
        self.received["tenant_id"] = tenant_id
        self.received["now"] = now
        return TicketCounts(
            open_now=125,
            new_today=32,
            new_yesterday_same_elapsed_window=30,
            resolved_today=28,
            resolved_yesterday_same_elapsed_window=24,
        )

    async def sla_ticket_counts(self, tenant_id: UUID, now: datetime) -> tuple[int, int]:
        return (7, 15)

    async def status_distribution(self, tenant_id: UUID) -> list[StatusRow]:
        return [StatusRow(status_name="New", count=32)]

    async def sla_compliance_week(self, tenant_id: UUID, now: datetime) -> SlaWeekRow:
        return SlaWeekRow(met=138, breached=12)

    async def recent_activity(self, tenant_id: UUID, limit: int) -> list[ActivityRow]:
        return [
            ActivityRow(
                event_id=901,
                ticket_key="ERP-1",
                event_type="STATUS_CHANGED",
                actor_name="John Analyst",
                created_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
            )
        ]


class _StubQueueService:
    async def queues(self, context: RequestContext) -> list[object]:
        class _Queue:
            id = UUID("37000000-0000-0000-0000-000000000001")
            name = "My Queue"

        return [_Queue()]


class _EmptyQueueService:
    async def queues(self, context: RequestContext) -> list[object]:
        return []


def _service(queue_service: object) -> DashboardService:
    from apps.api.app.identity.authorization import AuthorizationService
    from apps.api.app.queues.service import QueueService
    from apps.api.app.reporting.repository import DashboardRepository
    from apps.api.app.reporting.service import UnitOfWorkFactory

    repository = _StubRepository()
    service = DashboardService.__new__(DashboardService)
    service._authorization = AuthorizationService()
    service._queue_service = cast("QueueService", queue_service)
    service._repository_factory = lambda session: cast("DashboardRepository", repository)
    service._factory = cast("UnitOfWorkFactory", None)
    return service


@pytest.mark.anyio
async def test_service_formats_response_from_repository_rows() -> None:
    service = _service(_StubQueueService())
    response = await service._assemble(
        _context(),
        counts=TicketCounts(
            open_now=125,
            new_today=32,
            new_yesterday_same_elapsed_window=30,
            resolved_today=28,
            resolved_yesterday_same_elapsed_window=24,
        ),
        sla_breached_open=7,
        due_today=15,
        distribution=[StatusRow(status_name="New", count=32)],
        week=SlaWeekRow(met=138, breached=12),
        activity=[
            ActivityRow(
                event_id=901,
                ticket_key="ERP-1",
                event_type="STATUS_CHANGED",
                actor_name="John Analyst",
                created_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
            )
        ],
        generated_at=datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
    )
    assert response.counts.open_now == 125
    assert response.counts.sla_breached_open == 7
    assert response.counts.due_today == 15
    assert response.status_distribution[0].status_name == "New"
    assert response.sla_compliance_week.met == 138
    assert response.recent_activity[0].ticket_key == "ERP-1"
    assert response.primary_queue is not None
    assert response.primary_queue.name == "My Queue"
    assert response.generated_at == datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_service_returns_null_primary_queue_when_none_visible() -> None:
    service = _service(_EmptyQueueService())
    response = await service._assemble(
        _context(),
        counts=TicketCounts(
            open_now=0,
            new_today=0,
            new_yesterday_same_elapsed_window=0,
            resolved_today=0,
            resolved_yesterday_same_elapsed_window=0,
        ),
        sla_breached_open=0,
        due_today=0,
        distribution=[],
        week=SlaWeekRow(met=0, breached=0),
        activity=[],
        generated_at=datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
    )
    assert response.primary_queue is None
    assert response.counts.open_now == 0


@pytest.mark.anyio
async def test_service_rejects_missing_permission() -> None:
    service = _service(_StubQueueService())
    with pytest.raises(AuthorizationError):
        await service.dashboard(_context(roles=frozenset({"EMPLOYEE"})))
