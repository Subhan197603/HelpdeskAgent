"""Authorized, idempotent corpus validation over the tenant-visible corpus."""

import hashlib
import json
from collections.abc import Callable
from uuid import UUID, uuid4

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
)
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.knowledge.corpus_validation_models import (
    CorpusValidationFinding,
    CorpusValidationRun,
)
from apps.api.app.knowledge.corpus_validation_repository import (
    CorpusValidationRepository,
)
from apps.api.app.knowledge.corpus_validation_schemas import (
    CorpusFindingType,
    CorpusRunStatus,
    CorpusValidationFindingResponse,
    CorpusValidationReportResponse,
    CorpusValidationSummary,
)
from apps.api.app.knowledge.models import IdempotencyClaim
from apps.api.app.knowledge.repository import KnowledgeSourceRepository

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]

# Cosine similarity at or above this value marks a cross-document chunk pair
# as near-duplicate. Recorded on every run row for auditability.
NEAR_DUPLICATE_SIMILARITY_THRESHOLD = 0.95
_FINDING_PAGE_LIMIT = 500


class CorpusValidationService:
    def __init__(self, factory: UnitOfWorkFactory, authorization: AuthorizationService) -> None:
        self._factory = factory
        self._authorization = authorization

    async def run_validation(
        self, context: RequestContext, idempotency_key: str
    ) -> CorpusValidationReportResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_PUBLISH)
        tenant_id, user_id = _identity(context)
        request_hash = _hash("corpus-validation", {"tenant_id": str(tenant_id)})
        async with self._factory(context) as uow:
            sources = KnowledgeSourceRepository(uow.session)
            claim = await sources.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_CORPUS_VALIDATION"
            )
            _validate_claim(claim, user_id, request_hash)
            repo = CorpusValidationRepository(uow.session)
            if claim.processing_status == "COMPLETED":
                if claim.result_resource_id is None:
                    raise ConflictError("Corpus validation result is unavailable.")
                run = await repo.run(tenant_id, UUID(claim.result_resource_id))
                if run is None:
                    raise ConflictError("Corpus validation result is unavailable.")
                findings = await repo.findings(
                    tenant_id,
                    run.run_id,
                    finding_type=None,
                    limit=_FINDING_PAGE_LIMIT,
                    offset=0,
                )
                await uow.commit()
                return _report(run, findings, replayed=True)
            run_id = uuid4()
            await repo.create_run(
                run_id,
                tenant_id,
                user_id,
                NEAR_DUPLICATE_SIMILARITY_THRESHOLD,
                context.correlation_id,
                context.request_id,
            )
            documents, chunks = await repo.corpus_counts(tenant_id)
            structural, structural_over = await repo.insert_structural_findings(run_id, tenant_id)
            empty, empty_over = await repo.insert_empty_chunk_findings(run_id, tenant_id)
            duplicates, duplicates_over = await repo.insert_duplicate_document_findings(
                run_id, tenant_id
            )
            near, near_over = await repo.insert_near_duplicate_findings(
                run_id, tenant_id, NEAR_DUPLICATE_SIMILARITY_THRESHOLD
            )
            flagged = await repo.apply_suppression_flags(run_id, tenant_id)
            truncated = structural_over or empty_over or duplicates_over or near_over
            await repo.finalize_run(
                run_id,
                tenant_id,
                document_count=documents,
                chunk_count=chunks,
                structural_defects=structural,
                empty_chunks=empty,
                duplicate_documents=duplicates,
                near_duplicate_chunks=near,
                truncated=truncated,
            )
            await repo.audit(
                tenant_id,
                user_id,
                run_id,
                {
                    "documents": documents,
                    "chunks": chunks,
                    "structural_defects": structural,
                    "empty_chunks": empty,
                    "duplicate_documents": duplicates,
                    "near_duplicate_chunks": near,
                    "suppression_flagged_chunks": flagged,
                    "truncated": truncated,
                },
                context.correlation_id,
                context.request_id,
            )
            await sources.complete_idempotency(
                claim.record_id, "CORPUS_VALIDATION_RUN", run_id, 201
            )
            run = await repo.run(tenant_id, run_id)
            if run is None:
                raise ConflictError("Corpus validation result is unavailable.")
            findings = await repo.findings(
                tenant_id, run_id, finding_type=None, limit=_FINDING_PAGE_LIMIT, offset=0
            )
            await uow.commit()
        return _report(run, findings, replayed=False)

    async def latest_report(self, context: RequestContext) -> CorpusValidationReportResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            repo = CorpusValidationRepository(uow.session)
            run = await repo.latest_run(tenant_id)
            if run is None:
                return _empty_report()
            findings = await repo.findings(
                tenant_id, run.run_id, finding_type=None, limit=_FINDING_PAGE_LIMIT, offset=0
            )
        return _report(run, findings, replayed=False)

    async def report(
        self,
        context: RequestContext,
        run_id: UUID,
        *,
        finding_type: str | None,
        limit: int,
        offset: int,
    ) -> CorpusValidationReportResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            repo = CorpusValidationRepository(uow.session)
            run = await repo.run(tenant_id, run_id)
            if run is None:
                raise NotFoundError("Corpus validation run was not found.")
            findings = await repo.findings(
                tenant_id, run_id, finding_type=finding_type, limit=limit, offset=offset
            )
        return _report(run, findings, replayed=False)

    def _require(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError()


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise AuthorizationError()
    return context.tenant_id, context.user_id


def _validate_claim(claim: IdempotencyClaim, user_id: UUID, request_hash: str) -> None:
    if claim.principal_id != str(user_id) or claim.request_hash != request_hash:
        raise ConflictError("Idempotency key was already used for another request.")
    if claim.processing_status not in {"IN_PROGRESS", "COMPLETED"}:
        raise ConflictError("Idempotent operation cannot be resumed.")


def _hash(operation: str, value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            {"operation": operation, **value}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def _empty_report() -> CorpusValidationReportResponse:
    return CorpusValidationReportResponse(
        run_id=None,
        status=None,
        requested_by=None,
        similarity_threshold=None,
        started_at=None,
        completed_at=None,
        summary=CorpusValidationSummary(),
        findings=[],
    )


def _report(
    run: CorpusValidationRun,
    findings: list[CorpusValidationFinding],
    *,
    replayed: bool,
) -> CorpusValidationReportResponse:
    return CorpusValidationReportResponse(
        run_id=run.run_id,
        status=_run_status(run.run_status),
        requested_by=run.requested_by,
        similarity_threshold=float(run.similarity_threshold),
        document_count=run.document_count,
        chunk_count=run.chunk_count,
        truncated=run.truncated_flag,
        started_at=run.started_at,
        completed_at=run.completed_at,
        summary=CorpusValidationSummary(
            structural_defects=run.structural_defect_count,
            empty_chunks=run.empty_chunk_count,
            duplicate_documents=run.duplicate_document_count,
            near_duplicate_chunks=run.near_duplicate_chunk_count,
        ),
        findings=[
            CorpusValidationFindingResponse(
                id=finding.finding_id,
                finding_type=_finding_type(finding.finding_type),
                document_id=finding.document_id,
                document_title=finding.document_title,
                document_version_id=finding.document_version_id,
                chunk_id=finding.chunk_id,
                counterpart_document_id=finding.counterpart_document_id,
                counterpart_document_title=finding.counterpart_document_title,
                counterpart_chunk_id=finding.counterpart_chunk_id,
                duplicate_group_key=finding.duplicate_group_key,
                similarity_score=(
                    None if finding.similarity_score is None else float(finding.similarity_score)
                ),
                suppression_flagged=finding.suppression_flagged,
                evidence=finding.evidence_json,
            )
            for finding in findings
        ],
        replayed=replayed,
    )


def _run_status(value: str) -> CorpusRunStatus:
    if value not in {"COMPLETED", "FAILED"}:
        raise ConflictError("Corpus validation run status is invalid.")
    return "COMPLETED" if value == "COMPLETED" else "FAILED"


def _finding_type(value: str) -> CorpusFindingType:
    allowed: dict[str, CorpusFindingType] = {
        "STRUCTURAL_DEFECT": "STRUCTURAL_DEFECT",
        "EMPTY_CHUNK": "EMPTY_CHUNK",
        "DUPLICATE_DOCUMENT": "DUPLICATE_DOCUMENT",
        "NEAR_DUPLICATE_CHUNK": "NEAR_DUPLICATE_CHUNK",
    }
    if value not in allowed:
        raise ConflictError("Corpus validation finding type is invalid.")
    return allowed[value]
