"""Ticket draft, confirmation, and customer-safe ticket use cases."""

import base64
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from apps.api.app.catalog.service import CatalogueConfigurationService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import (
    AuthorizationResource,
    AuthorizationService,
    Permission,
)
from apps.api.app.tickets.models import PublicComment, TicketDraft, TicketView
from apps.api.app.tickets.repository import TicketRepository
from apps.api.app.tickets.schemas import (
    CustomFieldInput,
    DraftCreateRequest,
    DraftPatchRequest,
    DraftResponse,
    NormalizedField,
    PublicCommentCreateRequest,
    PublicCommentResponse,
    TicketResponse,
)
from apps.api.app.tickets.validation import validate_and_normalize

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TicketMetrics:
    drafts_created: int = 0
    drafts_updated: int = 0
    drafts_validated: int = 0
    drafts_cancelled: int = 0
    tickets_submitted: int = 0
    idempotent_replays: int = 0
    idempotency_conflicts: int = 0
    authorization_denials: int = 0
    operation_counts: dict[str, int] = field(default_factory=dict)
    operation_duration_ms_total: float = 0.0

    def record(self, operation: str, started: float) -> None:
        self.operation_counts[operation] = self.operation_counts.get(operation, 0) + 1
        self.operation_duration_ms_total += (time.perf_counter() - started) * 1000


class TicketConfigurationError(ConflictError):
    error_code = "ticket_configuration_conflict"

    def __init__(self) -> None:
        super().__init__("Ticket configuration is missing or ambiguous.")


class IdempotencyConflict(ConflictError):
    error_code = "idempotency_key_conflict"

    def __init__(self) -> None:
        super().__init__("The idempotency key was already used for a different request.")


class TicketService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        metrics: TicketMetrics,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._metrics = metrics

    async def create_draft(
        self, context: RequestContext, command: DraftCreateRequest
    ) -> DraftResponse:
        started = time.perf_counter()
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_DRAFT_CREATE)
        async with self._factory(context) as uow:
            catalogue = CatalogueConfigurationService(uow.session)
            ticket_repo = TicketRepository(uow.session)
            request_type = await catalogue.published_request_type(
                tenant_id, command.request_type_id, datetime.now(UTC)
            )
            if request_type is None or request_type.version.effective_version_count != 1:
                raise NotFoundError("Published request type was not found.")
            binding = await catalogue.request_type_binding(
                tenant_id, command.request_type_id, request_type.version.request_type_version_id
            )
            assert binding is not None
            await self._validate_references(
                context, ticket_repo, catalogue, tenant_id, user_id, command
            )
            fields = await catalogue.form_fields(
                tenant_id, request_type.version.request_type_version_id
            )
            custom = _form_inputs(
                command.summary, command.description, command.custom_fields, fields
            )
            normalized = validate_and_normalize(fields, custom, require_complete=False)
            await self._validate_form_references(
                ticket_repo, catalogue, tenant_id, fields, normalized
            )
            priority = await self._priority(
                ticket_repo,
                tenant_id,
                request_type.project_id,
                command.service_node_id,
                command.impact,
                command.urgency,
            )
            draft = await ticket_repo.create_draft(
                {
                    "tenant_id": tenant_id,
                    "owner_user_id": user_id,
                    "requested_for_user_id": command.requested_for_user_id,
                    "project_id": request_type.project_id,
                    "service_node_id": command.service_node_id,
                    "request_type_id": command.request_type_id,
                    "request_type_version_id": request_type.version.request_type_version_id,
                    "work_type_id": binding.work_type_id,
                    "application_environment_id": command.application_environment_id,
                    "summary": _summary(command.summary),
                    "description": _description(command.description),
                    "custom_values": json.dumps(normalized),
                    "impact_code": command.impact,
                    "urgency_code": command.urgency,
                    "priority_code": priority[0],
                    "priority_matrix_id": priority[1],
                    "expires_at": datetime.now(UTC) + timedelta(days=30),
                }
            )
            await ticket_repo.audit(
                draft, "TICKET_DRAFT_CREATED", "SUCCESS", context.correlation_id, context.request_id
            )
            await uow.commit()
            self._metrics.drafts_created += 1
            self._record("create_draft", started, "success")
            return _draft_response(draft, fields)

    async def get_draft(self, context: RequestContext, draft_id: UUID) -> DraftResponse:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_DRAFT_READ_OWN)
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            draft = await repo.draft(tenant_id, draft_id)
            await self._require_owned(uow, repo, draft, user_id, context)
            assert draft is not None
            fields = await CatalogueConfigurationService(uow.session).form_fields(
                tenant_id, draft.request_type_version_id
            )
            ticket_key = None
            if draft.submitted_ticket_id:
                ticket = await repo.ticket(tenant_id, user_id, ticket_id=draft.submitted_ticket_id)
                ticket_key = ticket.ticket_key if ticket else None
            return _draft_response(draft, fields, ticket_key)

    async def update_draft(
        self, context: RequestContext, draft_id: UUID, command: DraftPatchRequest
    ) -> DraftResponse:
        started = time.perf_counter()
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_DRAFT_UPDATE_OWN)
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            existing = await repo.draft(tenant_id, draft_id, lock=True)
            await self._require_owned(uow, repo, existing, user_id, context)
            assert existing is not None
            if existing.status not in {"DRAFT", "READY_FOR_REVIEW"}:
                raise ConflictError("Draft can no longer be edited.")
            if existing.row_version != command.row_version:
                raise ConcurrencyError("Draft row version is stale.")
            values = command.model_dump(exclude_unset=True)
            requested_for = values.get("requested_for_user_id", existing.requested_for_user_id)
            if requested_for not in {None, user_id}:
                self._authorize(context, Permission.TICKET_REQUEST_FOR_OTHER)
                if not await repo.reference_user_exists(tenant_id, cast(UUID, requested_for)):
                    raise ValidationError(
                        "Requested-for user is invalid.",
                        field_errors={"requested_for_user_id": ["User is unavailable."]},
                    )
            service_id = values.get("service_node_id", existing.service_node_id)
            environment_id = values.get(
                "application_environment_id", existing.application_environment_id
            )
            catalogue = CatalogueConfigurationService(uow.session)
            if service_id is not None and not await catalogue.service_node_exists(
                tenant_id, service_id
            ):
                raise ValidationError(
                    "Service is invalid.",
                    field_errors={"service_node_id": ["Service is unavailable."]},
                )
            if environment_id is not None and not await repo.environment_exists(
                tenant_id, environment_id, service_id
            ):
                raise ValidationError(
                    "Environment is invalid.",
                    field_errors={"application_environment_id": ["Environment is unavailable."]},
                )
            fields = await catalogue.form_fields(tenant_id, existing.request_type_version_id)
            supplied = (
                command.custom_fields
                if command.custom_fields is not None
                else _stored_inputs(existing.custom_values)
            )
            summary = command.summary if command.summary is not None else existing.summary
            description = command.description if "description" in values else existing.description
            normalized = validate_and_normalize(
                fields, _form_inputs(summary, description, supplied, fields), require_complete=False
            )
            await self._validate_form_references(repo, catalogue, tenant_id, fields, normalized)
            impact = command.impact or existing.impact_code
            urgency = command.urgency or existing.urgency_code
            assert impact is not None and urgency is not None
            priority = await self._priority(
                repo, tenant_id, existing.project_id, service_id, impact, urgency
            )
            updated = await repo.update_draft(
                draft_id,
                command.row_version,
                {
                    "requested_for_user_id": requested_for,
                    "service_node_id": service_id,
                    "application_environment_id": environment_id,
                    "summary": _summary(summary),
                    "description": _description(description),
                    "custom_values": json.dumps(normalized),
                    "impact_code": impact,
                    "urgency_code": urgency,
                    "priority_code": priority[0],
                    "priority_matrix_id": priority[1],
                },
            )
            if updated is None:
                raise ConcurrencyError("Draft row version is stale.")
            await repo.audit(
                updated,
                "TICKET_DRAFT_UPDATED",
                "SUCCESS",
                context.correlation_id,
                context.request_id,
            )
            await uow.commit()
            self._metrics.drafts_updated += 1
            self._record("update_draft", started, "success")
            return _draft_response(updated, fields)

    async def validate_draft(
        self, context: RequestContext, draft_id: UUID, row_version: int
    ) -> DraftResponse:
        started = time.perf_counter()
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_DRAFT_UPDATE_OWN)
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            draft = await repo.draft(tenant_id, draft_id, lock=True)
            await self._require_owned(uow, repo, draft, user_id, context)
            assert draft is not None
            if draft.row_version != row_version:
                raise ConcurrencyError("Draft row version is stale.")
            catalogue = CatalogueConfigurationService(uow.session)
            fields = await catalogue.form_fields(tenant_id, draft.request_type_version_id)
            try:
                normalized = validate_and_normalize(fields, _stored_inputs(draft.custom_values))
            except ValidationError:
                await repo.audit(
                    draft,
                    "TICKET_DRAFT_VALIDATION_FAILED",
                    "FAILED",
                    context.correlation_id,
                    context.request_id,
                )
                await uow.commit()
                raise
            await self._validate_form_references(repo, catalogue, tenant_id, fields, normalized)
            priority = await self._priority(
                repo,
                tenant_id,
                draft.project_id,
                draft.service_node_id,
                draft.impact_code or "",
                draft.urgency_code or "",
            )
            ready = await repo.set_ready(draft_id, row_version, priority)
            assert ready is not None
            await repo.audit(
                ready,
                "TICKET_DRAFT_VALIDATED",
                "SUCCESS",
                context.correlation_id,
                context.request_id,
            )
            await uow.commit()
            self._metrics.drafts_validated += 1
            self._record("validate_draft", started, "success")
            return _draft_response(ready, fields)

    async def cancel_draft(self, context: RequestContext, draft_id: UUID, row_version: int) -> None:
        started = time.perf_counter()
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_DRAFT_UPDATE_OWN)
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            draft = await repo.draft(tenant_id, draft_id, lock=True)
            await self._require_owned(uow, repo, draft, user_id, context)
            assert draft is not None
            if draft.row_version != row_version:
                raise ConcurrencyError("Draft row version is stale.")
            cancelled = await repo.cancel(draft_id, row_version)
            if cancelled is None:
                raise ConflictError("Draft can no longer be cancelled.")
            await repo.audit(
                cancelled,
                "TICKET_DRAFT_CANCELLED",
                "SUCCESS",
                context.correlation_id,
                context.request_id,
            )
            await uow.commit()
            self._metrics.drafts_cancelled += 1
            self._record("cancel_draft", started, "success")

    async def submit(
        self, context: RequestContext, draft_id: UUID, row_version: int, idempotency_key: str
    ) -> tuple[TicketResponse, bool]:
        started = time.perf_counter()
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_SUBMIT)
        request_hash = hashlib.sha256(f"{draft_id}:{row_version}".encode()).hexdigest()
        async with self._factory(context) as authorization_uow:
            authorization_repo = TicketRepository(authorization_uow.session)
            authorization_draft = await authorization_repo.draft(tenant_id, draft_id)
            await self._require_owned(
                authorization_uow, authorization_repo, authorization_draft, user_id, context
            )
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            idem = await repo.claim_idempotency(tenant_id, user_id, idempotency_key, request_hash)
            if idem.request_hash != request_hash or idem.principal_id != str(user_id):
                self._metrics.idempotency_conflicts += 1
                conflicted = await repo.draft(tenant_id, draft_id)
                if conflicted is not None and conflicted.owner_user_id == user_id:
                    await repo.audit(
                        conflicted,
                        "TICKET_SUBMISSION_IDEMPOTENCY_CONFLICT",
                        "FAILED",
                        context.correlation_id,
                        context.request_id,
                    )
                    await uow.commit()
                raise IdempotencyConflict()
            if idem.processing_status == "COMPLETED":
                ticket = await repo.ticket(
                    tenant_id, user_id, ticket_id=UUID(idem.result_resource_id)
                )
                if ticket is None:
                    raise TicketConfigurationError()
                replayed = await repo.draft(tenant_id, draft_id)
                if replayed is not None:
                    await repo.audit(
                        replayed,
                        "TICKET_SUBMISSION_REPLAYED",
                        "SUCCESS",
                        context.correlation_id,
                        context.request_id,
                    )
                    await uow.commit()
                self._metrics.idempotent_replays += 1
                self._record("submit_draft", started, "replayed")
                comments = await repo.public_comments(ticket.ticket_id)
                return _ticket_response(ticket, comments), True
            draft = await repo.draft(tenant_id, draft_id, lock=True)
            self._own(draft, user_id)
            assert draft is not None
            if draft.row_version != row_version:
                raise ConcurrencyError("Draft row version is stale.")
            if draft.status not in {"DRAFT", "READY_FOR_REVIEW"}:
                raise ConflictError("Draft is not submittable.")
            catalogue = CatalogueConfigurationService(uow.session)
            binding = await catalogue.request_type_binding(
                tenant_id, draft.request_type_id, draft.request_type_version_id
            )
            if binding is None or binding.version_status not in {"PUBLISHED", "RETIRED"}:
                raise TicketConfigurationError()
            fields = await catalogue.form_fields(tenant_id, draft.request_type_version_id)
            normalized = validate_and_normalize(fields, _stored_inputs(draft.custom_values))
            await self._validate_form_references(repo, catalogue, tenant_id, fields, normalized)
            priority = await self._priority(
                repo,
                tenant_id,
                draft.project_id,
                draft.service_node_id,
                draft.impact_code or "",
                draft.urgency_code or "",
            )
            draft = TicketDraft(
                **{
                    **asdict(draft),
                    "custom_values": normalized,
                    "priority_code": priority[0],
                    "priority_matrix_id": priority[1],
                }
            )
            workflow = await repo.workflow_initial(binding.workflow_id)
            if workflow is None:
                raise TicketConfigurationError()
            ticket_id, ticket_key = await repo.create_ticket(
                draft,
                workflow,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
            )
            await repo.persist_custom_values(ticket_id, draft.request_type_version_id, normalized)
            payload = {"id": str(ticket_id), "key": ticket_key}
            await repo.finish_submission(
                draft_id, ticket_id, idem.idempotency_record_id, ticket_key, payload
            )
            await repo.audit(
                draft, "TICKET_SUBMITTED", "SUCCESS", context.correlation_id, context.request_id
            )
            await uow.commit()
        self._metrics.tickets_submitted += 1
        self._record("submit_draft", started, "success", ticket_key=ticket_key)
        return await self.get_ticket(context, ticket_key), False

    async def get_ticket(self, context: RequestContext, ticket_key: str) -> TicketResponse:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_READ_OWN)
        async with self._factory(context) as uow:
            ticket = await TicketRepository(uow.session).ticket(tenant_id, user_id, key=ticket_key)
            if ticket is None:
                raise NotFoundError("Ticket was not found.")
            comments = await TicketRepository(uow.session).public_comments(ticket.ticket_id)
            return _ticket_response(ticket, comments)

    async def my_tickets(
        self, context: RequestContext, limit: int, cursor: str | None
    ) -> tuple[list[TicketResponse], str | None]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_READ_OWN)
        before_at, before_id = _decode_cursor(cursor)
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            rows = await repo.tickets(tenant_id, user_id, limit + 1, before_at, before_id)
            more = len(rows) > limit
            rows = rows[:limit]
            responses = [
                _ticket_response(row, await repo.public_comments(row.ticket_id)) for row in rows
            ]
        next_cursor = _encode_cursor(rows[-1]) if more and rows else None
        return responses, next_cursor

    async def analyst_ticket(self, context: RequestContext, ticket_key: str) -> TicketResponse:
        tenant_id, _ = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        include_all = self._authorization.is_allowed(context, Permission.TICKET_READ_ALL)
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            ticket = await repo.analyst_ticket(
                tenant_id,
                context.support_group_ids,
                key=ticket_key,
                include_all=include_all,
            )
            if ticket is None:
                raise NotFoundError("Ticket was not found.")
            comments = await repo.public_comments(ticket.ticket_id)
            return _ticket_response(ticket, comments)

    async def analyst_tickets(
        self, context: RequestContext, limit: int, cursor: str | None
    ) -> tuple[list[TicketResponse], str | None]:
        tenant_id, _ = _identity(context)
        self._authorize(context, Permission.TICKET_ANALYST_READ)
        include_all = self._authorization.is_allowed(context, Permission.TICKET_READ_ALL)
        before_at, before_id = _decode_cursor(cursor)
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            rows = await repo.analyst_tickets(
                tenant_id,
                context.support_group_ids,
                limit + 1,
                before_at,
                before_id,
                include_all=include_all,
            )
            more = len(rows) > limit
            rows = rows[:limit]
            responses = [
                _ticket_response(row, await repo.public_comments(row.ticket_id)) for row in rows
            ]
        next_cursor = _encode_cursor(rows[-1]) if more and rows else None
        return responses, next_cursor

    async def add_public_comment(
        self,
        context: RequestContext,
        ticket_key: str,
        command: PublicCommentCreateRequest,
        idempotency_key: str,
    ) -> tuple[TicketResponse, bool]:
        tenant_id, user_id = _identity(context)
        self._authorize(context, Permission.TICKET_COMMENT_PUBLIC)
        body = command.body.strip()
        if not body:
            raise ValidationError(
                "Comment body is required.", field_errors={"body": ["Enter a public comment."]}
            )
        request_hash = hashlib.sha256(f"{ticket_key}:{body}".encode()).hexdigest()
        async with self._factory(context) as uow:
            repo = TicketRepository(uow.session)
            ticket = await self._commentable_ticket(repo, context, ticket_key, lock=True)
            idem = await repo.claim_idempotency(
                tenant_id,
                user_id,
                idempotency_key,
                request_hash,
                "TICKET_PUBLIC_COMMENT_CREATE",
            )
            if idem.request_hash != request_hash or idem.principal_id != str(user_id):
                raise IdempotencyConflict()
            if idem.processing_status == "COMPLETED":
                comments = await repo.public_comments(ticket.ticket_id)
                return _ticket_response(ticket, comments), True
            comment_id = await repo.add_public_comment(
                tenant_id,
                ticket.ticket_id,
                user_id,
                body,
                context.correlation_id,
                context.request_id,
                sla_event_type=(
                    "AGENT_PUBLIC_RESPONSE_ADDED"
                    if self._authorization.is_allowed(context, Permission.TICKET_ANALYST_READ)
                    else "CUSTOMER_COMMENT_ADDED"
                ),
            )
            await repo.complete_idempotency(
                idem.idempotency_record_id,
                "TICKET_COMMENT",
                comment_id,
                {"comment_id": str(comment_id), "ticket_key": ticket_key},
            )
            await uow.commit()
        return await self._ticket_for_context(context, ticket_key), False

    async def _ticket_for_context(self, context: RequestContext, ticket_key: str) -> TicketResponse:
        if self._authorization.is_allowed(context, Permission.TICKET_ANALYST_READ):
            return await self.analyst_ticket(context, ticket_key)
        return await self.get_ticket(context, ticket_key)

    async def _commentable_ticket(
        self,
        repo: TicketRepository,
        context: RequestContext,
        ticket_key: str,
        *,
        lock: bool,
    ) -> TicketView:
        tenant_id, user_id = _identity(context)
        own = await repo.ticket(tenant_id, user_id, key=ticket_key, lock=lock)
        if own is not None:
            return own
        if not self._authorization.is_allowed(context, Permission.TICKET_ANALYST_READ):
            raise NotFoundError("Ticket was not found.")
        analyst = await repo.analyst_ticket(
            tenant_id,
            context.support_group_ids,
            key=ticket_key,
            include_all=self._authorization.is_allowed(context, Permission.TICKET_READ_ALL),
            lock=lock,
        )
        if analyst is None:
            raise NotFoundError("Ticket was not found.")
        return analyst

    async def _priority(
        self,
        repo: TicketRepository,
        tenant_id: UUID,
        project_id: UUID,
        service_id: UUID | None,
        impact: str,
        urgency: str,
    ) -> tuple[str, UUID]:
        try:
            value = await repo.priority(tenant_id, project_id, service_id, impact, urgency)
        except RuntimeError:
            raise TicketConfigurationError() from None
        if value is None:
            raise TicketConfigurationError()
        return value

    async def _validate_references(
        self,
        context: RequestContext,
        repo: TicketRepository,
        catalogue: CatalogueConfigurationService,
        tenant_id: UUID,
        user_id: UUID,
        command: DraftCreateRequest,
    ) -> None:
        if command.requested_for_user_id not in {None, user_id}:
            self._authorize(context, Permission.TICKET_REQUEST_FOR_OTHER)
            requested_for = cast(UUID, command.requested_for_user_id)
            if not await repo.reference_user_exists(tenant_id, requested_for):
                raise ValidationError("Requested-for user is invalid.")
        if command.service_node_id and not await catalogue.service_node_exists(
            tenant_id, command.service_node_id
        ):
            raise ValidationError("Service is invalid.")
        if command.application_environment_id and not await repo.environment_exists(
            tenant_id, command.application_environment_id, command.service_node_id
        ):
            raise ValidationError("Environment is invalid.")

    async def _validate_form_references(
        self,
        repo: TicketRepository,
        catalogue: CatalogueConfigurationService,
        tenant_id: UUID,
        fields: list[Any],
        values: dict[str, Any],
    ) -> None:
        types = {field.field_code: field.data_type for field in fields}
        errors: dict[str, list[str]] = {}
        for code, value in values.items():
            if value is None:
                continue
            data_type = types.get(code)
            if data_type == "USER" and not await repo.reference_user_exists(
                tenant_id, UUID(str(value))
            ):
                errors[f"custom_fields.{code}"] = ["User reference is unavailable."]
            if data_type in {"SERVICE", "MODULE"} and not await catalogue.service_node_exists(
                tenant_id, UUID(str(value))
            ):
                errors[f"custom_fields.{code}"] = ["Service reference is unavailable."]
        if errors:
            raise ValidationError("The draft contains unavailable references.", field_errors=errors)

    def _authorize(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(
            context, permission, AuthorizationResource(tenant_id=context.tenant_id)
        ):
            self._metrics.authorization_denials += 1
            raise AuthorizationError(
                "The authenticated user is not permitted to perform this operation."
            )

    def _record(
        self, operation: str, started: float, outcome: str, *, ticket_key: str | None = None
    ) -> None:
        duration_ms = (time.perf_counter() - started) * 1000
        self._metrics.record(operation, started)
        logger.info(
            "Ticket operation completed",
            extra={
                "operation": operation,
                "outcome": outcome,
                "duration_ms": round(duration_ms, 3),
                "ticket_key": ticket_key,
            },
        )

    async def _require_owned(
        self,
        uow: SqlAlchemyUnitOfWork,
        repo: TicketRepository,
        draft: TicketDraft | None,
        user_id: UUID,
        context: RequestContext,
    ) -> None:
        if draft is None:
            raise NotFoundError("Ticket draft was not found.")
        if draft.owner_user_id == user_id:
            return
        self._metrics.authorization_denials += 1
        await repo.audit(
            draft,
            "TICKET_DRAFT_ACCESS_DENIED",
            "DENIED",
            context.correlation_id,
            context.request_id,
            actor_user_id=user_id,
        )
        await uow.commit()
        raise NotFoundError("Ticket draft was not found.")

    @staticmethod
    def _own(draft: TicketDraft | None, user_id: UUID) -> None:
        if draft is None or draft.owner_user_id != user_id:
            raise NotFoundError("Ticket draft was not found.")


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise AuthorizationError()
    return context.tenant_id, context.user_id


def _summary(value: str) -> str:
    return " ".join(value.split())


def _description(value: str | None) -> str | None:
    normalized = value.strip() if value else ""
    return normalized or None


def _form_inputs(
    summary: str, description: str | None, supplied: list[CustomFieldInput], fields: list[Any]
) -> list[CustomFieldInput]:
    reserved = {field.field_code for field in fields} & {"summary", "description"}
    if any(item.field_code in reserved for item in supplied):
        raise ValidationError("Reserved fields must use their top-level properties.")
    result = list(supplied)
    if "summary" in reserved:
        result.append(CustomFieldInput(field_code="summary", value=summary))
    if "description" in reserved:
        result.append(CustomFieldInput(field_code="description", value=description))
    return result


def _stored_inputs(values: dict[str, Any]) -> list[CustomFieldInput]:
    return [CustomFieldInput(field_code=key, value=value) for key, value in values.items()]


def _draft_response(
    draft: TicketDraft, fields: list[Any], ticket_key: str | None = None
) -> DraftResponse:
    types = {field.field_code: field.data_type for field in fields}
    normalized = [
        NormalizedField(field_code=key, data_type=types.get(key, "UNKNOWN"), value=value)
        for key, value in sorted(draft.custom_values.items())
    ]
    return DraftResponse(
        id=draft.draft_id,
        request_type_id=draft.request_type_id,
        request_type_version_id=draft.request_type_version_id,
        project_id=draft.project_id,
        service_node_id=draft.service_node_id,
        application_environment_id=draft.application_environment_id,
        owner_user_id=draft.owner_user_id,
        requested_for_user_id=draft.requested_for_user_id,
        summary=draft.summary,
        description=draft.description,
        impact=draft.impact_code,
        urgency=draft.urgency_code,
        priority=draft.priority_code,
        status=cast(Any, draft.status),
        custom_fields=normalized,
        row_version=draft.row_version,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
        expires_at=draft.expires_at,
        submitted_ticket_key=ticket_key,
    )


def _ticket_response(
    ticket: TicketView, comments: list[PublicComment] | None = None
) -> TicketResponse:
    return TicketResponse(
        id=ticket.ticket_id,
        key=ticket.ticket_key,
        summary=ticket.summary,
        description=ticket.description,
        project_code=ticket.project_code,
        project_name=ticket.project_name,
        request_type_code=ticket.request_type_code,
        request_type_name=ticket.request_type_name,
        service_name=ticket.service_name,
        environment_name=ticket.environment_name,
        work_type=ticket.work_type_code,
        status=ticket.status_code,
        status_name=ticket.status_name,
        priority=ticket.priority_code,
        reporter_user_id=ticket.reporter_user_id,
        reporter_name=ticket.reporter_name,
        requested_for_user_id=ticket.requested_for_user_id,
        requested_for_name=ticket.requested_for_name,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        creation_event_at=ticket.created_event_at,
        row_version=ticket.row_version,
        public_comments=[
            PublicCommentResponse(
                id=comment.comment_id,
                author_user_id=comment.author_user_id,
                author_name=comment.author_name,
                body=comment.body,
                created_at=comment.created_at,
            )
            for comment in comments or []
        ],
    )


def _encode_cursor(ticket: TicketView) -> str:
    raw = f"{ticket.created_at.isoformat()}|{ticket.ticket_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[datetime | None, UUID | None]:
    if value is None:
        return None, None
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        timestamp, identifier = decoded.split("|", 1)
        return datetime.fromisoformat(timestamp), UUID(identifier)
    except (ValueError, UnicodeDecodeError):
        raise ValidationError(
            "Pagination cursor is invalid.", field_errors={"cursor": ["Invalid cursor."]}
        ) from None
