"""Permission-gated, retry-safe knowledge document acquisition worker."""

import asyncio
import hashlib
import ipaddress
import json
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from apps.api.app.attachments.clamav import ClamAVScanner, MalwareScanner, ScannerError
from apps.api.app.attachments.storage import (
    ObjectTooLargeError,
    S3ObjectStorage,
    StorageError,
    WritableObjectStorage,
)
from apps.api.app.core.context import RequestContext
from apps.api.app.core.settings import Settings
from apps.api.app.db.transaction_context import apply_transaction_context
from apps.api.app.ingestion.models import ManifestEntry
from apps.api.app.ingestion.repository import IngestionRepository
from apps.api.app.knowledge.models import KnowledgeSource, SourceAuthorization
from apps.api.app.knowledge.repository import KnowledgeSourceRepository
from apps.api.app.knowledge.service import acquisition_permission_reasons
from apps.worker.worker.settings import WorkerSettings

logger = logging.getLogger(__name__)


class RetryableAcquisitionError(RuntimeError):
    """A dependency failure that may succeed on a later attempt."""


class PermanentAcquisitionError(RuntimeError):
    """Invalid or forbidden content that must not be retried."""


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    content: bytes
    content_type: str


class DocumentFetcher(Protocol):
    async def fetch(self, url: str, maximum_bytes: int) -> FetchedDocument: ...


class HttpDocumentFetcher:
    """Fetch exactly one approved public HTTPS URL without redirects."""

    def __init__(self, timeout_seconds: float) -> None:
        self._timeout = timeout_seconds

    async def fetch(self, url: str, maximum_bytes: int) -> FetchedDocument:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise PermanentAcquisitionError("URL_NOT_APPROVED")
        await _require_public_host(parsed.hostname, parsed.port or 443)
        try:
            async with (
                httpx.AsyncClient(
                    timeout=self._timeout, follow_redirects=False, trust_env=False
                ) as client,
                client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response,
            ):
                if 400 <= response.status_code < 500:
                    raise PermanentAcquisitionError("REMOTE_REQUEST_REJECTED")
                if response.status_code >= 500:
                    raise RetryableAcquisitionError("REMOTE_SERVER_UNAVAILABLE")
                declared = int(response.headers.get("content-length", "0") or "0")
                if declared > maximum_bytes:
                    raise PermanentAcquisitionError("DOCUMENT_TOO_LARGE")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > maximum_bytes:
                        raise PermanentAcquisitionError("DOCUMENT_TOO_LARGE")
                media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        except PermanentAcquisitionError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, ValueError) as error:
            raise RetryableAcquisitionError("REMOTE_FETCH_UNAVAILABLE") from error
        return FetchedDocument(bytes(content), media_type)


@dataclass(frozen=True, slots=True)
class ClaimedItem:
    item_id: UUID
    tenant_id: UUID


@dataclass(frozen=True, slots=True)
class AcquisitionWork:
    item_id: UUID
    run_id: UUID
    tenant_id: UUID
    attempt_count: int
    source_row_version: int
    manifest_row_version: int
    quarantine_key: str
    manifest: ManifestEntry
    source: KnowledgeSource
    authorization: SourceAuthorization | None


class AcquisitionWorker:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: WorkerSettings,
        storage: WritableObjectStorage | None = None,
        scanner: MalwareScanner | None = None,
        fetcher: DocumentFetcher | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._storage = storage or cast(
            "WritableObjectStorage", S3ObjectStorage(cast("Settings", settings))
        )
        self._scanner = scanner or ClamAVScanner(cast("Settings", settings))
        self._fetcher = fetcher or HttpDocumentFetcher(settings.acquisition_fetch_timeout_seconds)

    async def process_one(self) -> bool:
        claim = await self._claim()
        if claim is None:
            return False
        work: AcquisitionWork | None = None
        try:
            work = await self._load(claim)
            reasons = _permission_reasons(work, self._settings)
            if reasons:
                await self._blocked(work, reasons)
                return True
            content, provider_type = await self._acquire(work)
            detected = _validate_content(work, content, provider_type, self._settings)
            checksum = hashlib.sha256(content).hexdigest()
            if work.manifest.expected_sha256 and checksum != work.manifest.expected_sha256:
                raise PermanentAcquisitionError("CHECKSUM_MISMATCH")
            scan = await self._scanner.scan(content)
            if not scan.clean:
                await self._storage.reject(work.quarantine_key)
                await self._failed(
                    work,
                    "MALWARE_DETECTED",
                    final=True,
                    detected_type=detected,
                    scanner=(scan.engine, scan.version, scan.threat_name),
                )
                return True
            await self._complete(work, content, checksum, detected, scan.engine, scan.version)
        except PermanentAcquisitionError as error:
            if work is not None:
                await self._safe_reject(work.quarantine_key)
                await self._failed(work, str(error), final=True)
        except (
            RetryableAcquisitionError,
            StorageError,
            ObjectTooLargeError,
            ScannerError,
        ) as error:
            if work is not None:
                await self._failed(work, type(error).__name__, final=False)
        except Exception as error:
            logger.exception(
                "Knowledge acquisition failed",
                extra={"item_id": str(claim.item_id), "error_code": type(error).__name__},
            )
            if work is not None:
                await self._failed(work, "UNEXPECTED_ACQUISITION_ERROR", final=False)
        return True

    async def _claim(self) -> ClaimedItem | None:
        async with self._sessions() as session, session.begin():
            row = (
                await session.execute(
                    text("SELECT * FROM kb.claim_acquisition_item(:worker_id)"),
                    {"worker_id": self._settings.worker_id},
                )
            ).one_or_none()
            return ClaimedItem(*tuple(row)) if row is not None else None

    async def _load(self, claim: ClaimedItem) -> AcquisitionWork:
        async with self._sessions() as session, session.begin():
            await _context(session, claim.tenant_id, claim.item_id)
            row = (
                await session.execute(
                    text("""
                        SELECT ingestion_run_id,manifest_entry_id,attempt_count,
                          source_row_version,manifest_entry_row_version,quarantine_object_key
                        FROM kb.ingestion_run_item
                        WHERE tenant_id=:tenant_id AND ingestion_run_item_id=:item_id
                          AND item_status='ACQUIRING' AND locked_by=:worker_id
                    """),
                    {
                        "tenant_id": claim.tenant_id,
                        "item_id": claim.item_id,
                        "worker_id": self._settings.worker_id,
                    },
                )
            ).one_or_none()
            if row is None:
                raise PermanentAcquisitionError("CLAIM_LOST")
            manifest = await IngestionRepository(session).manifest(
                claim.tenant_id, row.manifest_entry_id
            )
            if manifest is None:
                raise PermanentAcquisitionError("MANIFEST_NOT_FOUND")
            sources = KnowledgeSourceRepository(session)
            source = await sources.get(claim.tenant_id, manifest.source_id)
            if source is None:
                raise PermanentAcquisitionError("SOURCE_NOT_FOUND")
            authorization = await sources.effective_authorization(claim.tenant_id, source)
            return AcquisitionWork(
                claim.item_id,
                row.ingestion_run_id,
                claim.tenant_id,
                row.attempt_count,
                row.source_row_version,
                row.manifest_entry_row_version,
                row.quarantine_object_key,
                manifest,
                source,
                authorization,
            )

    async def _acquire(self, work: AcquisitionWork) -> tuple[bytes, str]:
        if work.manifest.acquisition_method == "MANUAL_UPLOAD":
            content = await self._storage.read(
                work.quarantine_key, self._settings.knowledge_document_max_bytes
            )
            return content, work.manifest.declared_content_type or ""
        url = work.manifest.pdf_url or work.manifest.html_url
        if not url:
            raise PermanentAcquisitionError("ACQUISITION_URL_MISSING")
        fetched = await self._fetcher.fetch(url, self._settings.knowledge_document_max_bytes)
        await self._storage.write(work.quarantine_key, fetched.content, fetched.content_type)
        return fetched.content, fetched.content_type

    async def _complete(
        self,
        work: AcquisitionWork,
        content: bytes,
        checksum: str,
        detected_type: str,
        scanner_engine: str,
        scanner_version: str,
    ) -> None:
        filename = work.manifest.original_filename or "document.bin"
        document_id = uuid5(
            NAMESPACE_URL, f"helpdesk:{work.source.source_id}:{work.manifest.manifest_key}"
        )
        version_id = uuid5(NAMESPACE_URL, f"helpdesk:{document_id}:{checksum}")
        scope = str(work.source.tenant_id or "global")
        original_key = (
            f"knowledge/{scope}/{work.source.source_code}/{document_id}/{version_id}/"
            f"original/{filename}"
        )
        duplicate = False
        async with self._sessions() as session, session.begin():
            await _context(session, work.tenant_id, work.item_id)
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": f"{work.source.source_id}:{work.manifest.manifest_key}"},
            )
            existing = (
                await session.execute(
                    text("""
                        SELECT document_id FROM kb.document
                        WHERE source_id=:source_id AND external_document_key=:manifest_key
                    """),
                    {
                        "source_id": work.source.source_id,
                        "manifest_key": work.manifest.manifest_key,
                    },
                )
            ).one_or_none()
            if existing is not None:
                document_id = existing.document_id
                duplicate = bool(
                    await session.scalar(
                        text("""
                            SELECT EXISTS(SELECT 1 FROM kb.document_version
                              WHERE document_id=:document_id AND sha256_checksum=:checksum)
                        """),
                        {"document_id": document_id, "checksum": checksum},
                    )
                )
            if duplicate:
                await self._storage.reject(work.quarantine_key)
                await _finish_item(
                    session,
                    work,
                    "SKIPPED_UNCHANGED",
                    "DUPLICATE_CHECKSUM",
                    checksum,
                    detected_type,
                    len(content),
                    scanner_engine,
                    scanner_version,
                    document_id,
                    None,
                )
                await _event(
                    session,
                    work,
                    "ACQUISITION_SKIPPED_UNCHANGED",
                    "SUCCESS",
                    {"checksum": checksum},
                )
                await _refresh_run(session, work.run_id)
                return
            version_id = uuid5(NAMESPACE_URL, f"helpdesk:{document_id}:{checksum}")
            original_key = (
                f"knowledge/{scope}/{work.source.source_code}/{document_id}/{version_id}/"
                f"original/{filename}"
            )
            await self._storage.copy(work.quarantine_key, original_key, detected_type)
            if existing is None:
                await session.execute(
                    text("""
                        INSERT INTO kb.document(
                          document_id,tenant_id,source_id,product_node_id,release_id,
                          external_document_key,document_title,document_type,audience_code,
                          canonical_url,language_code,owner_group_id,security_classification,
                          approval_status)
                        VALUES (:document_id,:resource_tenant_id,:source_id,:product_node_id,
                          :release_id,:manifest_key,:title,:document_type,:audience_code,
                          :canonical_url,:language_code,:owner_group_id,:classification,
                          'DRAFT')
                    """),
                    {
                        "document_id": document_id,
                        "resource_tenant_id": work.source.tenant_id,
                        "source_id": work.source.source_id,
                        "product_node_id": work.source.module_node_id
                        or work.source.product_node_id,
                        "release_id": work.source.release_id,
                        "manifest_key": work.manifest.manifest_key,
                        "title": work.manifest.document_title,
                        "document_type": work.manifest.document_type,
                        "audience_code": work.manifest.audience_code,
                        "canonical_url": work.manifest.canonical_url,
                        "language_code": work.source.language_code,
                        "owner_group_id": work.source.owner_group_id,
                        "classification": work.manifest.security_classification,
                    },
                )
            next_version = int(
                await session.scalar(
                    text(
                        "SELECT coalesce(max(version_number),0)+1 FROM kb.document_version "
                        "WHERE document_id=:document_id"
                    ),
                    {"document_id": document_id},
                )
                or 1
            )
            await session.execute(
                text("""
                    INSERT INTO kb.document_version(
                      document_version_id,document_id,version_number,source_version_label,
                      original_file_uri,content_type,file_size_bytes,sha256_checksum,
                      source_last_modified_at,acquired_at,acquisition_run_id,copyright_notice,
                      extraction_status,validation_status,current_version_flag)
                    VALUES (:version_id,:document_id,:version_number,NULL,:original_key,
                      :content_type,:file_size,:checksum,:source_modified,now(),:run_id,
                      :copyright_notice,'PENDING','PENDING',false)
                """),
                {
                    "version_id": version_id,
                    "document_id": document_id,
                    "version_number": next_version,
                    "original_key": original_key,
                    "content_type": detected_type,
                    "file_size": len(content),
                    "checksum": checksum,
                    "source_modified": work.manifest.source_last_modified_at,
                    "run_id": work.run_id,
                    "copyright_notice": work.manifest.copyright_notice,
                },
            )
            await _finish_item(
                session,
                work,
                "ACQUIRED",
                None,
                checksum,
                detected_type,
                len(content),
                scanner_engine,
                scanner_version,
                document_id,
                version_id,
                original_key,
            )
            await _event(
                session,
                work,
                "DOCUMENT_ACQUIRED",
                "SUCCESS",
                {"checksum": checksum, "document_version_id": str(version_id)},
            )
            await _refresh_run(session, work.run_id)
        await self._safe_reject(work.quarantine_key)

    async def _blocked(self, work: AcquisitionWork, reasons: list[str]) -> None:
        async with self._sessions() as session, session.begin():
            await _context(session, work.tenant_id, work.item_id)
            await session.execute(
                text("""
                    UPDATE kb.ingestion_run_item SET item_status='BLOCKED_PERMISSION',
                      final_failure=true,completed_at=now(),error_code='PERMISSION_DENIED',
                      error_message='Acquisition permission denied',locked_at=NULL,locked_by=NULL,
                      row_version=row_version+1
                    WHERE ingestion_run_item_id=:item_id AND tenant_id=:tenant_id
                """),
                {"item_id": work.item_id, "tenant_id": work.tenant_id},
            )
            await _event(session, work, "ACQUISITION_BLOCKED", "BLOCKED", {"reasons": reasons})
            await _refresh_run(session, work.run_id)

    async def _failed(
        self,
        work: AcquisitionWork,
        error_code: str,
        *,
        final: bool,
        detected_type: str | None = None,
        scanner: tuple[str, str, str | None] | None = None,
    ) -> None:
        final = final or work.attempt_count >= self._settings.worker_max_attempts
        delay = min(3600, 2 ** min(work.attempt_count, 10))
        async with self._sessions() as session, session.begin():
            await _context(session, work.tenant_id, work.item_id)
            await session.execute(
                text("""
                    UPDATE kb.ingestion_run_item SET item_status='FAILED',final_failure=:final,
                      completed_at=CASE WHEN :final THEN now() END,
                      error_code=CAST(:error_code AS varchar),
                      error_message=CASE WHEN :final THEN 'Document acquisition failed'
                        ELSE 'Document acquisition scheduled for retry' END,
                      detected_content_type=coalesce(
                        CAST(:detected_type AS varchar),detected_content_type),
                      malware_scan_status=CASE
                        WHEN CAST(:error_code AS varchar)='MALWARE_DETECTED' THEN 'INFECTED'
                        WHEN CAST(:scanner_engine AS varchar) IS NOT NULL THEN 'CLEAN'
                        ELSE 'ERROR' END,
                      malware_scanned_at=CASE
                        WHEN CAST(:scanner_engine AS varchar) IS NOT NULL THEN now()
                        ELSE malware_scanned_at END,
                      scanner_engine=coalesce(CAST(:scanner_engine AS varchar),scanner_engine),
                      scanner_version=coalesce(CAST(:scanner_version AS varchar),scanner_version),
                      threat_name=coalesce(CAST(:threat_name AS varchar),threat_name),
                      next_attempt_at=CASE WHEN :final THEN next_attempt_at
                        ELSE now()+make_interval(secs => :delay) END,
                      locked_at=NULL,locked_by=NULL,row_version=row_version+1
                    WHERE ingestion_run_item_id=:item_id AND tenant_id=:tenant_id
                """),
                {
                    "item_id": work.item_id,
                    "tenant_id": work.tenant_id,
                    "final": final,
                    "error_code": error_code[:100],
                    "detected_type": detected_type,
                    "scanner_engine": scanner[0] if scanner else None,
                    "scanner_version": scanner[1] if scanner else None,
                    "threat_name": scanner[2] if scanner else None,
                    "delay": delay,
                },
            )
            outcome = "FINAL_FAILURE" if final else "RETRYABLE_FAILURE"
            await _event(
                session, work, "ACQUISITION_FAILED", outcome, {"error_code": error_code[:100]}
            )
            await _refresh_run(session, work.run_id)

    async def _safe_reject(self, key: str) -> None:
        try:
            await self._storage.reject(key)
        except StorageError:
            logger.warning(
                "Quarantine cleanup failed",
                extra={"object_key_hash": hashlib.sha256(key.encode()).hexdigest()},
            )


async def _context(session: AsyncSession, tenant_id: UUID, item_id: UUID) -> None:
    await apply_transaction_context(
        session,
        RequestContext(
            tenant_id=tenant_id,
            user_id=None,
            external_subject=None,
            roles=frozenset(),
            support_group_ids=frozenset(),
            business_unit_id=None,
            correlation_id=str(item_id),
            request_id=f"acquisition-worker:{item_id}",
        ),
        rls_enabled=True,
    )


def _permission_reasons(work: AcquisitionWork, settings: WorkerSettings) -> list[str]:
    if work.source.row_version != work.source_row_version:
        return ["SOURCE_VERSION_CHANGED"]
    if work.manifest.row_version != work.manifest_row_version:
        return ["MANIFEST_VERSION_CHANGED"]
    external = work.manifest.acquisition_method != "MANUAL_UPLOAD"
    reasons = acquisition_permission_reasons(
        work.source, work.authorization, settings, external=external
    )
    if not work.manifest.enabled_flag:
        reasons.append("MANIFEST_ENTRY_DISABLED")
    expected_permission = "APPROVED" if external else "NOT_REQUIRED"
    if work.manifest.acquisition_permission != expected_permission:
        reasons.append("MANIFEST_ENTRY_NOT_APPROVED")
    if work.manifest.acquisition_method != work.source.acquisition_method:
        reasons.append("MANIFEST_METHOD_MISMATCH")
    if external and not work.manifest.permission_reference:
        reasons.append("MANIFEST_PERMISSION_REFERENCE_MISSING")
    return reasons


def _validate_content(
    work: AcquisitionWork,
    content: bytes,
    provider_type: str,
    settings: WorkerSettings,
) -> str:
    if not content:
        raise PermanentAcquisitionError("EMPTY_DOCUMENT")
    if len(content) > settings.knowledge_document_max_bytes:
        raise PermanentAcquisitionError("DOCUMENT_TOO_LARGE")
    if work.manifest.declared_size_bytes and len(content) != work.manifest.declared_size_bytes:
        raise PermanentAcquisitionError("DECLARED_SIZE_MISMATCH")
    filename = work.manifest.original_filename or ""
    detected = _detect_mime(content, filename)
    declared = (work.manifest.declared_content_type or "").lower()
    if provider_type and provider_type.lower() != declared:
        raise PermanentAcquisitionError("PROVIDER_CONTENT_TYPE_MISMATCH")
    if detected != declared:
        raise PermanentAcquisitionError("DETECTED_CONTENT_TYPE_MISMATCH")
    return detected


def _detect_mime(content: bytes, filename: str) -> str:
    extension = Path(filename).suffix.lower()
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if extension == ".docx" and content.startswith(b"PK\x03\x04"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if b"\x00" in content:
        return "application/octet-stream"
    try:
        text_content = content.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    stripped = text_content.lstrip().lower()
    if extension in {".html", ".htm"} and stripped.startswith(("<!doctype html", "<html")):
        return "text/html"
    if extension == ".json":
        try:
            json.loads(text_content)
            return "application/json"
        except json.JSONDecodeError:
            return "application/octet-stream"
    if extension == ".csv":
        return "text/csv"
    if extension == ".md":
        return "text/markdown"
    return "text/plain"


async def _require_public_host(hostname: str, port: int) -> None:
    try:
        literal = ipaddress.ip_address(hostname)
        addresses = [literal]
    except ValueError:
        try:
            records = await asyncio.get_running_loop().getaddrinfo(
                hostname, port, type=socket.SOCK_STREAM
            )
        except OSError as error:
            raise RetryableAcquisitionError("DNS_RESOLUTION_FAILED") from error
        addresses = [ipaddress.ip_address(record[4][0]) for record in records]
    if not addresses or any(not address.is_global for address in addresses):
        raise PermanentAcquisitionError("NON_PUBLIC_ACQUISITION_HOST")


async def _finish_item(
    session: AsyncSession,
    work: AcquisitionWork,
    status: str,
    error_code: str | None,
    checksum: str,
    detected_type: str,
    file_size: int,
    scanner_engine: str,
    scanner_version: str,
    document_id: UUID,
    version_id: UUID | None,
    original_key: str | None = None,
) -> None:
    await session.execute(
        text("""
            UPDATE kb.ingestion_run_item SET item_status=:status,document_id=:document_id,
              document_version_id=:version_id,completed_at=now(),downloaded_uri=:original_key,
              observed_sha256=:checksum,detected_content_type=:detected_type,
              file_size_bytes=:file_size,malware_scan_status='CLEAN',malware_scanned_at=now(),
              scanner_engine=:scanner_engine,scanner_version=:scanner_version,threat_name=NULL,
              error_code=:error_code,error_message=NULL,final_failure=false,
              locked_at=NULL,locked_by=NULL,row_version=row_version+1
            WHERE ingestion_run_item_id=:item_id AND tenant_id=:tenant_id
              AND item_status='ACQUIRING'
        """),
        {
            "status": status,
            "document_id": document_id,
            "version_id": version_id,
            "original_key": original_key,
            "checksum": checksum,
            "detected_type": detected_type,
            "file_size": file_size,
            "scanner_engine": scanner_engine,
            "scanner_version": scanner_version,
            "error_code": error_code,
            "item_id": work.item_id,
            "tenant_id": work.tenant_id,
        },
    )


async def _event(
    session: AsyncSession,
    work: AcquisitionWork,
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
            "deduplication_key": f"attempt-{work.attempt_count}:{event_code}",
        },
    )


async def _refresh_run(session: AsyncSession, run_id: UUID) -> None:
    await session.execute(
        text("""
            WITH totals AS (
              SELECT count(*) FILTER (WHERE item_status IN ('ACQUIRED','SKIPPED_UNCHANGED'))
                  AS completed,
                count(*) FILTER (WHERE item_status IN ('BLOCKED_PERMISSION','FAILED')
                  AND final_failure) AS failed,
                count(*) FILTER (WHERE item_status NOT IN (
                  'ACQUIRED','SKIPPED_UNCHANGED','BLOCKED_PERMISSION','FAILED'
                ) OR (item_status='FAILED' AND NOT final_failure)) AS pending
              FROM kb.ingestion_run_item WHERE ingestion_run_id=:run_id
            )
            UPDATE kb.ingestion_run SET completed_items=totals.completed,
              failed_items=totals.failed,
              run_status=CASE WHEN totals.pending>0 THEN 'RUNNING'
                WHEN totals.failed=0 THEN 'COMPLETED'
                WHEN totals.completed=0 THEN 'FAILED' ELSE 'COMPLETED_WITH_ERRORS' END,
              started_at=coalesce(started_at,now()),
              completed_at=CASE WHEN totals.pending=0 THEN now() ELSE NULL END,
              row_version=row_version+1
            FROM totals WHERE ingestion_run_id=:run_id
        """),
        {"run_id": run_id},
    )
