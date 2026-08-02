"""Deterministic event-driven SLA lifecycle service."""

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from apps.api.app.core.rules import InvalidRule, evaluate
from apps.api.app.sla.calendar import BusinessCalendar, CalendarConfigurationError
from apps.api.app.sla.models import (
    SlaDefinitionVersion,
    SlaGoalVersion,
    SlaInputEvent,
    SlaMetric,
    SlaState,
    TicketFacts,
    TicketSla,
)
from apps.api.app.sla.repository import SlaRepository

logger = logging.getLogger(__name__)
_SUPPORTED_INPUT_EVENTS = frozenset(
    {
        "START_SLA",
        "AGENT_PUBLIC_RESPONSE_ADDED",
        "CUSTOMER_COMMENT_ADDED",
        "TICKET_WORKFLOW_TRANSITIONED",
        "TICKET_PRIORITY_CHANGED",
    }
)
_GOAL_FIELDS = frozenset({"priority_code", "service_node_id", "work_type_code"})


class SlaConfigurationError(RuntimeError):
    """Published SLA configuration is absent, ambiguous, or unsupported."""


@dataclass(slots=True)
class SlaMetrics:
    input_events_processed: int = 0
    instances_started: int = 0
    instances_paused: int = 0
    instances_resumed: int = 0
    instances_met: int = 0
    warnings_emitted: int = 0
    breaches_emitted: int = 0
    recalculations: int = 0


class SlaEngine:
    """Coordinate SLA state changes inside the caller's database transaction."""

    def __init__(self, repository: SlaRepository, metrics: SlaMetrics | None = None) -> None:
        self._repository = repository
        self.metrics = metrics or SlaMetrics()

    async def process(self, event: SlaInputEvent) -> None:
        if event.event_type not in _SUPPORTED_INPUT_EVENTS:
            raise ValueError("Unsupported SLA input event.")
        ticket = await self._repository.ticket(event.tenant_id, event.ticket_id)
        if ticket is None:
            raise SlaConfigurationError("SLA input references an unavailable ticket.")
        if event.event_type == "START_SLA":
            await self._start(ticket, event)
        elif event.event_type == "AGENT_PUBLIC_RESPONSE_ADDED":
            await self._repository.mark_first_response(
                event.tenant_id, event.ticket_id, event.occurred_at
            )
            await self._complete_metric(ticket, SlaMetric.FIRST_RESPONSE, event)
        elif event.event_type == "TICKET_WORKFLOW_TRANSITIONED":
            await self._transition(ticket, event)
        elif event.event_type == "TICKET_PRIORITY_CHANGED":
            await self._priority_changed(ticket, event)
        # Customer comments are retained as explicit inputs for future next-response
        # metrics, but they do not change the two initial SLA metrics.
        self.metrics.input_events_processed += 1
        logger.info(
            "SLA input processed",
            extra={"event_type": event.event_type, "ticket_id": str(event.ticket_id)},
        )

    async def evaluate_due(self, tenant_id: Any, due_at: datetime, limit: int = 100) -> int:
        processed = 0
        for sla in await self._repository.due_slas(tenant_id, _utc(due_at), limit):
            current = await self._advance(sla, due_at)
            if (
                current.warning_emitted_at is None
                and current.goal.warning_seconds is not None
                and current.remaining_working_seconds <= current.goal.warning_seconds
            ):
                current = await self._warning(current, due_at)
            if current.remaining_working_seconds <= 0 and current.state is SlaState.RUNNING:
                await self._breach(current, due_at)
            processed += 1
        return processed

    async def _start(self, ticket: TicketFacts, event: SlaInputEvent) -> None:
        effective_at = ticket.created_at
        definitions = await self._repository.definitions(
            ticket.tenant_id, ticket.project_id, effective_at
        )
        by_identity: dict[Any, list[SlaDefinitionVersion]] = {}
        for definition in definitions:
            by_identity.setdefault(definition.sla_definition_id, []).append(definition)
        if any(len(values) > 1 for values in by_identity.values()):
            raise SlaConfigurationError("Published SLA definition versions overlap.")
        for definition in definitions:
            goal = await self._select_goal(definition, ticket, effective_at)
            calendar = await self._calendar(goal)
            target_at = calendar.add_business_seconds(effective_at, goal.target_seconds)
            warning_at = _warning_at(calendar, effective_at, goal)
            sla = await self._repository.create_sla(
                ticket, definition, goal, effective_at, target_at, warning_at
            )
            if sla is None:
                continue
            await self._repository.record_event(
                sla,
                "STARTED",
                effective_at,
                f"input:{event.outbox_event_id}:started",
                {
                    "sla_definition_version_id": str(definition.sla_definition_version_id),
                    "sla_goal_version_id": str(goal.sla_goal_version_id),
                    "business_calendar_version_id": str(goal.business_calendar_version_id),
                    "target_at": target_at.isoformat(),
                },
            )
            self.metrics.instances_started += 1
            if definition.metric is SlaMetric.FIRST_RESPONSE and ticket.first_response_at:
                await self._complete(
                    sla, ticket.first_response_at, event, reason="ALREADY_RESPONDED"
                )
            elif definition.metric is SlaMetric.RESOLUTION and ticket.resolved_at:
                await self._complete(sla, ticket.resolved_at, event, reason="ALREADY_RESOLVED")
            elif ticket.status_code in _pause_statuses(definition.pause_conditions):
                await self._pause(sla, effective_at, event, reason=ticket.status_code)

    async def _transition(self, ticket: TicketFacts, event: SlaInputEvent) -> None:
        from_status = _required_string(event.payload, "from_status")
        to_status = _required_string(event.payload, "to_status")
        from_category = await self._repository.status_category(ticket.ticket_id, from_status)
        to_category = await self._repository.status_category(ticket.ticket_id, to_status)
        if from_category is None or to_category is None:
            raise SlaConfigurationError("Workflow event references an unknown status.")
        slas = await self._repository.ticket_slas(ticket.tenant_id, ticket.ticket_id, lock=True)
        for sla in slas:
            if (
                sla.definition.metric is SlaMetric.FIRST_RESPONSE
                and ticket.first_response_at is not None
                and sla.state in {SlaState.RUNNING, SlaState.PAUSED}
            ):
                await self._complete(
                    sla, ticket.first_response_at, event, reason="FIRST_RESPONSE_RECORDED"
                )
                continue
            if sla.definition.metric is not SlaMetric.RESOLUTION:
                continue
            if from_category == "DONE" and to_category != "DONE":
                await self._reopen(sla, event.occurred_at, event)
            elif to_category == "DONE":
                await self._complete(sla, event.occurred_at, event, reason="RESOLVED")
            elif to_status in _pause_statuses(sla.definition.pause_conditions):
                await self._pause(sla, event.occurred_at, event, reason=to_status)
            elif sla.state is SlaState.PAUSED:
                await self._resume(sla, event.occurred_at, event, reason=to_status)

    async def _complete_metric(
        self, ticket: TicketFacts, metric: SlaMetric, event: SlaInputEvent
    ) -> None:
        for sla in await self._repository.ticket_slas(
            ticket.tenant_id, ticket.ticket_id, lock=True
        ):
            if sla.definition.metric is metric:
                await self._complete(sla, event.occurred_at, event, reason=event.event_type)

    async def _pause(
        self, sla: TicketSla, at: datetime, event: SlaInputEvent, *, reason: str
    ) -> TicketSla:
        if sla.state is not SlaState.RUNNING:
            return sla
        current = await self._calculated(sla, at)
        paused = replace(current, state=SlaState.PAUSED, paused_at=_utc(at))
        if not await self._repository.record_event(
            paused,
            "PAUSED",
            _utc(at),
            f"input:{event.outbox_event_id}:paused:{sla.ticket_sla_id}",
            {"reason": reason, "remaining_working_seconds": paused.remaining_working_seconds},
        ):
            return sla
        saved = await self._repository.save(paused, sla.row_version)
        self.metrics.instances_paused += 1
        return saved

    async def _resume(
        self, sla: TicketSla, at: datetime, event: SlaInputEvent, *, reason: str
    ) -> TicketSla:
        if sla.state is not SlaState.PAUSED or sla.paused_at is None:
            return sla
        calendar = await self._calendar(sla.goal)
        resumed_at = _utc(at)
        target_at = calendar.add_business_seconds(resumed_at, sla.remaining_working_seconds)
        warning_at = _remaining_warning_at(calendar, resumed_at, sla)
        resumed = replace(
            sla,
            state=SlaState.RUNNING,
            paused_at=None,
            accumulated_pause_seconds=sla.accumulated_pause_seconds
            + max(0, int((resumed_at - sla.paused_at).total_seconds())),
            target_at=target_at,
            warning_at=warning_at,
            last_calculated_at=resumed_at,
        )
        if not await self._repository.record_event(
            resumed,
            "RESUMED",
            resumed_at,
            f"input:{event.outbox_event_id}:resumed:{sla.ticket_sla_id}",
            {"reason": reason, "target_at": target_at.isoformat()},
        ):
            return sla
        saved = await self._repository.save(resumed, sla.row_version)
        self.metrics.instances_resumed += 1
        return saved

    async def _complete(
        self, sla: TicketSla, at: datetime, event: SlaInputEvent, *, reason: str
    ) -> TicketSla:
        if sla.completed_at is not None or sla.state in {SlaState.CANCELLED, SlaState.PENDING}:
            return sla
        current = await self._calculated(sla, at)
        if current.state is SlaState.RUNNING and current.remaining_working_seconds <= 0:
            current = await self._breach(current, at)
        completed_at = _utc(at)
        completed = replace(
            current,
            state=(SlaState.BREACHED if current.state is SlaState.BREACHED else SlaState.COMPLETED),
            completed_at=completed_at,
            paused_at=None,
            last_calculated_at=completed_at,
        )
        if not await self._repository.record_event(
            completed,
            "STOPPED",
            completed_at,
            f"input:{event.outbox_event_id}:stopped:{sla.ticket_sla_id}",
            {"reason": reason, "elapsed_working_seconds": completed.elapsed_working_seconds},
        ):
            return sla
        saved = await self._repository.save(completed, current.row_version)
        if saved.state is SlaState.COMPLETED:
            await self._repository.record_event(
                saved,
                "MET",
                completed_at,
                f"input:{event.outbox_event_id}:met:{sla.ticket_sla_id}",
                {"reason": reason, "remaining_working_seconds": saved.remaining_working_seconds},
            )
            self.metrics.instances_met += 1
        return saved

    async def _reopen(self, sla: TicketSla, at: datetime, event: SlaInputEvent) -> TicketSla:
        if sla.state is not SlaState.COMPLETED:
            return sla
        reopened_at = _utc(at)
        calendar = await self._calendar(sla.goal)
        remaining = max(0, sla.goal.target_seconds - sla.elapsed_working_seconds)
        if remaining == 0:
            return await self._breach(replace(sla, completed_at=None), reopened_at)
        target_at = calendar.add_business_seconds(reopened_at, remaining)
        reopened = replace(
            sla,
            state=SlaState.RUNNING,
            completed_at=None,
            remaining_working_seconds=remaining,
            target_at=target_at,
            warning_at=_remaining_warning_at(
                calendar, reopened_at, replace(sla, remaining_working_seconds=remaining)
            ),
            last_calculated_at=reopened_at,
        )
        if not await self._repository.record_event(
            reopened,
            "RESUMED",
            reopened_at,
            f"input:{event.outbox_event_id}:reopened:{sla.ticket_sla_id}",
            {"reason": "TICKET_REOPENED", "target_at": target_at.isoformat()},
        ):
            return sla
        saved = await self._repository.save(reopened, sla.row_version)
        self.metrics.instances_resumed += 1
        return saved

    async def _priority_changed(self, ticket: TicketFacts, event: SlaInputEvent) -> None:
        for sla in await self._repository.ticket_slas(
            ticket.tenant_id, ticket.ticket_id, lock=True
        ):
            if sla.state in {SlaState.CANCELLED, SlaState.COMPLETED, SlaState.BREACHED}:
                continue
            current = await self._calculated(sla, event.occurred_at)
            goal = await self._select_goal(sla.definition, ticket, event.occurred_at)
            calendar = await self._calendar(goal)
            remaining = max(0, goal.target_seconds - current.elapsed_working_seconds)
            target_at = calendar.add_business_seconds(event.occurred_at, remaining)
            changed = replace(
                current,
                goal=goal,
                remaining_working_seconds=remaining,
                target_at=target_at,
                warning_at=_remaining_warning_at(
                    calendar,
                    event.occurred_at,
                    replace(current, goal=goal, remaining_working_seconds=remaining),
                ),
                last_calculated_at=_utc(event.occurred_at),
            )
            if not await self._repository.record_event(
                changed,
                "RECALCULATED",
                _utc(event.occurred_at),
                f"input:{event.outbox_event_id}:recalculated:{sla.ticket_sla_id}",
                {
                    "old_sla_goal_version_id": str(sla.goal.sla_goal_version_id),
                    "new_sla_goal_version_id": str(goal.sla_goal_version_id),
                    "business_calendar_version_id": str(goal.business_calendar_version_id),
                },
            ):
                continue
            saved = await self._repository.save(changed, sla.row_version)
            self.metrics.recalculations += 1
            if saved.state is SlaState.RUNNING and remaining == 0:
                await self._breach(saved, event.occurred_at)

    async def _advance(self, sla: TicketSla, at: datetime) -> TicketSla:
        if sla.state is not SlaState.RUNNING:
            return sla
        advanced = await self._calculated(sla, at)
        if advanced == sla:
            return sla
        return await self._repository.save(advanced, sla.row_version)

    async def _calculated(self, sla: TicketSla, at: datetime) -> TicketSla:
        calculated_at = _utc(at)
        if sla.state is not SlaState.RUNNING or calculated_at <= sla.last_calculated_at:
            return sla
        calendar = await self._calendar(sla.goal)
        elapsed = sla.elapsed_working_seconds + calendar.business_seconds_between(
            sla.last_calculated_at, calculated_at
        )
        return replace(
            sla,
            elapsed_working_seconds=elapsed,
            remaining_working_seconds=max(0, sla.goal.target_seconds - elapsed),
            last_calculated_at=calculated_at,
        )

    async def _warning(self, sla: TicketSla, at: datetime) -> TicketSla:
        warned_at = _utc(at)
        if not await self._repository.record_event(
            sla,
            "WARNING",
            warned_at,
            "warning",
            {"remaining_working_seconds": sla.remaining_working_seconds},
        ):
            return sla
        warned = await self._repository.save(
            replace(sla, warning_emitted_at=warned_at), sla.row_version
        )
        await self._repository.emit_outbox(
            warned,
            "SLA_WARNING",
            {
                "ticket_id": str(warned.ticket_id),
                "ticket_sla_id": str(warned.ticket_sla_id),
                "sla_goal_version_id": str(warned.goal.sla_goal_version_id),
            },
            f"sla:{warned.ticket_sla_id}:warning",
        )
        self.metrics.warnings_emitted += 1
        return warned

    async def _breach(self, sla: TicketSla, at: datetime) -> TicketSla:
        breached_at = _utc(at)
        if sla.state is SlaState.BREACHED:
            return sla
        if not await self._repository.record_event(
            sla,
            "BREACHED",
            breached_at,
            "breach",
            {"target_at": sla.target_at.isoformat()},
        ):
            return sla
        breached = await self._repository.save(
            replace(
                sla,
                state=SlaState.BREACHED,
                breached_at=breached_at,
                remaining_working_seconds=0,
                last_calculated_at=breached_at,
            ),
            sla.row_version,
        )
        await self._repository.emit_outbox(
            breached,
            "SLA_BREACHED",
            {
                "ticket_id": str(breached.ticket_id),
                "ticket_sla_id": str(breached.ticket_sla_id),
                "sla_goal_version_id": str(breached.goal.sla_goal_version_id),
            },
            f"sla:{breached.ticket_sla_id}:breach",
        )
        self.metrics.breaches_emitted += 1
        return breached

    async def _select_goal(
        self,
        definition: SlaDefinitionVersion,
        ticket: TicketFacts,
        effective_at: datetime,
    ) -> SlaGoalVersion:
        candidates = [
            goal
            for goal in await self._repository.goals(
                definition.sla_definition_version_id, effective_at
            )
            if _goal_matches(goal.match_conditions, ticket.rule_values())
        ]
        if not candidates:
            raise SlaConfigurationError("No published SLA goal matches the ticket.")
        candidates.sort(key=lambda item: (item.priority_order, str(item.sla_goal_id)))
        if len(candidates) > 1 and candidates[0].priority_order == candidates[1].priority_order:
            raise SlaConfigurationError("Published SLA goals have an ambiguous priority tie.")
        return candidates[0]

    async def _calendar(self, goal: SlaGoalVersion) -> BusinessCalendar:
        version = await self._repository.calendar(goal.business_calendar_version_id)
        if version is None:
            raise SlaConfigurationError("SLA goal references an unavailable calendar version.")
        try:
            return BusinessCalendar(version)
        except CalendarConfigurationError as error:
            raise SlaConfigurationError(str(error)) from error


def _goal_matches(configuration: Any, values: dict[str, str | None]) -> bool:
    if configuration in ({}, None):
        return True
    if not isinstance(configuration, dict):
        raise SlaConfigurationError("SLA goal condition must be an object.")
    if set(configuration) <= _GOAL_FIELDS:
        return all(values[field] == str(expected) for field, expected in configuration.items())
    referenced = _rule_fields(configuration)
    if not referenced <= _GOAL_FIELDS:
        raise SlaConfigurationError("SLA goal condition references an unsupported field.")
    try:
        return evaluate(configuration, values)
    except InvalidRule as error:
        raise SlaConfigurationError("SLA goal condition is invalid.") from error


def _rule_fields(value: Any) -> set[str]:
    if isinstance(value, dict):
        fields = {str(value["field"])} if "field" in value else set()
        for nested in value.values():
            fields.update(_rule_fields(nested))
        return fields
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result.update(_rule_fields(item))
        return result
    return set()


def _pause_statuses(configuration: Any) -> frozenset[str]:
    if configuration in (None, [], {}):
        return frozenset()
    if not isinstance(configuration, list):
        raise SlaConfigurationError("SLA pause conditions must be an array.")
    statuses: set[str] = set()
    for condition in configuration:
        if not isinstance(condition, dict) or set(condition) != {"status_code"}:
            raise SlaConfigurationError("SLA pause condition is unsupported.")
        status = condition["status_code"]
        if not isinstance(status, str) or not status:
            raise SlaConfigurationError("SLA pause status is invalid.")
        statuses.add(status)
    return frozenset(statuses)


def _warning_at(
    calendar: BusinessCalendar, started_at: datetime, goal: SlaGoalVersion
) -> datetime | None:
    if goal.warning_seconds is None:
        return None
    return calendar.add_business_seconds(
        started_at, max(0, goal.target_seconds - goal.warning_seconds)
    )


def _remaining_warning_at(
    calendar: BusinessCalendar, resumed_at: datetime, sla: TicketSla
) -> datetime | None:
    if sla.warning_emitted_at is not None or sla.goal.warning_seconds is None:
        return sla.warning_at
    return calendar.add_business_seconds(
        resumed_at, max(0, sla.remaining_working_seconds - sla.goal.warning_seconds)
    )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SlaConfigurationError(f"SLA input is missing {key}.")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("SLA event times must be timezone-aware.")
    return value.astimezone(UTC)
