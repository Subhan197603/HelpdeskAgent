"""Governed administration of the synonym and acronym registry.

The registry records administrative vocabulary decisions only. Nothing in
this service is reachable from the retrieval path; only the separately
approved Task 15.2 may apply APPROVED entries during retrieval.
"""

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, ConflictError
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.knowledge.corpus_validation_service import (
    _hash,
    _identity,
    _validate_claim,
)
from apps.api.app.knowledge.repository import KnowledgeSourceRepository
from apps.api.app.knowledge.retrieval_synonym_repository import RetrievalSynonymRepository
from apps.api.app.knowledge.retrieval_synonym_schemas import (
    RetrievalSynonymCommand,
    RetrievalSynonymListResponse,
    RetrievalSynonymResponse,
    SynonymStatus,
)

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]

MAX_ACTIVE_EXPANSIONS = 10
_ALLOWED_TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("DRAFT", "DRAFT"),
        ("DRAFT", "APPROVED"),
        ("DRAFT", "RETIRED"),
        ("APPROVED", "RETIRED"),
        ("RETIRED", "DRAFT"),
    }
)


def normalize_synonym_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


class RetrievalSynonymService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
    ) -> None:
        self._factory = factory
        self._authorization = authorization

    async def list_entries(
        self,
        context: RequestContext,
        *,
        status: SynonymStatus | None,
        term: str | None,
        limit: int,
        offset: int,
    ) -> RetrievalSynonymListResponse:
        tenant_id = self._tenant(context)
        term_prefix = normalize_synonym_text(term) if term else None
        async with self._factory(context) as uow:
            rows = await RetrievalSynonymRepository(uow.session).list_entries(
                tenant_id,
                status=status,
                term=term_prefix or None,
                limit=limit + 1,
                offset=offset,
            )
        return RetrievalSynonymListResponse(
            items=[_entry_response(row, replayed=False) for row in rows[:limit]],
            has_more=len(rows) > limit,
        )

    async def change(
        self,
        context: RequestContext,
        command: RetrievalSynonymCommand,
        idempotency_key: str,
    ) -> RetrievalSynonymResponse:
        if not self._authorization.is_allowed(context, Permission.KNOWLEDGE_SOURCE_UPDATE):
            raise AuthorizationError()
        tenant_id, user_id = _identity(context)
        term = normalize_synonym_text(command.term)
        expansion = normalize_synonym_text(command.expansion)
        if not term or not expansion or term == expansion:
            raise ConflictError("Synonym term and expansion must differ and be non-empty.")
        request_hash = _hash(
            "retrieval-synonym-change",
            {
                "tenant_id": str(tenant_id),
                "term": term,
                "expansion": expansion,
                "synonym_status": command.synonym_status,
                "synonym_note": command.synonym_note,
                "expected_row_version": command.expected_row_version,
            },
        )
        async with self._factory(context) as uow:
            sources = KnowledgeSourceRepository(uow.session)
            claim = await sources.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_SYNONYM_CHANGE"
            )
            _validate_claim(claim, user_id, request_hash)
            repository = RetrievalSynonymRepository(uow.session)
            if claim.processing_status == "COMPLETED":
                row = await repository.entry(tenant_id, term, expansion)
                if row is None:
                    raise ConflictError("Synonym change result is unavailable.")
                await uow.commit()
                return _entry_response(row, replayed=True)
            previous = await repository.entry(tenant_id, term, expansion)
            if command.expected_row_version is None:
                if previous is not None:
                    raise ConflictError(
                        "Synonym entry already exists; supply expected_row_version."
                    )
                if command.synonym_status != "DRAFT":
                    raise ConflictError("New synonym entries must start in DRAFT.")
                await self._enforce_expansion_cap(repository, tenant_id, term)
                row = await repository.insert_entry(
                    tenant_id,
                    term=term,
                    expansion=expansion,
                    status=command.synonym_status,
                    note=command.synonym_note,
                    decided_by=user_id,
                )
            else:
                if previous is not None and (
                    (previous.synonym_status, command.synonym_status) not in _ALLOWED_TRANSITIONS
                ):
                    raise ConflictError(
                        "Synonym status transition "
                        f"{previous.synonym_status} to {command.synonym_status} "
                        "is not allowed."
                    )
                if previous is not None and previous.synonym_status == "RETIRED":
                    await self._enforce_expansion_cap(repository, tenant_id, term)
                row = await repository.update_entry(
                    tenant_id,
                    term=term,
                    expansion=expansion,
                    status=command.synonym_status,
                    note=command.synonym_note,
                    decided_by=user_id,
                    expected_row_version=command.expected_row_version,
                )
            if row is None:
                raise ConflictError("Synonym entry was changed concurrently; reload and retry.")
            await repository.audit_entry(
                tenant_id,
                user_id,
                row.synonym_id,
                {
                    "term": term,
                    "expansion": expansion,
                    "synonym_status": command.synonym_status,
                    "synonym_note": command.synonym_note,
                    "previous_status": (previous.synonym_status if previous is not None else None),
                    "row_version": int(row.row_version),
                },
                context.correlation_id,
                context.request_id,
            )
            await sources.complete_idempotency(
                claim.record_id, "KNOWLEDGE_SYNONYM", row.synonym_id, 201
            )
            await uow.commit()
        return _entry_response(row, replayed=False)

    async def _enforce_expansion_cap(
        self, repository: RetrievalSynonymRepository, tenant_id: UUID, term: str
    ) -> None:
        if await repository.active_expansion_count(tenant_id, term) >= MAX_ACTIVE_EXPANSIONS:
            raise ConflictError(
                f"Term already has {MAX_ACTIVE_EXPANSIONS} active expansions; retire one first."
            )

    def _tenant(self, context: RequestContext) -> UUID:
        if not self._authorization.is_allowed(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN):
            raise AuthorizationError()
        if context.tenant_id is None or context.user_id is None:
            raise AuthorizationError()
        return context.tenant_id


def _entry_response(row: Any, *, replayed: bool) -> RetrievalSynonymResponse:
    return RetrievalSynonymResponse(
        synonym_id=row.synonym_id,
        term=row.term,
        expansion=row.expansion,
        synonym_status=row.synonym_status,
        synonym_note=row.synonym_note,
        decided_at=row.decided_at,
        row_version=int(row.row_version),
        replayed=replayed,
    )
