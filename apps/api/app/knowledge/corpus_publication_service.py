"""Authorized, idempotent corpus publication and one-step rollback."""

from typing import Literal
from uuid import UUID, uuid4

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, ConflictError
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.knowledge.corpus_publication_models import (
    CorpusPublicationEvent,
    CorpusVersion,
    PublicationReadiness,
)
from apps.api.app.knowledge.corpus_publication_repository import (
    CorpusPublicationRepository,
)
from apps.api.app.knowledge.corpus_publication_schemas import (
    ActiveCorpusVersionResponse,
    CorpusPublicationEventResponse,
    CorpusPublicationReadinessResponse,
    CorpusVersionHistoryResponse,
    CorpusVersionResponse,
)
from apps.api.app.knowledge.corpus_validation_service import (
    UnitOfWorkFactory,
    _hash,
    _identity,
    _validate_claim,
)
from apps.api.app.knowledge.repository import KnowledgeSourceRepository

PublicationBlocker = Literal[
    "NO_VALIDATION_RUN",
    "VALIDATION_RUN_INCOMPLETE",
    "VALIDATION_RUN_TRUNCATED",
    "VALIDATION_STALE",
]


class CorpusPublicationService:
    def __init__(self, factory: UnitOfWorkFactory, authorization: AuthorizationService) -> None:
        self._factory = factory
        self._authorization = authorization

    async def publish(self, context: RequestContext, idempotency_key: str) -> CorpusVersionResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_PUBLISH)
        tenant_id, user_id = _identity(context)
        request_hash = _hash("corpus-publication", {"tenant_id": str(tenant_id)})
        async with self._factory(context) as uow:
            sources = KnowledgeSourceRepository(uow.session)
            claim = await sources.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_CORPUS_PUBLICATION"
            )
            _validate_claim(claim, user_id, request_hash)
            repo = CorpusPublicationRepository(uow.session)
            if claim.processing_status == "COMPLETED":
                version = await self._claimed_version(repo, tenant_id, claim.result_resource_id)
                await uow.commit()
                return _version_response(version, replayed=True)
            readiness = await repo.readiness(tenant_id)
            blockers = _blockers(readiness)
            if blockers:
                raise ConflictError("Corpus publication is blocked: " + ", ".join(blockers) + ".")
            if readiness.validation_run_id is None:  # pragma: no cover - guarded above
                raise ConflictError("Corpus publication is blocked: NO_VALIDATION_RUN.")
            previous_id = await repo.deactivate_active(tenant_id)
            corpus_version_id = uuid4()
            documents, chunks = await repo.corpus_counts(tenant_id)
            version_number = await repo.insert_version(
                corpus_version_id,
                tenant_id,
                readiness.validation_run_id,
                user_id,
                document_count=documents,
                chunk_count=chunks,
            )
            suppressed = await repo.snapshot_suppressed_chunks(corpus_version_id, tenant_id)
            evidence = {
                "version_number": version_number,
                "validation_run_id": str(readiness.validation_run_id),
                "document_count": documents,
                "chunk_count": chunks,
                "suppressed_chunk_count": suppressed,
            }
            await repo.insert_event(
                tenant_id,
                "PUBLISHED",
                corpus_version_id,
                previous_id,
                user_id,
                evidence,
                context.correlation_id,
                context.request_id,
                f"corpus-publish:{idempotency_key}",
            )
            await repo.audit(
                tenant_id,
                user_id,
                "KNOWLEDGE_CORPUS_PUBLICATION",
                corpus_version_id,
                evidence,
                context.correlation_id,
                context.request_id,
            )
            await sources.complete_idempotency(
                claim.record_id, "CORPUS_VERSION", corpus_version_id, 201
            )
            version = await self._claimed_version(repo, tenant_id, str(corpus_version_id))
            await uow.commit()
        return _version_response(version, replayed=False)

    async def rollback(
        self, context: RequestContext, idempotency_key: str
    ) -> CorpusVersionResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_PUBLISH)
        tenant_id, user_id = _identity(context)
        request_hash = _hash("corpus-rollback", {"tenant_id": str(tenant_id)})
        async with self._factory(context) as uow:
            sources = KnowledgeSourceRepository(uow.session)
            claim = await sources.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_CORPUS_ROLLBACK"
            )
            _validate_claim(claim, user_id, request_hash)
            repo = CorpusPublicationRepository(uow.session)
            if claim.processing_status == "COMPLETED":
                version = await self._claimed_version(repo, tenant_id, claim.result_resource_id)
                await uow.commit()
                return _version_response(version, replayed=True)
            active = await repo.active_version(tenant_id)
            if active is None:
                raise ConflictError("Corpus rollback requires an active published version.")
            target = await repo.previous_version(tenant_id, active.version_number)
            if target is None:
                raise ConflictError("Corpus rollback requires a prior published version.")
            await repo.deactivate_active(tenant_id)
            await repo.activate_version(tenant_id, target.corpus_version_id)
            evidence = {
                "restored_version_number": target.version_number,
                "rolled_back_version_number": active.version_number,
                "suppressed_chunk_count": target.suppressed_chunk_count,
            }
            await repo.insert_event(
                tenant_id,
                "ROLLED_BACK",
                target.corpus_version_id,
                active.corpus_version_id,
                user_id,
                evidence,
                context.correlation_id,
                context.request_id,
                f"corpus-rollback:{idempotency_key}",
            )
            await repo.audit(
                tenant_id,
                user_id,
                "KNOWLEDGE_CORPUS_ROLLBACK",
                target.corpus_version_id,
                evidence,
                context.correlation_id,
                context.request_id,
            )
            await sources.complete_idempotency(
                claim.record_id, "CORPUS_VERSION", target.corpus_version_id, 201
            )
            version = await self._claimed_version(repo, tenant_id, str(target.corpus_version_id))
            await uow.commit()
        return _version_response(version, replayed=False)

    async def active(self, context: RequestContext) -> ActiveCorpusVersionResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            repo = CorpusPublicationRepository(uow.session)
            active = await repo.active_version(tenant_id)
            readiness = await repo.readiness(tenant_id)
        return ActiveCorpusVersionResponse(
            active_version=(None if active is None else _version_response(active, replayed=False)),
            readiness=_readiness_response(readiness),
        )

    async def history(
        self, context: RequestContext, *, limit: int, offset: int
    ) -> CorpusVersionHistoryResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            repo = CorpusPublicationRepository(uow.session)
            versions = await repo.versions(tenant_id, limit=limit, offset=offset)
            events = await repo.events(tenant_id, limit=limit, offset=offset)
        return CorpusVersionHistoryResponse(
            versions=[_version_response(version, replayed=False) for version in versions],
            events=[_event_response(event) for event in events],
        )

    async def _claimed_version(
        self,
        repo: CorpusPublicationRepository,
        tenant_id: UUID,
        resource_id: str | None,
    ) -> CorpusVersion:
        if resource_id is None:
            raise ConflictError("Corpus publication result is unavailable.")
        version = await repo.version(tenant_id, UUID(resource_id))
        if version is None:
            raise ConflictError("Corpus publication result is unavailable.")
        return version

    def _require(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError()


def _blockers(readiness: PublicationReadiness) -> list[PublicationBlocker]:
    if readiness.validation_run_id is None:
        return ["NO_VALIDATION_RUN"]
    blockers: list[PublicationBlocker] = []
    if not readiness.run_completed:
        blockers.append("VALIDATION_RUN_INCOMPLETE")
    if readiness.truncated:
        blockers.append("VALIDATION_RUN_TRUNCATED")
    if readiness.stale:
        blockers.append("VALIDATION_STALE")
    return blockers


def _readiness_response(readiness: PublicationReadiness) -> CorpusPublicationReadinessResponse:
    blockers = _blockers(readiness)
    return CorpusPublicationReadinessResponse(
        publishable=not blockers,
        blockers=list(blockers),
        validation_run_id=readiness.validation_run_id,
        suppression_flagged_chunks=readiness.suppression_flagged_chunks,
    )


def _version_response(version: CorpusVersion, *, replayed: bool) -> CorpusVersionResponse:
    return CorpusVersionResponse(
        id=version.corpus_version_id,
        version_number=version.version_number,
        validation_run_id=version.validation_run_id,
        published_by=version.published_by,
        published_at=version.published_at,
        document_count=version.document_count,
        chunk_count=version.chunk_count,
        suppressed_chunk_count=version.suppressed_chunk_count,
        active=version.active_flag,
        replayed=replayed,
    )


def _event_response(event: CorpusPublicationEvent) -> CorpusPublicationEventResponse:
    action = event.action_code
    if action not in {"PUBLISHED", "ROLLED_BACK"}:
        raise ConflictError("Corpus publication event action is invalid.")
    return CorpusPublicationEventResponse(
        id=event.publication_event_id,
        action="PUBLISHED" if action == "PUBLISHED" else "ROLLED_BACK",
        corpus_version_number=event.corpus_version_number,
        previous_corpus_version_number=event.previous_corpus_version_number,
        actor_user_id=event.actor_user_id,
        evidence=event.evidence_json,
        occurred_at=event.occurred_at,
    )
