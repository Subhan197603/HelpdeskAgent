"""Deterministic workflow transition application service."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    ValidationError,
)
from apps.api.app.core.rules import InvalidRule, evaluate
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.tickets.repository import TicketRepository
from apps.api.app.tickets.service import IdempotencyConflict, TicketService
from apps.api.app.workflows.models import WorkflowTicket, WorkflowTransition
from apps.api.app.workflows.repository import WorkflowRepository
from apps.api.app.workflows.schemas import (
    AvailableTransition,
    AvailableTransitionList,
    TransitionCommand,
    TransitionResponse,
)

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]
_EDITABLE_FIELDS = frozenset({"resolution_code", "resolution_summary"})
_TIMESTAMP_FIELDS = frozenset({"first_response_at", "resolved_at", "closed_at"})
_CLEARABLE_FIELDS = _EDITABLE_FIELDS | _TIMESTAMP_FIELDS


class WorkflowConfigurationError(ConflictError):
    error_code = "workflow_configuration_conflict"


class WorkflowService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        ticket_service: TicketService,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._ticket_service = ticket_service

    async def available(self, context: RequestContext, ticket_key: str) -> AvailableTransitionList:
        self._authorize(context)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            repo = WorkflowRepository(uow.session)
            ticket = await self._ticket(repo, context, tenant_id, ticket_key, lock=False)
            if ticket.workflow_version_status not in {"PUBLISHED", "RETIRED"}:
                raise WorkflowConfigurationError(
                    "The ticket does not reference an executable workflow version."
                )
            transitions = await repo.available(ticket.workflow_version_id, ticket.status_id)
            values = _values(ticket, {})
            available: list[AvailableTransition] = []
            for transition in transitions:
                try:
                    allowed = evaluate(transition.condition, values)
                except InvalidRule:
                    raise WorkflowConfigurationError(
                        "The workflow contains an invalid deterministic guard."
                    ) from None
                if allowed:
                    available.append(
                        AvailableTransition(
                            code=transition.transition_code,
                            name=transition.transition_name,
                            to_status=transition.to_status_code,
                            to_status_name=transition.to_status_name,
                        )
                    )
            return AvailableTransitionList(
                ticket_key=ticket.ticket_key,
                row_version=ticket.row_version,
                current_status=ticket.status_code,
                transitions=available,
            )

    async def execute(
        self,
        context: RequestContext,
        ticket_key: str,
        command: TransitionCommand,
        idempotency_key: str,
    ) -> TransitionResponse:
        self._authorize(context)
        tenant_id, user_id = _identity(context)
        normalized_comment = command.comment.strip() if command.comment else None
        canonical = command.model_dump(mode="json")
        canonical["comment"] = normalized_comment
        request_hash = hashlib.sha256(
            json.dumps(
                {"ticket_key": ticket_key, **canonical}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        async with self._factory(context) as uow:
            repo = WorkflowRepository(uow.session)
            await self._ticket(repo, context, tenant_id, ticket_key, lock=False)
            idem = await repo.claim_idempotency(tenant_id, user_id, idempotency_key, request_hash)
            if idem.request_hash != request_hash or idem.principal_id != str(user_id):
                raise IdempotencyConflict()
            if idem.processing_status == "COMPLETED":
                await uow.commit()
                response_ticket = await self._ticket_service.analyst_ticket(context, ticket_key)
                return TransitionResponse(
                    ticket=response_ticket, transition_code=command.transition_code, replayed=True
                )
            ticket = await repo.ticket(
                tenant_id,
                ticket_key,
                context.support_group_ids,
                include_all=self._authorization.is_allowed(context, Permission.TICKET_READ_ALL),
                lock=True,
            )
            if ticket is None:
                raise ConcurrencyError(
                    "Ticket changed while the transition was acquiring its lock."
                )
            if ticket.row_version != command.row_version:
                raise ConcurrencyError("Ticket row version is stale.")
            if ticket.workflow_version_status not in {"PUBLISHED", "RETIRED"}:
                raise WorkflowConfigurationError(
                    "The ticket does not reference an executable workflow version."
                )
            transition = await repo.transition(
                ticket.workflow_version_id, ticket.status_id, command.transition_code
            )
            if transition is None:
                raise InvalidTransitionError(
                    "The transition is not allowed from the ticket's current status."
                )
            updates = await self._validated_updates(repo, ticket, transition, command.field_updates)
            if normalized_comment:
                await TicketRepository(uow.session).add_public_comment(
                    tenant_id,
                    ticket.ticket_id,
                    user_id,
                    normalized_comment,
                    context.correlation_id,
                    context.request_id,
                )
            new_version = await repo.apply_transition(ticket, transition, user_id, updates)
            if new_version is None:
                raise ConcurrencyError("Ticket changed while the transition was executing.")
            await repo.record_transition(
                ticket,
                transition,
                user_id,
                new_version,
                context.correlation_id,
                context.request_id,
            )
            await repo.complete_idempotency(
                idem.idempotency_record_id,
                ticket.ticket_id,
                {
                    "ticket_key": ticket.ticket_key,
                    "transition_code": transition.transition_code,
                    "row_version": new_version,
                },
            )
            await uow.commit()
        result = await self._ticket_service.analyst_ticket(context, ticket_key)
        return TransitionResponse(ticket=result, transition_code=command.transition_code)

    async def _validated_updates(
        self,
        repo: WorkflowRepository,
        ticket: WorkflowTicket,
        transition: WorkflowTransition,
        requested: dict[str, Any],
    ) -> dict[str, Any]:
        if not set(requested) <= _EDITABLE_FIELDS:
            unsupported = sorted(set(requested) - _EDITABLE_FIELDS)
            raise ValidationError(
                "The transition contains unsupported field updates.",
                field_errors={
                    field: ["Field cannot be changed by a transition."] for field in unsupported
                },
            )
        updates = dict(requested)
        await self._validate_update_values(repo, updates)
        values = _values(ticket, updates)
        try:
            if not evaluate(transition.condition, values):
                raise InvalidTransitionError("The transition guard conditions are not satisfied.")
            self._validate_required(transition.validators, values)
            self._apply_actions(transition.actions, updates)
        except InvalidRule:
            raise WorkflowConfigurationError(
                "The workflow contains unsupported deterministic configuration."
            ) from None
        await self._validate_update_values(repo, updates)
        return updates

    @staticmethod
    async def _validate_update_values(repo: WorkflowRepository, updates: dict[str, Any]) -> None:
        if "resolution_code" in updates:
            code = updates["resolution_code"]
            if code is not None and (
                not isinstance(code, str) or not await repo.resolution_code_exists(code)
            ):
                raise ValidationError(
                    "Resolution code is invalid.",
                    field_errors={"field_updates.resolution_code": ["Unknown resolution code."]},
                )
        summary = updates.get("resolution_summary")
        if summary is not None and (not isinstance(summary, str) or len(summary) > 20_000):
            raise ValidationError(
                "Resolution summary is invalid.",
                field_errors={
                    "field_updates.resolution_summary": ["Enter at most 20000 characters."]
                },
            )

    @staticmethod
    def _validate_required(validators: Any, values: dict[str, Any]) -> None:
        if validators in (None, [], {}):
            return
        if not isinstance(validators, list):
            raise InvalidRule("Validators must be an array.")
        missing: dict[str, list[str]] = {}
        for validator in validators:
            if not isinstance(validator, dict) or set(validator) != {"type", "field"}:
                raise InvalidRule("Validator syntax is unsupported.")
            if str(validator["type"]).lower() != "required_field" or not isinstance(
                validator["field"], str
            ):
                raise InvalidRule("Validator type is unsupported.")
            field = validator["field"]
            if values.get(field) in (None, "", []):
                missing[f"field_updates.{field}"] = ["Field is required for this transition."]
        if missing:
            raise ValidationError("Required transition fields are missing.", field_errors=missing)

    @staticmethod
    def _apply_actions(actions: Any, updates: dict[str, Any]) -> None:
        if actions in (None, [], {}):
            return
        if not isinstance(actions, list):
            raise InvalidRule("Actions must be an array.")
        for action in actions:
            if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                raise InvalidRule("Action syntax is unsupported.")
            action_type = action["type"].upper()
            field = action.get("field")
            if action_type == "SET_TIMESTAMP" and field in _TIMESTAMP_FIELDS:
                updates[field] = datetime.now(UTC)
            elif action_type == "CLEAR_FIELD" and field in _CLEARABLE_FIELDS:
                updates[field] = None
            elif action_type == "SET_FIELD" and field in _EDITABLE_FIELDS and "value" in action:
                updates[field] = action["value"]
            else:
                raise InvalidRule("Action type or field is unsupported.")

    async def _ticket(
        self,
        repo: WorkflowRepository,
        context: RequestContext,
        tenant_id: UUID,
        ticket_key: str,
        *,
        lock: bool,
    ) -> WorkflowTicket:
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

    def _authorize(self, context: RequestContext) -> None:
        if not self._authorization.is_allowed(context, Permission.TICKET_TRANSITION):
            raise AuthorizationError(
                "The authenticated user is not permitted to transition tickets."
            )


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise NotFoundError("Ticket was not found.")
    return context.tenant_id, context.user_id


def _values(ticket: WorkflowTicket, updates: dict[str, Any]) -> dict[str, Any]:
    values = asdict(ticket)
    values.update(updates)
    return values
