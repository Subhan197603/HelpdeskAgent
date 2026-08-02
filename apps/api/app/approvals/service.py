"""Version-pinned approval resolution and decision orchestration."""

import hashlib
import json
from collections.abc import Callable
from uuid import UUID

from apps.api.app.approvals.models import ApprovalDefinition, ApprovalTicket, ApprovalView
from apps.api.app.approvals.repository import ApprovalRepository
from apps.api.app.approvals.schemas import (
    ApprovalDecisionCommand,
    ApprovalDecisionResponse,
    ApprovalItem,
    ApprovalList,
)
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
from apps.api.app.tickets.service import IdempotencyConflict

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class ApprovalConfigurationError(ConflictError):
    error_code = "approval_configuration_conflict"


class ApprovalEngine:
    """Run approval state changes inside an existing unit of work."""

    def __init__(self, repository: ApprovalRepository) -> None:
        self._repository = repository

    async def request(
        self,
        tenant_id: UUID,
        ticket_id: UUID,
        approval_code: str,
        actor_user_id: UUID,
        correlation_id: str,
        request_id: str,
    ) -> UUID:
        ticket = await self._repository.ticket(tenant_id, ticket_id)
        if ticket is None:
            raise ApprovalConfigurationError("Approval ticket was not found.")
        definition = await self._repository.published_definition(
            tenant_id, ticket.project_id, approval_code
        )
        if definition is None:
            raise ApprovalConfigurationError(
                "No effective published approval definition matches the workflow action."
            )
        approvers = await self._resolve(ticket, definition)
        requester = ticket.requested_for_user_id or ticket.reporter_user_id
        if not definition.allow_requester_self_approval and requester in approvers:
            raise ApprovalConfigurationError(
                "The approval definition resolves the requester as an approver."
            )
        return await self._repository.create(
            ticket,
            definition,
            approvers,
            actor_user_id,
            correlation_id,
            request_id,
        )

    async def _resolve(self, ticket: ApprovalTicket, definition: ApprovalDefinition) -> list[UUID]:
        rule = definition.approver_rule
        if not isinstance(rule, dict):
            raise ApprovalConfigurationError("Approver rule must be an object.")
        if definition.mode in {"ANY_ONE_APPROVER", "ALL_APPROVERS"}:
            if not set(rule) <= {"user_ids", "rejection_comment_required"}:
                raise ApprovalConfigurationError("The approver rule contains unsupported keys.")
            raw_ids = rule.get("user_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                raise ApprovalConfigurationError("The approver rule must contain user_ids.")
            try:
                requested = list(dict.fromkeys(UUID(value) for value in raw_ids))
            except (TypeError, ValueError):
                raise ApprovalConfigurationError(
                    "The approver rule contains an invalid user ID."
                ) from None
            active = await self._repository.active_users(ticket.tenant_id, requested)
            if active != set(requested):
                raise ApprovalConfigurationError(
                    "Every configured approver must be active in the tenant."
                )
            return requested
        if definition.mode == "MANAGER_APPROVAL":
            if not set(rule) <= {"subject", "rejection_comment_required"}:
                raise ApprovalConfigurationError("The manager rule contains unsupported keys.")
            if rule.get("subject", "REQUESTED_FOR_OR_REPORTER") != "REQUESTED_FOR_OR_REPORTER":
                raise ApprovalConfigurationError("The manager approval subject is unsupported.")
            subject = ticket.requested_for_user_id or ticket.reporter_user_id
            manager = await self._repository.manager_for(ticket.tenant_id, subject)
            if manager is None:
                raise ApprovalConfigurationError("The approval subject has no active manager.")
            return [manager]
        raise ApprovalConfigurationError("The published approval mode is not supported.")

    async def cancel_for_ticket(
        self,
        tenant_id: UUID,
        ticket_id: UUID,
        actor_user_id: UUID,
        correlation_id: str,
        request_id: str,
    ) -> int:
        """Cancel all still-pending approvals after an explicit workflow reset."""
        return await self._repository.cancel_pending(
            tenant_id,
            ticket_id,
            actor_user_id,
            correlation_id,
            request_id,
        )


class ApprovalService:
    def __init__(self, factory: UnitOfWorkFactory, authorization: AuthorizationService) -> None:
        self._factory = factory
        self._authorization = authorization

    async def mine(self, context: RequestContext) -> ApprovalList:
        self._authorize(context, Permission.APPROVAL_READ_ASSIGNED)
        tenant_id, user_id = _identity(context)
        async with self._factory(context) as uow:
            views = await ApprovalRepository(uow.session).list_for_user(tenant_id, user_id)
        return ApprovalList(items=[_item(view) for view in views])

    async def decide(
        self,
        context: RequestContext,
        approval_id: UUID,
        command: ApprovalDecisionCommand,
        idempotency_key: str,
    ) -> ApprovalDecisionResponse:
        self._authorize(context, Permission.APPROVAL_DECIDE)
        tenant_id, user_id = _identity(context)
        comment = command.comment.strip() if command.comment and command.comment.strip() else None
        canonical = command.model_dump(mode="json")
        canonical["comment"] = comment
        request_hash = hashlib.sha256(
            json.dumps(
                {"approval_id": str(approval_id), **canonical},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        async with self._factory(context) as uow:
            repo = ApprovalRepository(uow.session)
            idem = await repo.claim_idempotency(tenant_id, user_id, idempotency_key, request_hash)
            if idem.request_hash != request_hash or idem.principal_id != str(user_id):
                raise IdempotencyConflict()
            if idem.processing_status == "COMPLETED":
                view = await repo.view_for_user(tenant_id, approval_id, user_id)
                if view is None:
                    raise NotFoundError("Approval was not found.")
                await uow.commit()
                return ApprovalDecisionResponse(approval=_item(view), replayed=True)
            approval = await repo.lock_for_decision(tenant_id, approval_id, user_id)
            if approval is None:
                raise NotFoundError("Approval was not found.")
            if await repo.expire_if_due(
                approval, user_id, context.correlation_id, context.request_id
            ):
                await uow.commit()
                raise ConflictError("Approval has expired.")
            if approval.status != "PENDING":
                raise ConflictError("Approval is no longer pending.")
            if approval.row_version != command.expected_version:
                raise ConcurrencyError("Approval row version is stale.")
            if approval.existing_decision is not None:
                raise ConflictError("The approver has already decided this approval.")
            if not approval.allow_requester_self_approval and approval.requester_user_id == user_id:
                raise AuthorizationError("Requesters may not approve their own request.")
            if (
                command.decision == "REJECT"
                and isinstance(approval.approver_rule, dict)
                and approval.approver_rule.get("rejection_comment_required") is True
                and comment is None
            ):
                raise ValidationError(
                    "A rejection comment is required.",
                    field_errors={"comment": ["Explain why the approval was rejected."]},
                )
            stored_decision = "APPROVED" if command.decision == "APPROVE" else "REJECTED"
            total, approved, rejected = await repo.decision_counts(approval_id)
            approved += stored_decision == "APPROVED"
            rejected += stored_decision == "REJECTED"
            terminal = _terminal_status(approval.mode, total, approved, rejected)
            new_version = await repo.record_decision(
                approval,
                user_id,
                stored_decision,
                comment,
                terminal,
                context.correlation_id,
                context.request_id,
            )
            if terminal is not None:
                transition_id = (
                    approval.approved_transition_id
                    if terminal == "APPROVED"
                    else approval.rejected_transition_id
                )
                if transition_id is None:
                    raise ApprovalConfigurationError(
                        "The terminal approval outcome has no workflow transition."
                    )
                try:
                    await repo.continue_workflow(
                        approval,
                        transition_id,
                        user_id,
                        context.correlation_id,
                        context.request_id,
                    )
                except RuntimeError as exc:
                    raise ApprovalConfigurationError(str(exc)) from None
            await repo.complete_idempotency(
                idem.idempotency_record_id,
                approval_id,
                {"approval_id": str(approval_id), "row_version": new_version},
            )
            await uow.commit()
        async with self._factory(context) as uow:
            view = await ApprovalRepository(uow.session).view_for_user(
                tenant_id, approval_id, user_id
            )
        if view is None:
            raise NotFoundError("Approval was not found.")
        return ApprovalDecisionResponse(approval=_item(view))

    def _authorize(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError("The authenticated user is not permitted to manage approvals.")


def _terminal_status(mode: str, total: int, approved: int, rejected: int) -> str | None:
    if mode in {"ANY_ONE_APPROVER", "MANAGER_APPROVAL"}:
        if approved:
            return "APPROVED"
        return "REJECTED" if rejected == total else None
    if mode == "ALL_APPROVERS":
        if rejected:
            return "REJECTED"
        return "APPROVED" if approved == total else None
    raise ApprovalConfigurationError("The approval mode is not supported.")


def _item(view: ApprovalView) -> ApprovalItem:
    return ApprovalItem(
        approval_id=view.approval_id,
        ticket_key=view.ticket_key,
        ticket_summary=view.ticket_summary,
        approval_code=view.approval_code,
        approval_name=view.approval_name,
        approval_mode=view.approval_mode,
        status=view.status,
        requested_at=view.requested_at,
        completed_at=view.completed_at,
        expires_at=view.expires_at,
        row_version=view.row_version,
        sequence_number=view.sequence_number,
        decision=view.decision,
        decision_comment=view.decision_comment,
        decided_at=view.decided_at,
    )


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise NotFoundError("Approval was not found.")
    return context.tenant_id, context.user_id
