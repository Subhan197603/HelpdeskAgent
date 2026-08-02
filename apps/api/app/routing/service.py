"""Deterministic routing and manual assignment application service."""

import hashlib
import json
from collections import Counter
from collections.abc import Callable
from typing import Any
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from apps.api.app.core.rules import InvalidRule, evaluate
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.routing.models import RoutingRuleVersion, RoutingTicket
from apps.api.app.routing.repository import RoutingRepository
from apps.api.app.routing.schemas import (
    AssignmentResponse,
    ManualAssignmentCommand,
    RouteCommand,
)
from apps.api.app.tickets.service import IdempotencyConflict, TicketService

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class RoutingConfigurationError(ConflictError):
    error_code = "routing_configuration_conflict"


class RoutingService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        ticket_service: TicketService,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._ticket_service = ticket_service

    async def route(
        self,
        context: RequestContext,
        ticket_key: str,
        command: RouteCommand,
        idempotency_key: str,
    ) -> AssignmentResponse:
        self._authorize(context, Permission.TICKET_ROUTE)
        tenant_id, user_id = _identity(context)
        request_hash = _request_hash({"ticket_key": ticket_key, "row_version": command.row_version})
        async with self._factory(context) as uow:
            repo = RoutingRepository(uow.session)
            await self._ticket(repo, context, tenant_id, ticket_key, lock=False)
            idem = await repo.claim_idempotency(
                tenant_id, user_id, "TICKET_ROUTE", idempotency_key, request_hash
            )
            self._validate_idempotency(idem, request_hash, user_id)
            if idem.processing_status == "COMPLETED":
                payload = dict(idem.response_payload_json)
                await uow.commit()
                replay_ticket = await self._ticket_service.analyst_ticket(context, ticket_key)
                return AssignmentResponse(ticket=replay_ticket, replayed=True, **payload)
            ticket = await self._locked_ticket(repo, context, tenant_id, ticket_key)
            if ticket.row_version != command.row_version:
                raise ConcurrencyError("Ticket row version is stale.")
            rule, fallback, evaluated_rules = self._select_rule(
                await repo.rule_versions(ticket), ticket
            )
            self._authorize_group(context, rule.assignment_group_id)
            assignee_id = await self._assignee(repo, ticket, rule)
            result = await repo.assign(
                ticket,
                rule.assignment_group_id,
                rule.group_code,
                assignee_id,
                user_id,
            )
            if result is None:
                raise ConcurrencyError("Ticket changed while routing was executing.")
            await repo.record_assignment(
                ticket,
                result,
                user_id,
                "DEFAULT_ROUTE" if fallback else "ROUTING_RULE",
                context.correlation_id,
                context.request_id,
                rule=rule,
                fallback=fallback,
                routing_trace=_routing_trace(ticket, evaluated_rules),
            )
            payload = {
                "assignment_group_code": result.assignment_group_code,
                "assignee_user_id": str(result.assignee_user_id)
                if result.assignee_user_id
                else None,
                "routing_rule_version_id": str(rule.routing_rule_version_id),
                "fallback": fallback,
            }
            await repo.complete_idempotency(idem.idempotency_record_id, ticket.ticket_id, payload)
            await uow.commit()
        response_ticket = await self._ticket_service.analyst_ticket(context, ticket_key)
        return AssignmentResponse(ticket=response_ticket, **payload)

    async def assign_manual(
        self,
        context: RequestContext,
        ticket_key: str,
        command: ManualAssignmentCommand,
        idempotency_key: str,
    ) -> AssignmentResponse:
        self._authorize(context, Permission.TICKET_ASSIGN_MANUAL)
        tenant_id, user_id = _identity(context)
        reason = " ".join(command.reason.split())
        if len(reason) < 3:
            raise ValidationError(
                "Assignment reason is required.",
                field_errors={"reason": ["Enter at least three non-whitespace characters."]},
            )
        request_hash = _request_hash(
            {
                "ticket_key": ticket_key,
                "row_version": command.row_version,
                "assignment_group_id": str(command.assignment_group_id),
                "assignee_user_id": str(command.assignee_user_id)
                if command.assignee_user_id
                else None,
                "reason": reason,
            }
        )
        async with self._factory(context) as uow:
            repo = RoutingRepository(uow.session)
            await self._ticket(repo, context, tenant_id, ticket_key, lock=False)
            idem = await repo.claim_idempotency(
                tenant_id, user_id, "TICKET_ASSIGN_MANUAL", idempotency_key, request_hash
            )
            self._validate_idempotency(idem, request_hash, user_id)
            if idem.processing_status == "COMPLETED":
                payload = dict(idem.response_payload_json)
                await uow.commit()
                replay_ticket = await self._ticket_service.analyst_ticket(context, ticket_key)
                return AssignmentResponse(ticket=replay_ticket, replayed=True, **payload)
            ticket = await self._locked_ticket(repo, context, tenant_id, ticket_key)
            if ticket.row_version != command.row_version:
                raise ConcurrencyError("Ticket row version is stale.")
            self._authorize_group(context, command.assignment_group_id)
            target = await repo.target(
                tenant_id, command.assignment_group_id, command.assignee_user_id
            )
            if target is None:
                raise ValidationError(
                    "Assignment target is invalid.",
                    field_errors={
                        "assignment_group_id": [
                            "Group must be active in the tenant and contain the assignee."
                        ]
                    },
                )
            result = await repo.assign(
                ticket,
                command.assignment_group_id,
                target[0],
                target[1],
                user_id,
            )
            if result is None:
                raise ConcurrencyError("Ticket changed while reassignment was executing.")
            await repo.record_assignment(
                ticket,
                result,
                user_id,
                f"MANUAL: {reason}",
                context.correlation_id,
                context.request_id,
                rule=None,
                fallback=False,
                routing_trace=None,
            )
            payload = {
                "assignment_group_code": result.assignment_group_code,
                "assignee_user_id": str(result.assignee_user_id)
                if result.assignee_user_id
                else None,
                "routing_rule_version_id": None,
                "fallback": False,
            }
            await repo.complete_idempotency(idem.idempotency_record_id, ticket.ticket_id, payload)
            await uow.commit()
        response_ticket = await self._ticket_service.analyst_ticket(context, ticket_key)
        return AssignmentResponse(ticket=response_ticket, **payload)

    def _select_rule(
        self, versions: list[RoutingRuleVersion], ticket: RoutingTicket
    ) -> tuple[RoutingRuleVersion, bool, list[dict[str, Any]]]:
        counts = Counter(rule.routing_rule_id for rule in versions)
        if any(count > 1 for count in counts.values()):
            raise RoutingConfigurationError(
                "More than one effective published version exists for a routing rule."
            )
        defaults = [rule for rule in versions if rule.condition in ({}, [], None)]
        if len(defaults) != 1:
            raise RoutingConfigurationError(
                "The ticket project must have exactly one effective default route."
            )
        values = _routing_values(ticket)
        candidates = sorted((rule for rule in versions if rule not in defaults), key=_rule_order)
        evaluated_rules: list[dict[str, Any]] = []
        try:
            for rule in candidates:
                matched = evaluate(rule.condition, values)
                evaluated_rules.append(
                    {
                        "routing_rule_version_id": str(rule.routing_rule_version_id),
                        "matched": matched,
                    }
                )
                if matched:
                    return rule, False, evaluated_rules
        except InvalidRule:
            raise RoutingConfigurationError(
                "A published routing rule contains unsupported deterministic configuration."
            ) from None
        evaluated_rules.append(
            {
                "routing_rule_version_id": str(defaults[0].routing_rule_version_id),
                "matched": True,
                "default": True,
            }
        )
        return defaults[0], True, evaluated_rules

    async def _assignee(
        self, repo: RoutingRepository, ticket: RoutingTicket, rule: RoutingRuleVersion
    ) -> UUID | None:
        if rule.assignment_method == "GROUP_ONLY":
            return None
        if rule.assignment_method == "ROUND_ROBIN":
            assignee_id = await repo.round_robin_assignee(
                ticket.tenant_id, rule.assignment_group_id
            )
            if assignee_id is None:
                raise RoutingConfigurationError(
                    "The round-robin group has no active eligible analysts."
                )
            return assignee_id
        if rule.assignment_method == "NAMED_ASSIGNEE" and rule.assignee_user_id is not None:
            target = await repo.target(
                ticket.tenant_id, rule.assignment_group_id, rule.assignee_user_id
            )
            if target is not None:
                return rule.assignee_user_id
        raise RoutingConfigurationError(
            "The published routing rule uses an unsupported or invalid assignment method."
        )

    async def _locked_ticket(
        self,
        repo: RoutingRepository,
        context: RequestContext,
        tenant_id: UUID,
        ticket_key: str,
    ) -> RoutingTicket:
        ticket = await repo.ticket(
            tenant_id,
            ticket_key,
            context.support_group_ids,
            include_all=self._authorization.is_allowed(context, Permission.TICKET_READ_ALL),
            lock=True,
        )
        if ticket is None:
            raise ConcurrencyError("Ticket changed while assignment was acquiring its lock.")
        return ticket

    async def _ticket(
        self,
        repo: RoutingRepository,
        context: RequestContext,
        tenant_id: UUID,
        ticket_key: str,
        *,
        lock: bool,
    ) -> RoutingTicket:
        ticket = await repo.ticket(
            tenant_id,
            ticket_key,
            context.support_group_ids,
            include_all=self._authorization.is_allowed(context, Permission.TICKET_READ_ALL),
            lock=lock,
        )
        if ticket is None:
            raise NotFoundError("Ticket was not found.")
        return ticket

    def _authorize(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError("The authenticated user is not permitted to assign tickets.")

    def _authorize_group(self, context: RequestContext, group_id: UUID) -> None:
        if self._authorization.is_allowed(context, Permission.TICKET_READ_ALL):
            return
        if group_id not in context.support_group_ids:
            raise AuthorizationError(
                "The authenticated user is not permitted to assign tickets to this group."
            )

    @staticmethod
    def _validate_idempotency(idem: Any, request_hash: str, user_id: UUID) -> None:
        if idem.request_hash != request_hash or idem.principal_id != str(user_id):
            raise IdempotencyConflict()


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise AuthorizationError()
    return context.tenant_id, context.user_id


def _request_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _specificity(rule: Any) -> int:
    if rule in ({}, [], None):
        return 0
    if isinstance(rule, list):
        return sum(_specificity(item) for item in rule)
    if isinstance(rule, dict) and set(rule) in ({"all"}, {"any"}):
        values = rule.get("all", rule.get("any"))
        if isinstance(values, list):
            return sum(_specificity(item) for item in values)
    if isinstance(rule, dict) and {"field", "operator"}.issubset(rule):
        return 1
    raise RoutingConfigurationError("A routing rule has invalid condition syntax.")


def _rule_order(rule: RoutingRuleVersion) -> tuple[int, int, float, str]:
    effective_timestamp = rule.effective_from.timestamp() if rule.effective_from else 0.0
    return (
        rule.rule_priority,
        -_specificity(rule.condition),
        -effective_timestamp,
        str(rule.routing_rule_version_id),
    )


def _routing_values(ticket: RoutingTicket) -> dict[str, Any]:
    values: dict[str, Any] = {
        "project_id": str(ticket.project_id),
        "project_code": ticket.project_code,
        "service_node_id": str(ticket.service_node_id) if ticket.service_node_id else None,
        "service_node_code": ticket.service_node_code,
        "service_code": ticket.service_code,
        "module_code": ticket.module_code,
        "environment_code": ticket.environment_code,
        "work_type_code": ticket.work_type_code,
        "priority_code": ticket.priority_code,
        "status_code": ticket.status_code,
        "summary": ticket.summary,
        "description": ticket.description,
    }
    for code, value in ticket.custom_fields.items():
        values[f"field.{code}"] = value
        values.setdefault(code, value)
    return values


def _routing_trace(ticket: RoutingTicket, evaluated_rules: list[dict[str, Any]]) -> dict[str, Any]:
    values = _routing_values(ticket)
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "evaluated_rules": evaluated_rules,
        "inputs": {
            "project_code": ticket.project_code,
            "service_code": ticket.service_code,
            "module_code": ticket.module_code,
            "environment_code": ticket.environment_code,
            "work_type_code": ticket.work_type_code,
            "priority_code": ticket.priority_code,
            "custom_field_codes": sorted(ticket.custom_fields),
        },
        "input_hash": hashlib.sha256(canonical.encode()).hexdigest(),
        "classifier_version": None,
        "classifier_confidence": None,
        "routing_source": "CONFIGURATION_ONLY",
    }
