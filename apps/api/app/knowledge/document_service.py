"""Human-authorized document review, publication, and retirement."""

import hashlib
import json
from collections.abc import Callable
from uuid import UUID

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    NotFoundError,
)
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.ingestion.repository import IngestionRepository
from apps.api.app.knowledge.document_models import ProcessingRecord
from apps.api.app.knowledge.document_repository import KnowledgeDocumentRepository
from apps.api.app.knowledge.document_schemas import (
    DocumentAdminResponse,
    DocumentApprovalCommand,
    DocumentVersionResponse,
    ProcessingVersionResponse,
    PublishDocumentCommand,
    RetireDocumentCommand,
)
from apps.api.app.knowledge.models import IdempotencyClaim
from apps.api.app.knowledge.repository import KnowledgeSourceRepository
from apps.api.app.knowledge.service import acquisition_permission_reasons

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class KnowledgeDocumentService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._settings = settings

    async def get(self, context: RequestContext, document_id: UUID) -> DocumentAdminResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            return await _response(KnowledgeDocumentRepository(uow.session), tenant_id, document_id)

    async def approve(
        self,
        context: RequestContext,
        document_id: UUID,
        command: DocumentApprovalCommand,
        idempotency_key: str,
    ) -> DocumentAdminResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_APPROVE)
        tenant_id, actor_id = _identity(context)
        request_hash = _hash("document-approval", document_id, command.model_dump(mode="json"))
        async with self._factory(context) as uow:
            idempotency = IngestionRepository(uow.session)
            claim = await idempotency.claim_idempotency(
                tenant_id, actor_id, idempotency_key, request_hash, "KNOWLEDGE_DOCUMENT_APPROVAL"
            )
            _validate_claim(claim, actor_id, request_hash)
            repo = KnowledgeDocumentRepository(uow.session)
            document = await repo.get(tenant_id, document_id, lock=True)
            if document is None:
                raise NotFoundError("Knowledge document was not found.")
            if claim.processing_status == "COMPLETED":
                response = await _response(repo, tenant_id, document_id, replayed=True)
                await uow.commit()
                return response
            source = await KnowledgeSourceRepository(uow.session).get(tenant_id, document.source_id)
            if source is None:
                raise ConflictError("Knowledge source is unavailable.")
            if source.owner_user_id == actor_id or (
                source.owner_group_id is not None
                and source.owner_group_id in context.support_group_ids
            ):
                raise AuthorizationError("A source owner cannot approve its document.")
            if not await repo.approve(
                tenant_id,
                document_id,
                actor_id,
                command.decision,
                command.expected_version,
            ):
                raise ConcurrencyError("Knowledge document row version is stale.")
            await repo.audit(
                document.tenant_id,
                actor_id,
                document_id,
                f"KNOWLEDGE_DOCUMENT_{command.decision}",
                {"reason": command.reason},
                context.correlation_id,
                context.request_id,
            )
            await idempotency.complete_idempotency(
                claim.record_id, "KNOWLEDGE_DOCUMENT", document_id, 200
            )
            response = await _response(repo, tenant_id, document_id)
            await uow.commit()
            return response

    async def publish(
        self,
        context: RequestContext,
        document_id: UUID,
        command: PublishDocumentCommand,
        idempotency_key: str,
    ) -> DocumentAdminResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_PUBLISH)
        tenant_id, actor_id = _identity(context)
        request_hash = _hash("document-publish", document_id, command.model_dump(mode="json"))
        async with self._factory(context) as uow:
            idempotency = IngestionRepository(uow.session)
            claim = await idempotency.claim_idempotency(
                tenant_id, actor_id, idempotency_key, request_hash, "KNOWLEDGE_DOCUMENT_PUBLISH"
            )
            _validate_claim(claim, actor_id, request_hash)
            repo = KnowledgeDocumentRepository(uow.session)
            document = await repo.get(tenant_id, document_id, lock=True)
            if document is None:
                raise NotFoundError("Knowledge document was not found.")
            if claim.processing_status == "COMPLETED":
                response = await _response(repo, tenant_id, document_id, replayed=True)
                await uow.commit()
                return response
            if document.row_version != command.expected_document_version:
                raise ConcurrencyError("Knowledge document row version is stale.")
            if document.approval_status != "APPROVED" or not document.active:
                raise ConflictError("Only an approved active document may be published.")
            candidate = await repo.publication_candidate(document_id, command.processing_version_id)
            if candidate is None:
                raise NotFoundError("Processing version was not found.")
            (
                document_version_id,
                processing_status,
                validation_status,
                chunk_count,
                embedded_count,
                parser,
                chunker,
                embedding_model,
            ) = candidate
            if processing_status != "COMPLETED" or validation_status not in {
                "PASSED",
                "WARNING",
            }:
                raise ConflictError("Only a completed valid processing version may be published.")
            if chunk_count < 1 or embedded_count != chunk_count:
                raise ConflictError("Publication requires complete chunks and embeddings.")
            source_repo = KnowledgeSourceRepository(uow.session)
            source = await source_repo.get(tenant_id, document.source_id)
            if source is None:
                raise ConflictError("Knowledge source is unavailable.")
            authorization = await source_repo.effective_authorization(tenant_id, source)
            external = source.acquisition_method != "MANUAL_UPLOAD"
            reasons = acquisition_permission_reasons(
                source, authorization, self._settings, external=external
            )
            if reasons:
                raise AuthorizationError("Publication permission denied: " + ",".join(reasons))
            (
                lineage_chunks,
                lineage_embeddings,
                lineage_valid,
                permissions,
            ) = await repo.lineage_evidence(document, command.processing_version_id)
            if (
                not lineage_valid
                or lineage_chunks != chunk_count
                or lineage_embeddings != chunk_count
            ):
                raise ConflictError("Chunk authorization lineage is incomplete.")
            evidence: dict[str, object] = {
                "tenant_id": str(tenant_id),
                "reason": command.reason,
                "document_row_version": document.row_version,
                "processing_version_id": str(command.processing_version_id),
                "parser": parser,
                "chunker": chunker,
                "embedding_model_code": embedding_model,
                "validation_status": validation_status,
                "chunk_count": chunk_count,
                "source_id": str(source.source_id),
                "source_row_version": source.row_version,
                "source_permission_reference": (
                    authorization.permission_reference
                    if authorization
                    else source.permission_reference
                ),
                "audience_code": document.audience_code,
                "security_classification": document.security_classification,
                "document_permissions": permissions,
            }
            published = await repo.publish(
                document,
                document_version_id,
                command.processing_version_id,
                actor_id,
                evidence,
                context.correlation_id,
                context.request_id,
                idempotency_key,
            )
            if published is None and not any(
                version.document_version_id == document_version_id and version.current
                for version in await repo.versions(document_id)
            ):
                raise ConflictError("Document publication failed.")
            await repo.audit(
                document.tenant_id,
                actor_id,
                document_id,
                "KNOWLEDGE_DOCUMENT_PUBLISHED",
                evidence,
                context.correlation_id,
                context.request_id,
            )
            await idempotency.complete_idempotency(
                claim.record_id, "KNOWLEDGE_DOCUMENT", document_id, 200
            )
            response = await _response(repo, tenant_id, document_id)
            await uow.commit()
            return response

    async def retire(
        self,
        context: RequestContext,
        document_id: UUID,
        command: RetireDocumentCommand,
        idempotency_key: str,
    ) -> DocumentAdminResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_RETIRE)
        tenant_id, actor_id = _identity(context)
        request_hash = _hash("document-retire", document_id, command.model_dump(mode="json"))
        async with self._factory(context) as uow:
            idempotency = IngestionRepository(uow.session)
            claim = await idempotency.claim_idempotency(
                tenant_id, actor_id, idempotency_key, request_hash, "KNOWLEDGE_DOCUMENT_RETIRE"
            )
            _validate_claim(claim, actor_id, request_hash)
            repo = KnowledgeDocumentRepository(uow.session)
            document = await repo.get(tenant_id, document_id, lock=True)
            if document is None:
                raise NotFoundError("Knowledge document was not found.")
            if claim.processing_status == "COMPLETED":
                response = await _response(repo, tenant_id, document_id, replayed=True)
                await uow.commit()
                return response
            if document.row_version != command.expected_version:
                raise ConcurrencyError("Knowledge document row version is stale.")
            evidence: dict[str, object] = {
                "tenant_id": str(tenant_id),
                "reason": command.reason,
                "document_row_version": document.row_version,
            }
            if not await repo.retire(
                document,
                actor_id,
                evidence,
                context.correlation_id,
                context.request_id,
                idempotency_key,
            ):
                raise ConflictError("Only a published document may be retired.")
            await repo.audit(
                document.tenant_id,
                actor_id,
                document_id,
                "KNOWLEDGE_DOCUMENT_RETIRED",
                evidence,
                context.correlation_id,
                context.request_id,
            )
            await idempotency.complete_idempotency(
                claim.record_id, "KNOWLEDGE_DOCUMENT", document_id, 200
            )
            response = await _response(repo, tenant_id, document_id)
            await uow.commit()
            return response

    def _require(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError()


async def _response(
    repo: KnowledgeDocumentRepository,
    tenant_id: UUID,
    document_id: UUID,
    *,
    replayed: bool = False,
) -> DocumentAdminResponse:
    document = await repo.get(tenant_id, document_id)
    if document is None:
        raise NotFoundError("Knowledge document was not found.")
    versions = await repo.versions(document_id)
    processing = await repo.processing_versions(document_id)
    by_version: dict[UUID, list[ProcessingRecord]] = {}
    for record in processing:
        by_version.setdefault(record.document_version_id, []).append(record)
    return DocumentAdminResponse(
        id=document.document_id,
        scope="GLOBAL" if document.tenant_id is None else "TENANT",
        source_id=document.source_id,
        title=document.title,
        document_type=document.document_type,
        audience_code=document.audience_code,
        security_classification=document.security_classification,
        approval_status=document.approval_status,
        approved_by=document.approved_by,
        approved_at=document.approved_at,
        active=document.active,
        row_version=document.row_version,
        created_at=document.created_at,
        updated_at=document.updated_at,
        versions=[
            DocumentVersionResponse(
                id=version.document_version_id,
                version_number=version.version_number,
                sha256_checksum=version.sha256_checksum,
                content_type=version.content_type,
                extraction_status=version.extraction_status,
                validation_status=version.validation_status,
                current=version.current,
                published_processing_version_id=version.published_processing_version_id,
                acquired_at=version.acquired_at,
                published_at=version.published_at,
                retired_at=version.retired_at,
                processing_versions=[
                    _processing_response(item)
                    for item in by_version.get(version.document_version_id, [])
                ],
            )
            for version in versions
        ],
        replayed=replayed,
    )


def _processing_response(value: ProcessingRecord) -> ProcessingVersionResponse:
    return ProcessingVersionResponse(
        id=value.processing_version_id,
        document_version_id=value.document_version_id,
        processing_number=value.processing_number,
        parser=value.parser_name,
        parser_version=value.parser_version,
        chunker=value.chunker_name,
        chunker_version=value.chunker_version,
        chunking_configuration_hash=value.chunking_configuration_hash,
        embedding_model_code=value.embedding_model_code,
        status=value.processing_status,
        validation_status=value.validation_status,
        validation=value.validation_json,
        chunk_count=value.chunk_count,
        embedded_chunk_count=value.embedded_chunk_count,
        created_at=value.created_at,
        completed_at=value.completed_at,
    )


def _validate_claim(claim: IdempotencyClaim, actor_id: UUID, request_hash: str) -> None:
    if claim.principal_id != str(actor_id) or claim.request_hash != request_hash:
        raise ConflictError("Idempotency key was already used for another request.")
    if claim.processing_status not in {"IN_PROGRESS", "COMPLETED"}:
        raise ConflictError("Idempotent operation cannot be resumed.")


def _hash(operation: str, document_id: UUID, value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            {"operation": operation, "document_id": str(document_id), **value},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise AuthorizationError()
    return context.tenant_id, context.user_id
