"""Authorized queue queries and immutable activity timeline use cases."""

import base64
import hashlib
import json
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.queues.models import (
    ActivityItem,
    CannedResponse,
    QueueDefinition,
    QueueTicket,
    SavedFilter,
)
from apps.api.app.queues.repository import QueueRepository
from apps.api.app.queues.schemas import (
    ActivityItemResponse,
    AnalystCommentCreateRequest,
    CannedResponseCreateRequest,
    CannedResponseFields,
    CannedResponseOrderRequest,
    CannedResponseResponse,
    CannedResponseUpdateRequest,
    QueueResponse,
    QueueTicketResponse,
    SavedFilterCreateRequest,
    SavedFilterFields,
    SavedFilterOrderRequest,
    SavedFilterResponse,
    SavedFilterUpdateRequest,
    TimelineResponse,
)
from apps.api.app.tickets.repository import TicketRepository
from apps.api.app.tickets.service import IdempotencyConflict

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class QueueConfigurationError(ConflictError):
    error_code = "queue_configuration_conflict"


class QueueService:
    def __init__(self, factory: UnitOfWorkFactory, authorization: AuthorizationService) -> None:
        self._factory = factory
        self._authorization = authorization

    async def canned_responses(self, context: RequestContext) -> list[CannedResponseResponse]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        async with self._factory(context) as uow:
            rows = await QueueRepository(uow.session).canned_responses(tenant_id, user_id)
        return [_canned_response_response(row) for row in rows]

    async def canned_response(
        self, context: RequestContext, canned_response_id: UUID
    ) -> CannedResponseResponse:
        row = await self._owned_canned_response(context, canned_response_id)
        return _canned_response_response(row)

    async def create_canned_response(
        self,
        context: RequestContext,
        command: CannedResponseCreateRequest,
        idempotency_key: str,
    ) -> tuple[CannedResponseResponse, bool]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        values = _canned_response_values(command)
        request_hash = hashlib.sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            idem = await TicketRepository(uow.session).claim_idempotency(
                tenant_id,
                user_id,
                idempotency_key,
                request_hash,
                "ANALYST_CANNED_RESPONSE_CREATE",
            )
            if idem.request_hash != request_hash or idem.principal_id != str(user_id):
                raise IdempotencyConflict()
            if idem.processing_status == "COMPLETED":
                row = await repo.canned_response(tenant_id, user_id, UUID(idem.result_resource_id))
                if row is None:
                    raise ConflictError("The idempotent canned-response result is unavailable.")
                await uow.commit()
                return _canned_response_response(row), True
            if await repo.canned_response_name_exists(tenant_id, user_id, values["name"]):
                raise ConflictError("A personal canned response with this name already exists.")
            row = await repo.create_canned_response(tenant_id, user_id, **values)
            if row is None:
                raise ConflictError("A personal canned response with this name already exists.")
            await TicketRepository(uow.session).complete_idempotency(
                idem.idempotency_record_id,
                "ANALYST_CANNED_RESPONSE",
                row.canned_response_id,
                {"canned_response_id": str(row.canned_response_id)},
            )
            await uow.commit()
        return _canned_response_response(row), False

    async def update_canned_response(
        self,
        context: RequestContext,
        canned_response_id: UUID,
        command: CannedResponseUpdateRequest,
    ) -> CannedResponseResponse:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        values = _canned_response_values(command)
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            current = await repo.canned_response(tenant_id, user_id, canned_response_id)
            if current is None:
                raise NotFoundError("Canned response was not found.")
            if current.row_version != command.row_version:
                raise ConcurrencyError("The canned response changed. Refresh and try again.")
            if await repo.canned_response_name_exists(
                tenant_id, user_id, values["name"], excluding=canned_response_id
            ):
                raise ConflictError("A personal canned response with this name already exists.")
            updated = await repo.update_canned_response(
                tenant_id,
                user_id,
                canned_response_id,
                command.row_version,
                **values,
            )
            if updated is None:
                raise ConcurrencyError("The canned response changed. Refresh and try again.")
            await uow.commit()
        return _canned_response_response(updated)

    async def reorder_canned_responses(
        self, context: RequestContext, command: CannedResponseOrderRequest
    ) -> list[CannedResponseResponse]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        identifiers = [item.id for item in command.items]
        if len(set(identifiers)) != len(identifiers):
            raise ValidationError(
                "Canned response order contains duplicates.",
                field_errors={"items": ["Include each canned response once."]},
            )
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            current = await repo.canned_responses(tenant_id, user_id)
            current_by_id = {item.canned_response_id: item for item in current}
            if set(identifiers) != set(current_by_id):
                raise ValidationError(
                    "Canned response order is incomplete.",
                    field_errors={"items": ["Include every personal canned response once."]},
                )
            if any(
                current_by_id[item.id].row_version != item.row_version for item in command.items
            ):
                raise ConcurrencyError("A canned response changed. Refresh and try again.")
            changed = await repo.reorder_canned_responses(
                tenant_id,
                user_id,
                [
                    (item.id, item.row_version, index * 10)
                    for index, item in enumerate(command.items)
                ],
            )
            if changed != len(command.items):
                raise ConcurrencyError("A canned response changed. Refresh and try again.")
            rows = await repo.canned_responses(tenant_id, user_id)
            await uow.commit()
        return [_canned_response_response(row) for row in rows]

    async def delete_canned_response(
        self, context: RequestContext, canned_response_id: UUID, row_version: int
    ) -> None:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            current = await repo.canned_response(tenant_id, user_id, canned_response_id)
            if current is None:
                raise NotFoundError("Canned response was not found.")
            if current.row_version != row_version:
                raise ConcurrencyError("The canned response changed. Refresh and try again.")
            if not await repo.delete_canned_response(
                tenant_id, user_id, canned_response_id, row_version
            ):
                raise ConcurrencyError("The canned response changed. Refresh and try again.")
            await uow.commit()

    async def _owned_canned_response(
        self, context: RequestContext, canned_response_id: UUID
    ) -> CannedResponse:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        async with self._factory(context) as uow:
            row = await QueueRepository(uow.session).canned_response(
                tenant_id, user_id, canned_response_id
            )
        if row is None:
            raise NotFoundError("Canned response was not found.")
        return row

    async def saved_filters(self, context: RequestContext) -> list[SavedFilterResponse]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        async with self._factory(context) as uow:
            rows = await QueueRepository(uow.session).saved_filters(tenant_id, user_id)
        return [_saved_filter_response(row) for row in rows]

    async def saved_filter(
        self, context: RequestContext, saved_filter_id: UUID
    ) -> SavedFilterResponse:
        row = await self._owned_saved_filter(context, saved_filter_id)
        return _saved_filter_response(row)

    async def create_saved_filter(
        self,
        context: RequestContext,
        command: SavedFilterCreateRequest,
        idempotency_key: str,
    ) -> tuple[SavedFilterResponse, bool]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        values = _saved_filter_values(command)
        request_hash = hashlib.sha256(
            json.dumps(values, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            idem = await TicketRepository(uow.session).claim_idempotency(
                tenant_id,
                user_id,
                idempotency_key,
                request_hash,
                "ANALYST_SAVED_FILTER_CREATE",
            )
            if idem.request_hash != request_hash or idem.principal_id != str(user_id):
                raise IdempotencyConflict()
            if idem.processing_status == "COMPLETED":
                row = await repo.saved_filter(tenant_id, user_id, UUID(idem.result_resource_id))
                if row is None:
                    raise ConflictError("The idempotent saved-filter result is unavailable.")
                await uow.commit()
                return _saved_filter_response(row), True
            await self._validate_saved_filter(context, repo, **values)
            if await repo.saved_filter_name_exists(tenant_id, user_id, values["name"]):
                raise ConflictError("A personal saved filter with this name already exists.")
            row = await repo.create_saved_filter(tenant_id, user_id, **values)
            if row is None:
                raise ConflictError("A personal saved filter with this name already exists.")
            await TicketRepository(uow.session).complete_idempotency(
                idem.idempotency_record_id,
                "ANALYST_SAVED_FILTER",
                row.saved_filter_id,
                {"saved_filter_id": str(row.saved_filter_id)},
            )
            await uow.commit()
        return _saved_filter_response(row), False

    async def update_saved_filter(
        self,
        context: RequestContext,
        saved_filter_id: UUID,
        command: SavedFilterUpdateRequest,
    ) -> SavedFilterResponse:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        values = _saved_filter_values(command)
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            current = await repo.saved_filter(tenant_id, user_id, saved_filter_id)
            if current is None:
                raise NotFoundError("Saved filter was not found.")
            if current.row_version != command.row_version:
                raise ConcurrencyError("The saved filter changed. Refresh and try again.")
            await self._validate_saved_filter(context, repo, **values)
            if await repo.saved_filter_name_exists(
                tenant_id, user_id, values["name"], excluding=saved_filter_id
            ):
                raise ConflictError("A personal saved filter with this name already exists.")
            updated = await repo.update_saved_filter(
                tenant_id,
                user_id,
                saved_filter_id,
                command.row_version,
                **values,
            )
            if updated is None:
                raise ConcurrencyError("The saved filter changed. Refresh and try again.")
            await uow.commit()
        return _saved_filter_response(updated)

    async def reorder_saved_filters(
        self, context: RequestContext, command: SavedFilterOrderRequest
    ) -> list[SavedFilterResponse]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        identifiers = [item.id for item in command.items]
        if len(set(identifiers)) != len(identifiers):
            raise ValidationError(
                "Saved filter order contains duplicates.",
                field_errors={"items": ["Include each saved filter once."]},
            )
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            current = await repo.saved_filters(tenant_id, user_id)
            current_by_id = {item.saved_filter_id: item for item in current}
            if set(identifiers) != set(current_by_id):
                raise ValidationError(
                    "Saved filter order is incomplete.",
                    field_errors={"items": ["Include every personal saved filter once."]},
                )
            if any(
                current_by_id[item.id].row_version != item.row_version for item in command.items
            ):
                raise ConcurrencyError("A saved filter changed. Refresh and try again.")
            changed = await repo.reorder_saved_filters(
                tenant_id,
                user_id,
                [
                    (item.id, item.row_version, index * 10)
                    for index, item in enumerate(command.items)
                ],
            )
            if changed != len(command.items):
                raise ConcurrencyError("A saved filter changed. Refresh and try again.")
            rows = await repo.saved_filters(tenant_id, user_id)
            await uow.commit()
        return [_saved_filter_response(row) for row in rows]

    async def delete_saved_filter(
        self, context: RequestContext, saved_filter_id: UUID, row_version: int
    ) -> None:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            current = await repo.saved_filter(tenant_id, user_id, saved_filter_id)
            if current is None:
                raise NotFoundError("Saved filter was not found.")
            if current.row_version != row_version:
                raise ConcurrencyError("The saved filter changed. Refresh and try again.")
            if not await repo.delete_saved_filter(tenant_id, user_id, saved_filter_id, row_version):
                raise ConcurrencyError("The saved filter changed. Refresh and try again.")
            await uow.commit()

    async def saved_filter_tickets(
        self,
        context: RequestContext,
        saved_filter_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[QueueTicketResponse], str | None]:
        row = await self._owned_saved_filter(context, saved_filter_id)
        return await self.tickets(
            context,
            row.queue_id,
            limit,
            cursor,
            status=row.status_code,
            priority=row.priority_code,
            search=row.search_text,
            assignment_group_id=row.assignment_group_id,
            assignee=row.assignee_scope,
        )

    async def _owned_saved_filter(
        self, context: RequestContext, saved_filter_id: UUID
    ) -> SavedFilter:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        async with self._factory(context) as uow:
            row = await QueueRepository(uow.session).saved_filter(
                tenant_id, user_id, saved_filter_id
            )
        if row is None:
            raise NotFoundError("Saved filter was not found.")
        return row

    async def _validate_saved_filter(
        self,
        context: RequestContext,
        repo: QueueRepository,
        *,
        name: str,
        queue_id: UUID,
        status_code: str | None,
        priority_code: str | None,
        search: str | None,
        assignment_group_id: UUID | None,
        assignee: str | None,
    ) -> None:
        del name, status_code, priority_code, search, assignee
        tenant_id, _ = _identity(context)
        definitions = self._effective(await repo.definitions(tenant_id, queue_id))
        if len(definitions) != 1 or not self._visible(context, definitions[0]):
            raise NotFoundError("Queue was not found.")
        if (
            assignment_group_id is not None
            and not self._authorization.is_allowed(context, Permission.TICKET_READ_ALL)
            and assignment_group_id not in context.support_group_ids
        ):
            raise AuthorizationError("The requested support-group filter is not permitted.")

    async def queues(self, context: RequestContext) -> list[QueueResponse]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        async with self._factory(context) as uow:
            definitions = self._effective(await QueueRepository(uow.session).definitions(tenant_id))
        responses: list[QueueResponse] = []
        for item in definitions:
            if not self._visible(context, item):
                continue
            self._validate_sort(item.sort_json)
            _compile_filter(item.filter_json, {"current_user_id": user_id})
            responses.append(_queue_response(item))
        return responses

    async def tickets(
        self,
        context: RequestContext,
        queue_id: UUID,
        limit: int,
        cursor: str | None,
        *,
        status: str | None,
        priority: str | None,
        search: str | None,
        assignment_group_id: UUID | None,
        assignee: str | None,
    ) -> tuple[list[QueueTicketResponse], str | None]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        normalized_search = " ".join(search.split()) if search else None
        if search is not None and (normalized_search is None or len(normalized_search) < 2):
            raise ValidationError(
                "Search text is too short.",
                field_errors={"search": ["Enter at least two non-whitespace characters."]},
            )
        include_all = self._authorization.is_allowed(context, Permission.TICKET_READ_ALL)
        if (
            assignment_group_id is not None
            and not include_all
            and assignment_group_id not in context.support_group_ids
        ):
            raise AuthorizationError("The requested support-group filter is not permitted.")
        scope = _scope_hash(
            queue_id,
            status=status,
            priority=priority,
            search=normalized_search,
            assignment_group_id=assignment_group_id,
            assignee=assignee,
        )
        before_at, before_id = _decode_cursor(cursor, scope)
        async with self._factory(context) as uow:
            repo = QueueRepository(uow.session)
            definitions = self._effective(await repo.definitions(tenant_id, queue_id))
            if len(definitions) != 1 or not self._visible(context, definitions[0]):
                raise NotFoundError("Queue was not found.")
            queue = definitions[0]
            self._validate_sort(queue.sort_json)
            parameters: dict[str, Any] = {
                "current_user_id": user_id,
                "before_at": before_at,
                "before_id": before_id,
                "status": status,
                "priority": priority,
                "search": normalized_search,
                "filter_group_id": assignment_group_id,
            }
            predicates = [
                _compile_filter(queue.filter_json, parameters),
                "(CAST(:before_at AS timestamptz) IS NULL OR "
                "(ticket.created_at,ticket.ticket_id) < "
                "(CAST(:before_at AS timestamptz),CAST(:before_id AS uuid)))",
                "(CAST(:status AS varchar) IS NULL OR status.status_code=:status)",
                "(CAST(:priority AS varchar) IS NULL OR ticket.priority_code=:priority)",
                "(CAST(:filter_group_id AS uuid) IS NULL OR "
                "ticket.assignment_group_id=:filter_group_id)",
                "(CAST(:search AS varchar) IS NULL OR "
                "to_tsvector('simple',coalesce(ticket.ticket_key,'') || ' ' || ticket.summary) "
                "@@ plainto_tsquery('simple',:search))",
            ]
            if assignee == "me":
                predicates.append("ticket.assignee_user_id=:current_user_id")
            elif assignee == "unassigned":
                predicates.append("ticket.assignee_user_id IS NULL")
            elif assignee is not None:
                raise ValidationError(
                    "Assignee filter is invalid.",
                    field_errors={"assignee": ["Use 'me' or 'unassigned'."]},
                )
            rows = await repo.tickets(
                queue,
                " AND ".join(f"({predicate})" for predicate in predicates),
                parameters,
                support_group_ids=context.support_group_ids,
                include_all=include_all,
                limit=limit + 1,
            )
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1], scope) if more and rows else None
        return [_ticket_response(item) for item in rows], next_cursor

    async def customer_timeline(self, context: RequestContext, ticket_key: str) -> TimelineResponse:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_READ_OWN)
        async with self._factory(context) as uow:
            ticket = await TicketRepository(uow.session).ticket(tenant_id, user_id, key=ticket_key)
            if ticket is None:
                raise NotFoundError("Ticket was not found.")
            items = await QueueRepository(uow.session).timeline(
                ticket.ticket_id, include_internal=False
            )
        return TimelineResponse(ticket_key=ticket_key, items=[_activity(item) for item in items])

    async def analyst_timeline(self, context: RequestContext, ticket_key: str) -> TimelineResponse:
        tenant_id, _ = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        async with self._factory(context) as uow:
            ticket = await TicketRepository(uow.session).analyst_ticket(
                tenant_id,
                context.support_group_ids,
                key=ticket_key,
                include_all=self._authorization.is_allowed(context, Permission.TICKET_READ_ALL),
            )
            if ticket is None:
                raise NotFoundError("Ticket was not found.")
            items = await QueueRepository(uow.session).timeline(
                ticket.ticket_id, include_internal=True
            )
        return TimelineResponse(ticket_key=ticket_key, items=[_activity(item) for item in items])

    async def add_comment(
        self,
        context: RequestContext,
        ticket_key: str,
        command: AnalystCommentCreateRequest,
        idempotency_key: str,
    ) -> tuple[ActivityItemResponse, bool]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        permission = (
            Permission.TICKET_COMMENT_INTERNAL
            if command.visibility == "INTERNAL"
            else Permission.TICKET_COMMENT_PUBLIC
        )
        self._authorize(context, permission)
        body = command.body.strip()
        if not body:
            raise ValidationError(
                "Comment body is required.", field_errors={"body": ["Enter a comment."]}
            )
        request_hash = hashlib.sha256(
            json.dumps(
                {"ticket_key": ticket_key, "visibility": command.visibility, "body": body},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        async with self._factory(context) as uow:
            ticket_repo = TicketRepository(uow.session)
            ticket = await ticket_repo.analyst_ticket(
                tenant_id,
                context.support_group_ids,
                key=ticket_key,
                include_all=self._authorization.is_allowed(context, Permission.TICKET_READ_ALL),
                lock=True,
            )
            if ticket is None:
                raise NotFoundError("Ticket was not found.")
            operation = f"TICKET_{command.visibility}_COMMENT_CREATE"
            idem = await ticket_repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, operation
            )
            if idem.request_hash != request_hash or idem.principal_id != str(user_id):
                raise IdempotencyConflict()
            queue_repo = QueueRepository(uow.session)
            if idem.processing_status == "COMPLETED":
                item = await queue_repo.comment(tenant_id, UUID(idem.result_resource_id))
                if item is None:
                    raise ConflictError("The idempotent comment result is unavailable.")
                await uow.commit()
                return _activity(item), True
            comment_id = await queue_repo.add_comment(
                tenant_id,
                ticket.ticket_id,
                user_id,
                command.visibility,
                body,
                context.correlation_id,
                context.request_id,
            )
            await ticket_repo.complete_idempotency(
                idem.idempotency_record_id,
                "TICKET_COMMENT",
                comment_id,
                {"comment_id": str(comment_id), "ticket_key": ticket_key},
            )
            item = await queue_repo.comment(tenant_id, comment_id)
            if item is None:
                raise ConflictError("The created comment is unavailable.")
            await uow.commit()
        return _activity(item), False

    @staticmethod
    def _effective(definitions: list[QueueDefinition]) -> list[QueueDefinition]:
        counts = Counter(item.queue_id for item in definitions)
        if any(count > 1 for count in counts.values()):
            raise QueueConfigurationError(
                "More than one effective published version exists for a queue."
            )
        return definitions

    @staticmethod
    def _validate_sort(value: Any) -> None:
        if value != [{"field": "created_at", "direction": "DESC"}]:
            raise QueueConfigurationError(
                "Published queues must use the supported stable created-at descending sort."
            )

    def _visible(self, context: RequestContext, queue: QueueDefinition) -> bool:
        if queue.visibility_type in {"ALL_AGENTS", "PROJECT_AGENTS"}:
            return True
        if queue.visibility_type == "GROUP":
            return queue.owner_group_id in context.support_group_ids
        return False

    def _authorize(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError()


_FIELDS = {
    "assignment_group_id": "ticket.assignment_group_id",
    "assignee_user_id": "ticket.assignee_user_id",
    "priority_code": "ticket.priority_code",
    "status_code": "status.status_code",
    "project_id": "ticket.project_id",
}


def _compile_filter(value: Any, parameters: dict[str, Any], depth: int = 0) -> str:
    if depth > 5:
        raise QueueConfigurationError("Queue filter nesting is too deep.")
    if value in ({}, [], None):
        return "TRUE"
    if isinstance(value, dict) and set(value) in ({"all"}, {"any"}):
        children = value[next(iter(value))]
        if not isinstance(children, list) or not children or len(children) > 20:
            raise QueueConfigurationError("Queue filter groups must contain 1 to 20 rules.")
        operator = " AND " if "all" in value else " OR "
        return operator.join(
            f"({_compile_filter(child, parameters, depth + 1)})" for child in children
        )
    if not isinstance(value, dict) or not {"field", "operator"}.issubset(value):
        raise QueueConfigurationError("A published queue contains an invalid filter.")
    field = _FIELDS.get(value["field"])
    operator = value["operator"]
    if field is None:
        raise QueueConfigurationError("A published queue uses an unsupported filter field.")
    if operator == "is_null":
        return f"{field} IS NULL"
    if operator == "is_not_null":
        return f"{field} IS NOT NULL"
    if (
        operator == "equals_context"
        and value.get("value") == "user_id"
        and value["field"] == "assignee_user_id"
    ):
        return f"{field}=:current_user_id"
    if (
        operator == "in_context"
        and value.get("value") == "support_group_ids"
        and value["field"] == "assignment_group_id"
    ):
        return f"{field}=ANY(CAST(:support_group_ids AS uuid[]))"
    index = sum(key.startswith("queue_filter_") for key in parameters)
    parameter = f"queue_filter_{index}"
    if operator == "equals" and isinstance(value.get("value"), (str, int, bool)):
        parameters[parameter] = value["value"]
        return f"CAST({field} AS text)=CAST(:{parameter} AS text)"
    if operator == "in" and isinstance(value.get("value"), list):
        expected = value["value"]
        if (
            not expected
            or len(expected) > 50
            or not all(isinstance(item, str) for item in expected)
        ):
            raise QueueConfigurationError("Queue filter lists must contain 1 to 50 strings.")
        parameters[parameter] = expected
        return f"CAST({field} AS text)=ANY(CAST(:{parameter} AS text[]))"
    raise QueueConfigurationError("A published queue uses an unsupported filter operator.")


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise AuthorizationError()
    return context.tenant_id, context.user_id


def _saved_filter_values(command: SavedFilterFields) -> dict[str, Any]:
    name = " ".join(command.name.split())
    if not name:
        raise ValidationError(
            "Saved filter name is required.", field_errors={"name": ["Enter a name."]}
        )
    search = " ".join(command.search.split()) if command.search else None
    if command.search is not None and (search is None or len(search) < 2):
        raise ValidationError(
            "Search text is too short.",
            field_errors={"search": ["Enter at least two non-whitespace characters."]},
        )
    return {
        "name": name,
        "queue_id": command.queue_id,
        "status_code": command.status_code,
        "priority_code": command.priority_code,
        "search": search,
        "assignment_group_id": command.assignment_group_id,
        "assignee": command.assignee,
    }


def _canned_response_values(command: CannedResponseFields) -> dict[str, str]:
    name = " ".join(command.name.split())
    body = command.body.strip()
    field_errors: dict[str, list[str]] = {}
    if not name:
        field_errors["name"] = ["Enter a name."]
    if not body:
        field_errors["body"] = ["Enter response text."]
    if field_errors:
        raise ValidationError("Canned response fields are required.", field_errors=field_errors)
    return {"name": name, "body": body}


def _canned_response_response(item: CannedResponse) -> CannedResponseResponse:
    return CannedResponseResponse(
        id=item.canned_response_id,
        name=item.name,
        body=item.body,
        display_order=item.display_order,
        row_version=item.row_version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _saved_filter_response(item: SavedFilter) -> SavedFilterResponse:
    return SavedFilterResponse(
        id=item.saved_filter_id,
        name=item.name,
        queue_id=item.queue_id,
        status_code=item.status_code,
        priority_code=item.priority_code,
        search=item.search_text,
        assignment_group_id=item.assignment_group_id,
        assignee=cast("Literal['me', 'unassigned'] | None", item.assignee_scope),
        display_order=item.display_order,
        row_version=item.row_version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _queue_response(item: QueueDefinition) -> QueueResponse:
    columns = item.columns_json
    sort = item.sort_json
    if not isinstance(columns, list) or not all(isinstance(value, str) for value in columns):
        raise QueueConfigurationError("A published queue contains invalid columns.")
    allowed_columns = {
        "ticket_key",
        "summary",
        "priority",
        "status",
        "reporter",
        "assignment_group",
        "assignee",
        "created_at",
        "updated_at",
        "first_response_sla_target",
        "resolution_sla_target",
    }
    if not columns or len(columns) > 20 or not set(columns).issubset(allowed_columns):
        raise QueueConfigurationError("A published queue contains unsupported columns.")
    if not isinstance(sort, list) or not all(isinstance(value, dict) for value in sort):
        raise QueueConfigurationError("A published queue contains an invalid sort.")
    return QueueResponse(
        id=item.queue_id,
        version_id=item.queue_version_id,
        name=item.name,
        description=item.description,
        project_id=item.project_id,
        project_code=item.project_code,
        visibility=cast("Literal['GROUP', 'PROJECT_AGENTS', 'ALL_AGENTS']", item.visibility_type),
        display_order=item.display_order,
        columns=columns,
        sort=sort,
    )


def _ticket_response(item: QueueTicket) -> QueueTicketResponse:
    return QueueTicketResponse(
        id=item.ticket_id,
        key=item.ticket_key,
        summary=item.summary,
        project_code=item.project_code,
        priority=item.priority_code,
        status=item.status_code,
        status_name=item.status_name,
        reporter_name=item.reporter_name,
        assignment_group_id=item.assignment_group_id,
        assignment_group_name=item.assignment_group_name,
        assignee_user_id=item.assignee_user_id,
        assignee_name=item.assignee_name,
        created_at=item.created_at,
        updated_at=item.updated_at,
        first_response_sla_target=item.first_response_sla_target,
        resolution_sla_target=item.resolution_sla_target,
    )


def _activity(item: ActivityItem) -> ActivityItemResponse:
    return ActivityItemResponse(
        id=item.item_id,
        type=item.item_type,
        classification=cast("Literal['PUBLIC', 'INTERNAL', 'SYSTEM']", item.classification),
        actor_user_id=item.actor_user_id,
        actor_name=item.actor_name,
        body=item.body,
        details=item.details,
        created_at=item.created_at,
    )


def _scope_hash(queue_id: UUID, **filters: Any) -> str:
    payload = {"queue_id": str(queue_id), **filters}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _encode_cursor(ticket: QueueTicket, scope: str) -> str:
    payload = json.dumps(
        {"created_at": ticket.created_at.isoformat(), "id": str(ticket.ticket_id), "scope": scope},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str | None, scope: str) -> tuple[datetime | None, UUID | None]:
    if value is None:
        return None, None
    try:
        payload = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if payload["scope"] != scope:
            raise ValueError
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise ValidationError(
            "Pagination cursor is invalid for this queue query.",
            field_errors={"cursor": ["Invalid or mismatched cursor."]},
        ) from None
