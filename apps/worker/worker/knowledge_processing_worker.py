"""Versioned parsing, chunking, embedding, and validation worker."""

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.app.attachments.storage import S3ObjectStorage, StorageError, WritableObjectStorage
from apps.api.app.core.settings import Settings
from apps.api.app.ingestion.models import ManifestEntry
from apps.api.app.ingestion.repository import IngestionRepository
from apps.api.app.knowledge.models import KnowledgeSource, SourceAuthorization
from apps.api.app.knowledge.repository import KnowledgeSourceRepository
from apps.api.app.knowledge.service import acquisition_permission_reasons
from apps.worker.worker.acquisition_worker import _context
from apps.worker.worker.settings import WorkerSettings
from ingestion.chunkers import Chunk, ChunkingConfig, SemanticChunker
from ingestion.embeddings import (
    DeterministicEmbeddingProvider,
    EmbeddingError,
    EmbeddingProvider,
    HttpEmbeddingProvider,
)
from ingestion.parsers import ParserRegistry, StoredFile
from ingestion.parsers.documents import DocumentParser, ParsingError
from ingestion.validation import ValidationContext, ValidationResult, validate_corpus

logger = logging.getLogger(__name__)


class PermanentProcessingError(RuntimeError):
    """Content or governance failure that cannot be retried."""


@dataclass(frozen=True, slots=True)
class ProcessingClaim:
    item_id: UUID
    tenant_id: UUID


@dataclass(frozen=True, slots=True)
class ProcessingWork:
    item_id: UUID
    run_id: UUID
    tenant_id: UUID
    processing_attempt_count: int
    source_row_version: int
    manifest_row_version: int
    original_key: str
    filename: str
    content_type: str
    document_id: UUID
    document_version_id: UUID
    document_title: str
    document_approval_status: str
    canonical_url: str | None
    language_code: str
    product_node_id: UUID | None
    release_id: UUID | None
    audience_code: str
    security_classification: str
    copyright_notice: str | None
    manifest: ManifestEntry
    source: KnowledgeSource
    authorization: SourceAuthorization | None


@dataclass(frozen=True, slots=True)
class ProcessingVersion:
    processing_version_id: UUID
    completed: bool


class KnowledgeProcessingWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: WorkerSettings,
        storage: WritableObjectStorage | None = None,
        embeddings: EmbeddingProvider | None = None,
        parsers: ParserRegistry | None = None,
        chunker: SemanticChunker | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._storage = storage or cast(
            "WritableObjectStorage", S3ObjectStorage(cast("Settings", settings))
        )
        self._embeddings = embeddings or _provider(settings)
        self._parsers = parsers or ParserRegistry()
        self._chunker = chunker or SemanticChunker(
            ChunkingConfig(
                target_tokens=settings.knowledge_chunk_target_tokens,
                maximum_tokens=settings.knowledge_chunk_maximum_tokens,
                minimum_tokens=settings.knowledge_chunk_minimum_tokens,
                overlap_tokens=settings.knowledge_chunk_overlap_tokens,
            )
        )

    async def process_one(self) -> bool:
        claim = await self._claim()
        if claim is None:
            return False
        work: ProcessingWork | None = None
        processing: ProcessingVersion | None = None
        try:
            work = await self._load(claim)
            reasons = _permission_reasons(work, self._settings)
            if reasons:
                raise PermanentProcessingError("PERMISSION_DENIED")
            parser = self._parsers.require(work.content_type)
            processing = await self._start_processing(work, parser)
            if processing.completed:
                await self._mark_replayed(work, processing.processing_version_id)
                return True
            content = await self._storage.read(
                work.original_key, self._settings.knowledge_document_max_bytes
            )
            parsed = await parser.parse(StoredFile(content, work.filename, work.content_type))
            normalized = parsed.normalized_text.encode()
            if not normalized:
                raise PermanentProcessingError("EMPTY_EXTRACTION")
            chunks = self._chunker.chunk(work.document_title, parsed)
            if not chunks:
                raise PermanentProcessingError("NO_CHUNKS")
            vectors = await self._embed(chunks)
            normalized_key = _normalized_key(work.original_key, processing.processing_version_id)
            await self._storage.write(normalized_key, normalized, "text/plain")
            validation_context = await self._validation_context(work, len(vectors))
            validation = validate_corpus(parsed, chunks, validation_context)
            await self._persist(
                work,
                processing.processing_version_id,
                parser,
                parsed.page_count,
                normalized,
                normalized_key,
                chunks,
                vectors,
                validation,
            )
        except (ParsingError, PermanentProcessingError) as error:
            if work is not None:
                await self._failed(
                    work,
                    processing.processing_version_id if processing else None,
                    str(error),
                    final=True,
                )
        except (EmbeddingError, StorageError) as error:
            if work is not None:
                await self._failed(
                    work,
                    processing.processing_version_id if processing else None,
                    type(error).__name__,
                    final=False,
                )
        except Exception as error:
            logger.exception(
                "Knowledge processing failed",
                extra={"item_id": str(claim.item_id), "error_code": type(error).__name__},
            )
            if work is not None:
                await self._failed(
                    work,
                    processing.processing_version_id if processing else None,
                    "UNEXPECTED_PROCESSING_ERROR",
                    final=False,
                )
        return True

    async def _claim(self) -> ProcessingClaim | None:
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    text("SELECT * FROM kb.claim_processing_item(:worker_id)"),
                    {"worker_id": self._settings.worker_id},
                )
            ).one_or_none()
            return ProcessingClaim(*tuple(row)) if row is not None else None

    async def _load(self, claim: ProcessingClaim) -> ProcessingWork:
        async with self._sessions() as session, session.begin():
            await _context(session, claim.tenant_id, claim.item_id)
            row = (
                await session.execute(
                    text("""
                        SELECT item.ingestion_run_id,item.manifest_entry_id,
                          item.processing_attempt_count,item.source_row_version,
                          item.manifest_entry_row_version,version.original_file_uri,
                          item.original_filename,version.content_type,
                          item.document_id AS item_document_id,
                          item.document_version_id,document.document_title,
                          document.approval_status,document.canonical_url,
                          document.language_code,document.product_node_id,document.release_id,
                          document.audience_code,document.security_classification,
                          version.copyright_notice
                        FROM kb.ingestion_run_item item
                        JOIN kb.document document ON document.document_id=item.document_id
                        JOIN kb.document_version version
                          ON version.document_version_id=item.document_version_id
                        WHERE item.ingestion_run_item_id=:item_id
                          AND item.tenant_id=:tenant_id AND item.item_status='EXTRACTING'
                          AND item.locked_by=:worker_id AND item.pipeline_stage='PROCESSING'
                    """),
                    {
                        "item_id": claim.item_id,
                        "tenant_id": claim.tenant_id,
                        "worker_id": self._settings.worker_id,
                    },
                )
            ).one_or_none()
            if row is None or row.item_document_id is None:
                raise PermanentProcessingError("PROCESSING_CLAIM_LOST")
            manifest = await IngestionRepository(session).manifest(
                claim.tenant_id, row.manifest_entry_id
            )
            if manifest is None:
                raise PermanentProcessingError("MANIFEST_NOT_FOUND")
            source_repo = KnowledgeSourceRepository(session)
            source = await source_repo.get(claim.tenant_id, manifest.source_id)
            if source is None:
                raise PermanentProcessingError("SOURCE_NOT_FOUND")
            authorization = await source_repo.effective_authorization(claim.tenant_id, source)
            return ProcessingWork(
                claim.item_id,
                row.ingestion_run_id,
                claim.tenant_id,
                row.processing_attempt_count,
                row.source_row_version,
                row.manifest_entry_row_version,
                row.original_file_uri,
                row.original_filename or "document.bin",
                row.content_type,
                row.item_document_id,
                row.document_version_id,
                row.document_title,
                row.approval_status,
                row.canonical_url,
                row.language_code,
                row.product_node_id,
                row.release_id,
                row.audience_code,
                row.security_classification,
                row.copyright_notice,
                manifest,
                source,
                authorization,
            )

    async def _start_processing(
        self, work: ProcessingWork, parser: DocumentParser
    ) -> ProcessingVersion:
        if self._embeddings.dimension != 1536:
            raise PermanentProcessingError("UNSUPPORTED_EMBEDDING_DIMENSION")
        async with self._sessions() as session, session.begin():
            await _context(session, work.tenant_id, work.item_id)
            model_dimension = await session.scalar(
                text("""
                    SELECT vector_dimension FROM kb.embedding_model
                    WHERE embedding_model_code=:model_code AND active_flag
                """),
                {"model_code": self._embeddings.model_code},
            )
            if model_dimension != self._embeddings.dimension:
                raise PermanentProcessingError("EMBEDDING_MODEL_NOT_APPROVED")
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"processing:{work.document_version_id}"},
            )
            existing = (
                await session.execute(
                    text("""
                        SELECT processing_version_id,processing_status
                        FROM kb.document_processing_version
                        WHERE document_version_id=:version_id AND parser_name=:parser_name
                          AND parser_version=:parser_version
                          AND chunker_name=:chunker_name
                          AND chunker_version=:chunker_version
                          AND chunking_configuration_hash=:chunk_hash
                          AND embedding_model_code=:model_code
                        FOR UPDATE
                    """),
                    {
                        "version_id": work.document_version_id,
                        "parser_name": parser.name,
                        "parser_version": parser.version,
                        "chunker_name": self._chunker.name,
                        "chunker_version": self._chunker.version,
                        "chunk_hash": self._chunker.config.digest,
                        "model_code": self._embeddings.model_code,
                    },
                )
            ).one_or_none()
            if existing is not None:
                if existing.processing_status == "COMPLETED":
                    return ProcessingVersion(existing.processing_version_id, True)
                await session.execute(
                    text("""
                        UPDATE kb.document_processing_version
                        SET processing_status='RUNNING',validation_status='PENDING',
                          validation_json='{}'::jsonb,started_at=now(),completed_at=NULL
                        WHERE processing_version_id=:processing_id
                    """),
                    {"processing_id": existing.processing_version_id},
                )
                return ProcessingVersion(existing.processing_version_id, False)
            processing_id = uuid4()
            next_number = int(
                await session.scalar(
                    text("""
                        SELECT coalesce(max(processing_number),0)+1
                        FROM kb.document_processing_version
                        WHERE document_version_id=:version_id
                    """),
                    {"version_id": work.document_version_id},
                )
                or 1
            )
            await session.execute(
                text("""
                    INSERT INTO kb.document_processing_version(
                      processing_version_id,tenant_id,document_id,document_version_id,
                      processing_number,parser_name,parser_version,chunker_name,
                      chunker_version,chunking_configuration_json,
                      chunking_configuration_hash,embedding_model_code)
                    VALUES (:processing_id,:tenant_id,:document_id,:version_id,:number,
                      :parser_name,:parser_version,:chunker_name,:chunker_version,
                      CAST(:chunk_config AS jsonb),:chunk_hash,:model_code)
                """),
                {
                    "processing_id": processing_id,
                    "tenant_id": work.tenant_id,
                    "document_id": work.document_id,
                    "version_id": work.document_version_id,
                    "number": next_number,
                    "parser_name": parser.name,
                    "parser_version": parser.version,
                    "chunker_name": self._chunker.name,
                    "chunker_version": self._chunker.version,
                    "chunk_config": json.dumps(asdict(self._chunker.config)),
                    "chunk_hash": self._chunker.config.digest,
                    "model_code": self._embeddings.model_code,
                },
            )
            return ProcessingVersion(processing_id, False)

    async def _embed(self, chunks: tuple[Chunk, ...]) -> list[list[float]]:
        vectors: list[list[float]] = []
        size = self._settings.embedding_batch_size
        for offset in range(0, len(chunks), size):
            batch = [chunk.embedding_input for chunk in chunks[offset : offset + size]]
            vectors.extend(await self._embeddings.embed_batch(batch))
        if len(vectors) != len(chunks):
            raise EmbeddingError("INCOMPLETE_EMBEDDING_BATCH")
        return vectors

    async def _validation_context(
        self, work: ProcessingWork, embedded_count: int
    ) -> ValidationContext:
        async with self._sessions() as session, session.begin():
            await _context(session, work.tenant_id, work.item_id)
            release_valid = work.release_id is None or bool(
                await session.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM kb.release WHERE release_id=:id)"),
                    {"id": work.release_id},
                )
            )
            product_valid = work.product_node_id is None or bool(
                await session.scalar(
                    text("SELECT EXISTS(SELECT 1 FROM kb.product_node WHERE product_node_id=:id)"),
                    {"id": work.product_node_id},
                )
            )
        return ValidationContext(
            work.language_code,
            release_valid,
            product_valid,
            not _permission_reasons(work, self._settings),
            work.document_approval_status,
            work.canonical_url,
            work.copyright_notice,
            embedded_count,
        )

    async def _persist(
        self,
        work: ProcessingWork,
        processing_id: UUID,
        parser: DocumentParser,
        page_count: int | None,
        normalized: bytes,
        normalized_key: str,
        chunks: tuple[Chunk, ...],
        vectors: list[list[float]],
        validation: ValidationResult,
    ) -> None:
        async with self._sessions() as session, session.begin():
            await _context(session, work.tenant_id, work.item_id)
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk_id = uuid5(
                    NAMESPACE_URL,
                    f"helpdesk:{processing_id}:{chunk.sequence}:{chunk.content_hash}",
                )
                await session.execute(
                    text("""
                        INSERT INTO kb.document_chunk(
                          chunk_id,document_version_id,processing_version_id,tenant_id,
                          document_id,source_id,chunk_sequence,heading_path,chapter_title,
                          section_title,section_anchor,page_number,content_text,token_count,
                          content_hash,audience_code,security_classification,
                          embedding_input_hash)
                        VALUES (:chunk_id,:version_id,:processing_id,:tenant_id,:document_id,
                          :source_id,:sequence,:heading_path,:chapter,:section,:anchor,
                          :page_number,:content,:token_count,:content_hash,:audience,
                          :classification,:embedding_hash)
                    """),
                    {
                        "chunk_id": chunk_id,
                        "version_id": work.document_version_id,
                        "processing_id": processing_id,
                        "tenant_id": work.tenant_id,
                        "document_id": work.document_id,
                        "source_id": work.source.source_id,
                        "sequence": chunk.sequence,
                        "heading_path": " > ".join(chunk.heading_path) or None,
                        "chapter": chunk.heading_path[0] if chunk.heading_path else None,
                        "section": chunk.heading_path[-1] if chunk.heading_path else None,
                        "anchor": chunk.anchor,
                        "page_number": chunk.page_number,
                        "content": chunk.content,
                        "token_count": chunk.token_count,
                        "content_hash": chunk.content_hash,
                        "audience": work.audience_code,
                        "classification": work.security_classification,
                        "embedding_hash": chunk.embedding_input_hash,
                    },
                )
                await session.execute(
                    text("""
                        INSERT INTO kb.chunk_embedding_1536(
                          chunk_id,embedding_model_code,embedding,tenant_id,
                          processing_version_id)
                        VALUES (:chunk_id,:model_code,CAST(:embedding AS vector),
                          :tenant_id,:processing_id)
                    """),
                    {
                        "chunk_id": chunk_id,
                        "model_code": self._embeddings.model_code,
                        "embedding": _vector(vector),
                        "tenant_id": work.tenant_id,
                        "processing_id": processing_id,
                    },
                )
            evidence = {
                "failures": validation.failures,
                "warnings": validation.warnings,
                "metrics": validation.metrics,
            }
            await session.execute(
                text("""
                    UPDATE kb.document_processing_version
                    SET processing_status=:processing_status,
                      normalized_object_key=:normalized_key,
                      extracted_text_sha256=:normalized_sha,page_count=:page_count,
                      chunk_count=:chunk_count,embedded_chunk_count=:embedded_count,
                      validation_status=:validation_status,
                      validation_json=CAST(:validation AS jsonb),completed_at=now()
                    WHERE processing_version_id=:processing_id
                """),
                {
                    "processing_status": (
                        "FAILED" if validation.status == "FAILED" else "COMPLETED"
                    ),
                    "normalized_key": normalized_key,
                    "normalized_sha": hashlib.sha256(normalized).hexdigest(),
                    "page_count": page_count,
                    "chunk_count": len(chunks),
                    "embedded_count": len(vectors),
                    "validation_status": validation.status,
                    "validation": json.dumps(evidence),
                    "processing_id": processing_id,
                },
            )
            await session.execute(
                text("""
                    UPDATE kb.document_version SET normalized_file_uri=:normalized_key,
                      parser_name=:parser_name,parser_version=:parser_version,
                      extraction_status='COMPLETED',validation_status=:validation_status
                    WHERE document_version_id=:version_id
                """),
                {
                    "normalized_key": normalized_key,
                    "parser_name": parser.name,
                    "parser_version": parser.version,
                    "validation_status": validation.status,
                    "version_id": work.document_version_id,
                },
            )
            final_failure = validation.status == "FAILED"
            await session.execute(
                text("""
                    UPDATE kb.ingestion_run_item SET
                      item_status=CASE WHEN :failed THEN 'FAILED' ELSE 'EMBEDDED' END,
                      final_failure=:failed,error_code=CASE WHEN :failed
                        THEN 'VALIDATION_FAILED' END,error_message=CASE WHEN :failed
                        THEN 'Knowledge processing validation failed' END,
                      page_count=:page_count,chunk_count=:chunk_count,
                      warning_json=CAST(:warnings AS jsonb),locked_at=NULL,locked_by=NULL,
                      row_version=row_version+1
                    WHERE ingestion_run_item_id=:item_id AND tenant_id=:tenant_id
                """),
                {
                    "failed": final_failure,
                    "page_count": page_count,
                    "chunk_count": len(chunks),
                    "warnings": json.dumps(list(validation.warnings)),
                    "item_id": work.item_id,
                    "tenant_id": work.tenant_id,
                },
            )
            await _event(
                session,
                work,
                "KNOWLEDGE_PROCESSING_VALIDATED",
                "FINAL_FAILURE" if final_failure else "SUCCESS",
                {"processing_version_id": str(processing_id), "status": validation.status},
            )

    async def _mark_replayed(self, work: ProcessingWork, processing_id: UUID) -> None:
        async with self._sessions() as session, session.begin():
            await _context(session, work.tenant_id, work.item_id)
            await session.execute(
                text("""
                    UPDATE kb.ingestion_run_item SET item_status='EMBEDDED',locked_at=NULL,
                      locked_by=NULL,error_code=NULL,error_message=NULL,row_version=row_version+1
                    WHERE ingestion_run_item_id=:item_id AND tenant_id=:tenant_id
                """),
                {"item_id": work.item_id, "tenant_id": work.tenant_id},
            )
            await _event(
                session,
                work,
                "KNOWLEDGE_PROCESSING_REPLAYED",
                "SUCCESS",
                {"processing_version_id": str(processing_id)},
            )

    async def _failed(
        self,
        work: ProcessingWork,
        processing_id: UUID | None,
        error_code: str,
        *,
        final: bool,
    ) -> None:
        final = final or work.processing_attempt_count >= self._settings.worker_max_attempts
        delay = min(3600, 2 ** min(work.processing_attempt_count, 10))
        async with self._sessions() as session, session.begin():
            await _context(session, work.tenant_id, work.item_id)
            if processing_id is not None:
                await session.execute(
                    text("""
                        UPDATE kb.document_processing_version
                        SET processing_status='FAILED',validation_status='FAILED',
                          validation_json=jsonb_build_object('error_code',CAST(:error AS text)),
                          completed_at=CASE WHEN :final THEN now() END
                        WHERE processing_version_id=:processing_id
                    """),
                    {"processing_id": processing_id, "error": error_code[:100], "final": final},
                )
            if final:
                await session.execute(
                    text("""
                        UPDATE kb.document_version
                        SET extraction_status='FAILED',validation_status='FAILED'
                        WHERE document_version_id=:version_id
                    """),
                    {"version_id": work.document_version_id},
                )
            await session.execute(
                text("""
                    UPDATE kb.ingestion_run_item SET item_status='FAILED',final_failure=:final,
                      completed_at=CASE WHEN :final THEN now() END,
                      error_code=CAST(:error AS varchar),error_message=CASE WHEN :final
                        THEN 'Knowledge processing failed'
                        ELSE 'Knowledge processing scheduled for retry' END,
                      processing_next_attempt_at=CASE WHEN :final THEN processing_next_attempt_at
                        ELSE now()+make_interval(secs=>:delay) END,
                      locked_at=NULL,locked_by=NULL,row_version=row_version+1
                    WHERE ingestion_run_item_id=:item_id AND tenant_id=:tenant_id
                """),
                {
                    "final": final,
                    "error": error_code[:100],
                    "delay": delay,
                    "item_id": work.item_id,
                    "tenant_id": work.tenant_id,
                },
            )
            await _event(
                session,
                work,
                "KNOWLEDGE_PROCESSING_FAILED",
                "FINAL_FAILURE" if final else "RETRYABLE_FAILURE",
                {"error_code": error_code[:100]},
            )


def _provider(settings: WorkerSettings) -> EmbeddingProvider:
    if settings.embedding_provider_mode == "http":
        if settings.embedding_endpoint is None or settings.embedding_api_key is None:
            raise ValueError("HTTP embedding provider configuration is incomplete")
        return HttpEmbeddingProvider(
            settings.embedding_endpoint,
            settings.embedding_api_key.get_secret_value(),
            settings.embedding_model_code,
            settings.embedding_dimension,
            settings.embedding_timeout_seconds,
        )
    return DeterministicEmbeddingProvider(
        settings.embedding_model_code, settings.embedding_dimension
    )


def _permission_reasons(work: ProcessingWork, settings: WorkerSettings) -> list[str]:
    reasons: list[str] = []
    if work.source.row_version != work.source_row_version:
        reasons.append("SOURCE_VERSION_CHANGED")
    if work.manifest.row_version != work.manifest_row_version:
        reasons.append("MANIFEST_VERSION_CHANGED")
    external = work.manifest.acquisition_method != "MANUAL_UPLOAD"
    reasons.extend(
        acquisition_permission_reasons(work.source, work.authorization, settings, external=external)
    )
    expected = "APPROVED" if external else "NOT_REQUIRED"
    if work.manifest.acquisition_permission != expected:
        reasons.append("MANIFEST_ENTRY_NOT_APPROVED")
    return reasons


def _normalized_key(original_key: str, processing_id: UUID) -> str:
    prefix = original_key.split("/original/", 1)[0]
    return f"{prefix}/normalized/{processing_id}/extracted.txt"


def _vector(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.9f}" for value in vector) + "]"


async def _event(
    session: AsyncSession,
    work: ProcessingWork,
    event_code: str,
    outcome: str,
    detail: dict[str, object],
) -> None:
    await session.execute(
        text("""
            INSERT INTO kb.ingestion_event(
              tenant_id,ingestion_run_id,ingestion_run_item_id,event_code,outcome_code,
              detail_json,deduplication_key)
            VALUES (:tenant_id,:run_id,:item_id,:event_code,:outcome,
              CAST(:detail AS jsonb),:deduplication_key)
            ON CONFLICT (ingestion_run_item_id,deduplication_key) DO NOTHING
        """),
        {
            "tenant_id": work.tenant_id,
            "run_id": work.run_id,
            "item_id": work.item_id,
            "event_code": event_code,
            "outcome": outcome,
            "detail": json.dumps(detail),
            "deduplication_key": (
                f"processing-attempt-{work.processing_attempt_count}:{event_code}"
            ),
        },
    )
