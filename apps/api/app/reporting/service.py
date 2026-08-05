"""Analyst dashboard aggregation use case."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.queues.service import QueueService
from apps.api.app.reporting.models import (
    ActivityRow,
    SlaWeekRow,
    StatusRow,
    TicketCounts,
)
from apps.api.app.reporting.repository import DashboardRepository
from apps.api.app.reporting.schemas import (
    AnalystDashboardResponse,
    DashboardActivityResponse,
    DashboardCountsResponse,
    PrimaryQueueResponse,
    SlaComplianceWeekResponse,
    StatusSliceResponse,
)

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]

ACTIVITY_LIMIT = 10


class DashboardService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        queue_service: QueueService,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._queue_service = queue_service
        self._repository_factory: Callable[[AsyncSession], DashboardRepository] = (
            DashboardRepository
        )

    async def dashboard(self, context: RequestContext) -> AnalystDashboardResponse:
        if not self._authorization.is_allowed(context, Permission.TICKET_ANALYST_READ):
            raise AuthorizationError()
        if context.tenant_id is None:
            raise AuthorizationError()
        tenant_id = context.tenant_id
        now = datetime.now(tz=UTC)
        async with self._factory(context) as uow:
            repository = self._repository_factory(uow.session)
            counts = await repository.ticket_counts(tenant_id, now)
            breached_open, due_today = await repository.sla_ticket_counts(tenant_id, now)
            distribution = await repository.status_distribution(tenant_id)
            week = await repository.sla_compliance_week(tenant_id, now)
            activity = await repository.recent_activity(tenant_id, ACTIVITY_LIMIT)
        return await self._assemble(
            context,
            counts=counts,
            sla_breached_open=breached_open,
            due_today=due_today,
            distribution=distribution,
            week=week,
            activity=activity,
            generated_at=now,
        )

    async def _assemble(
        self,
        context: RequestContext,
        *,
        counts: TicketCounts,
        sla_breached_open: int,
        due_today: int,
        distribution: list[StatusRow],
        week: SlaWeekRow,
        activity: list[ActivityRow],
        generated_at: datetime,
    ) -> AnalystDashboardResponse:
        queues = await self._queue_service.queues(context)
        primary = queues[0] if queues else None
        return AnalystDashboardResponse(
            counts=DashboardCountsResponse(
                open_now=counts.open_now,
                new_today=counts.new_today,
                new_yesterday_same_elapsed_window=counts.new_yesterday_same_elapsed_window,
                resolved_today=counts.resolved_today,
                resolved_yesterday_same_elapsed_window=(
                    counts.resolved_yesterday_same_elapsed_window
                ),
                sla_breached_open=sla_breached_open,
                due_today=due_today,
            ),
            status_distribution=[
                StatusSliceResponse(status_name=row.status_name, count=row.count)
                for row in distribution
            ],
            sla_compliance_week=SlaComplianceWeekResponse(met=week.met, breached=week.breached),
            recent_activity=[
                DashboardActivityResponse(
                    id=f"event:{row.event_id}",
                    ticket_key=row.ticket_key,
                    event_type=row.event_type,
                    actor_name=row.actor_name,
                    created_at=row.created_at,
                )
                for row in activity
            ],
            primary_queue=(
                PrimaryQueueResponse(id=primary.id, name=primary.name) if primary else None
            ),
            generated_at=generated_at,
        )
