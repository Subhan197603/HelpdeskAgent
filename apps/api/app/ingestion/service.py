"""Authorized manifest and acquisition-run orchestration."""

import hashlib
import ipaddress
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from apps.api.app.attachments.storage import ObjectStorage, StorageError
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConcurrencyError,
    ConflictError,
    ExternalDependencyError,
    InvalidTransitionError,
    NotFoundError,
    UnsupportedFileError,
    ValidationError,
)
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission
from apps.api.app.ingestion.models import IngestionRunItem, ManifestEntry
from apps.api.app.ingestion.repository import IngestionRepository
from apps.api.app.ingestion.schemas import (
    AcquisitionRunCommand,
    ChangeClassification,
    ChangeReportPageResponse,
    ChangeReportSummary,
    ManifestApprovalCommand,
    ManifestEntryInput,
    ManifestEntryResponse,
    ManifestImportCommand,
    ManifestImportResponse,
    ManualUploadCommand,
    ManualUploadResponse,
    RefreshRunCommand,
    RunItemResponse,
    RunResponse,
    SourceChangeReportResponse,
    UploadCompleteResponse,
)
from apps.api.app.knowledge.models import IdempotencyClaim, KnowledgeSource
from apps.api.app.knowledge.repository import KnowledgeSourceRepository
from apps.api.app.knowledge.service import acquisition_permission_reasons

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]
_ALLOWED_CONTENT: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".html": frozenset({"text/html"}),
    ".htm": frozenset({"text/html"}),
    ".txt": frozenset({"text/plain"}),
    ".md": frozenset({"text/markdown", "text/plain"}),
    ".csv": frozenset({"text/csv", "text/plain"}),
    ".json": frozenset({"application/json"}),
    ".docx": frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
}


class IngestionService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        storage: ObjectStorage,
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._storage = storage
        self._settings = settings

    async def import_manifest(
        self, context: RequestContext, command: ManifestImportCommand, idempotency_key: str
    ) -> ManifestImportResponse:
        self._require(context, Permission.KNOWLEDGE_MANIFEST_IMPORT)
        tenant_id, user_id = _identity(context)
        request_hash = _hash("manifest-import", command.model_dump(mode="json"))
        async with self._factory(context) as uow:
            repo = IngestionRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_MANIFEST_IMPORT"
            )
            _validate_claim(claim, user_id, request_hash)
            if claim.processing_status == "COMPLETED":
                rows = await self._manifest_command_rows(repo, tenant_id, command.entries)
                await uow.commit()
                return ManifestImportResponse(
                    items=[_manifest_response(row) for row in rows], replayed=True
                )
            result_ids: list[UUID] = []
            for entry in command.entries:
                source = await _source(uow, tenant_id, entry.source_id)
                if source.tenant_id is None:
                    self._require(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
                normalized_url = _validate_external_entry(source, entry)
                entry = entry.model_copy(update={"acquisition_url": normalized_url})
                result_ids.append(
                    await repo.import_entry(
                        source.tenant_id,
                        user_id,
                        entry,
                        context.correlation_id,
                        context.request_id,
                    )
                )
            await repo.complete_idempotency(
                claim.record_id, "KNOWLEDGE_MANIFEST_IMPORT", result_ids[0], 200
            )
            rows = await repo.manifests(tenant_id, result_ids)
            await uow.commit()
        return ManifestImportResponse(items=[_manifest_response(row) for row in rows])

    async def decide_manifest(
        self,
        context: RequestContext,
        entry_id: UUID,
        command: ManifestApprovalCommand,
        idempotency_key: str,
    ) -> tuple[ManifestEntryResponse, bool]:
        self._require(context, Permission.KNOWLEDGE_MANIFEST_APPROVE)
        tenant_id, user_id = _identity(context)
        request_hash = _hash(
            "manifest-decision", {"entry_id": str(entry_id), **command.model_dump(mode="json")}
        )
        async with self._factory(context) as uow:
            repo = IngestionRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_MANIFEST_DECISION"
            )
            _validate_claim(claim, user_id, request_hash)
            entry = await repo.manifest(tenant_id, entry_id, lock=True)
            if entry is None:
                raise NotFoundError("Manifest entry was not found.")
            source = await _source(uow, tenant_id, entry.source_id)
            if source.tenant_id is None:
                self._require(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
            if source.owner_user_id == user_id or (
                source.owner_group_id is not None
                and source.owner_group_id in context.support_group_ids
            ):
                raise AuthorizationError("A source owner cannot approve its manifest entry.")
            if claim.processing_status == "COMPLETED":
                await uow.commit()
                return _manifest_response(entry), True
            source_reasons = acquisition_permission_reasons(
                source, None, self._settings, external=False
            )
            if source_reasons:
                raise ConflictError("Manifest approval requires an active, approved source.")
            if not await repo.decide_manifest(
                tenant_id,
                entry_id,
                user_id,
                command.decision,
                command.permission_reference.strip(),
                command.expected_version,
                context.correlation_id,
                context.request_id,
            ):
                raise ConcurrencyError("Manifest entry row version is stale.")
            await repo.complete_idempotency(
                claim.record_id, "KNOWLEDGE_MANIFEST_ENTRY", entry_id, 200
            )
            updated = await repo.manifest(tenant_id, entry_id)
            if updated is None:
                raise ConflictError("Manifest decision result is unavailable.")
            await uow.commit()
        return _manifest_response(updated), False

    async def create_run(
        self, context: RequestContext, command: AcquisitionRunCommand, idempotency_key: str
    ) -> RunResponse:
        self._require(context, Permission.KNOWLEDGE_INGESTION_RUN_CREATE)
        tenant_id, user_id = _identity(context)
        request_hash = _hash("acquisition-run", command.model_dump(mode="json"))
        async with self._factory(context) as uow:
            repo = IngestionRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_ACQUISITION_RUN"
            )
            _validate_claim(claim, user_id, request_hash)
            if claim.processing_status == "COMPLETED":
                if claim.result_resource_id is None:
                    raise ConflictError("Acquisition run result is unavailable.")
                response = await _run_response(
                    repo, tenant_id, UUID(claim.result_resource_id), True
                )
                await uow.commit()
                return response
            entries = await repo.manifests(tenant_id, command.manifest_entry_ids)
            if len(entries) != len(command.manifest_entry_ids):
                raise NotFoundError("One or more manifest entries were not found.")
            snapshots: list[tuple[ManifestEntry, int, str | None]] = []
            for entry in entries:
                source = await _source(uow, tenant_id, entry.source_id)
                if source.tenant_id is None:
                    self._require(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
                authorization = await KnowledgeSourceRepository(
                    uow.session
                ).effective_authorization(tenant_id, source)
                reasons = _entry_permission_reasons(entry, source, authorization, self._settings)
                if reasons:
                    raise AuthorizationError("Acquisition permission denied: " + ",".join(reasons))
                snapshots.append((entry, source.row_version, entry.permission_reference))
            run_id, _ = await repo.create_run(
                tenant_id, user_id, snapshots, context.correlation_id, context.request_id
            )
            await repo.complete_idempotency(claim.record_id, "INGESTION_RUN", run_id, 201)
            response = await _run_response(repo, tenant_id, run_id, False)
            await uow.commit()
        return response

    async def create_refresh_run(
        self,
        context: RequestContext,
        source_id: UUID,
        command: RefreshRunCommand,
        idempotency_key: str,
    ) -> RunResponse:
        self._require(context, Permission.KNOWLEDGE_INGESTION_RUN_CREATE)
        tenant_id, user_id = _identity(context)
        request_hash = _hash(
            "refresh-run", {"source_id": str(source_id), **command.model_dump(mode="json")}
        )
        async with self._factory(context) as uow:
            repo = IngestionRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_REFRESH_RUN"
            )
            _validate_claim(claim, user_id, request_hash)
            if claim.processing_status == "COMPLETED":
                if claim.result_resource_id is None:
                    raise ConflictError("Refresh run result is unavailable.")
                response = await _run_response(
                    repo, tenant_id, UUID(claim.result_resource_id), True
                )
                await uow.commit()
                return response
            sources = KnowledgeSourceRepository(uow.session)
            source = await sources.get(tenant_id, source_id, lock=True)
            if source is None:
                raise NotFoundError("Knowledge source was not found.")
            if source.tenant_id is None:
                self._require(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
            if source.source_status == "RETIRED":
                raise InvalidTransitionError("A retired source cannot be refreshed.")
            if source.refresh_state == "REFRESHING":
                raise InvalidTransitionError("A refresh run is already in progress.")
            entries = await repo.approved_entries_for_source(tenant_id, source_id)
            if not entries:
                raise ConflictError("The source has no approved, enabled manifest entries.")
            authorization = await sources.effective_authorization(tenant_id, source)
            snapshots: list[tuple[ManifestEntry, int, str | None]] = []
            for entry in entries:
                reasons = _entry_permission_reasons(entry, source, authorization, self._settings)
                if reasons:
                    raise AuthorizationError(
                        "Refresh acquisition permission denied: " + ",".join(reasons)
                    )
                snapshots.append((entry, source.row_version, entry.permission_reference))
            if not await sources.start_refresh(
                tenant_id,
                source_id,
                user_id,
                previous_state=source.refresh_state,
                expected_version=command.expected_version,
                correlation_id=context.correlation_id,
                request_id=context.request_id,
            ):
                raise ConcurrencyError("Knowledge source row version is stale.")
            run_id, _ = await repo.create_run(
                tenant_id,
                user_id,
                snapshots,
                context.correlation_id,
                context.request_id,
                run_type="REFRESH",
            )
            await repo.complete_idempotency(claim.record_id, "INGESTION_RUN", run_id, 201)
            response = await _run_response(repo, tenant_id, run_id, False)
            await uow.commit()
        return response

    async def change_report(
        self, context: RequestContext, source_id: UUID
    ) -> SourceChangeReportResponse:
        self._require(context, Permission.KNOWLEDGE_SOURCE_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            await _source(uow, tenant_id, source_id)
            repo = IngestionRepository(uow.session)
            run = await repo.latest_refresh_run(tenant_id, source_id)
            pages = (
                await repo.change_report_pages(tenant_id, run.ingestion_run_id)
                if run is not None
                else []
            )
        summary = ChangeReportSummary(
            unchanged=sum(1 for page in pages if page.change_classification == "UNCHANGED"),
            changed=sum(1 for page in pages if page.change_classification == "CHANGED"),
            removed=sum(1 for page in pages if page.change_classification == "REMOVED"),
            redirected=sum(1 for page in pages if page.change_classification == "REDIRECTED"),
            failed=sum(1 for page in pages if page.final_failure),
        )
        return SourceChangeReportResponse(
            source_id=source_id,
            run_id=run.ingestion_run_id if run is not None else None,
            run_status=run.run_status if run is not None else None,
            requested_by=run.requested_by if run is not None else None,
            created_at=run.created_at if run is not None else None,
            completed_at=run.completed_at if run is not None else None,
            total_items=run.total_items if run is not None else 0,
            summary=summary,
            pages=[
                ChangeReportPageResponse(
                    item_id=page.ingestion_run_item_id,
                    manifest_key=page.manifest_key,
                    document_title=page.document_title,
                    status=page.item_status,
                    classification=cast("ChangeClassification | None", page.change_classification),
                    previous_sha256=page.previous_sha256,
                    observed_sha256=page.observed_sha256,
                    redirect_target_url=page.redirect_target_url,
                    observed_http_status=page.observed_http_status,
                    error_code=page.error_code,
                    final_failure=page.final_failure,
                    completed_at=page.completed_at,
                )
                for page in pages
            ],
        )

    async def authorize_manual_upload(
        self, context: RequestContext, command: ManualUploadCommand, idempotency_key: str
    ) -> ManualUploadResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_UPLOAD)
        _require_content(
            command.filename, command.content_type, command.file_size_bytes, self._settings
        )
        self._require_storage()
        tenant_id, user_id = _identity(context)
        request_hash = _hash("manual-upload", command.model_dump(mode="json"))
        async with self._factory(context) as uow:
            repo = IngestionRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id, user_id, idempotency_key, request_hash, "KNOWLEDGE_MANUAL_UPLOAD"
            )
            _validate_claim(claim, user_id, request_hash)
            if claim.processing_status == "COMPLETED":
                if claim.result_resource_id is None:
                    raise ConflictError("Manual upload result is unavailable.")
                run_id = UUID(claim.result_resource_id)
                items = await repo.run_items(tenant_id, run_id)
                if len(items) != 1:
                    raise ConflictError("Manual upload result is unavailable.")
                response = await self._upload_response(repo, tenant_id, run_id, items[0], True)
                await uow.commit()
                return response
            source = await _source(uow, tenant_id, command.source_id)
            if source.tenant_id is None:
                self._require(context, Permission.KNOWLEDGE_SOURCE_MANAGE_GLOBAL)
            if source.acquisition_method != "MANUAL_UPLOAD":
                raise ValidationError("Source is not configured for manual upload.")
            reasons = acquisition_permission_reasons(source, None, self._settings, external=False)
            if reasons:
                raise AuthorizationError(
                    "Manual acquisition permission denied: " + ",".join(reasons)
                )
            entry = await repo.upsert_manual_manifest(source.tenant_id, command)
            run_id, item_ids = await repo.create_run(
                tenant_id,
                user_id,
                [(entry, source.row_version, source.permission_reference)],
                context.correlation_id,
                context.request_id,
                awaiting_upload=True,
            )
            await repo.complete_idempotency(claim.record_id, "INGESTION_RUN", run_id, 201)
            items = await repo.run_items(tenant_id, run_id)
            if len(items) != 1 or items[0].ingestion_run_item_id != item_ids[0]:
                raise ConflictError("Manual upload result is unavailable.")
            response = await self._upload_response(repo, tenant_id, run_id, items[0], False)
            await uow.commit()
        return response

    async def complete_manual_upload(
        self, context: RequestContext, item_id: UUID, idempotency_key: str
    ) -> UploadCompleteResponse:
        self._require(context, Permission.KNOWLEDGE_DOCUMENT_UPLOAD)
        tenant_id, user_id = _identity(context)
        request_hash = _hash("manual-upload-complete", {"item_id": str(item_id)})
        async with self._factory(context) as uow:
            repo = IngestionRepository(uow.session)
            claim = await repo.claim_idempotency(
                tenant_id,
                user_id,
                idempotency_key,
                request_hash,
                "KNOWLEDGE_MANUAL_UPLOAD_COMPLETE",
            )
            _validate_claim(claim, user_id, request_hash)
            result = await repo.complete_upload(tenant_id, item_id)
            if result is None:
                raise NotFoundError("Manual upload item was not found.")
            run_id, lifecycle_replay = result
            replayed = claim.processing_status == "COMPLETED" or lifecycle_replay
            if claim.processing_status != "COMPLETED":
                await repo.complete_idempotency(claim.record_id, "INGESTION_RUN_ITEM", item_id, 200)
            await uow.commit()
        return UploadCompleteResponse(
            run_id=run_id, item_id=item_id, status="QUEUED", replayed=replayed
        )

    async def get_run(self, context: RequestContext, run_id: UUID) -> RunResponse:
        self._require(context, Permission.KNOWLEDGE_SOURCE_READ_ADMIN)
        tenant_id, _ = _identity(context)
        async with self._factory(context) as uow:
            return await _run_response(IngestionRepository(uow.session), tenant_id, run_id, False)

    async def _manifest_command_rows(
        self, repo: IngestionRepository, tenant_id: UUID, entries: list[ManifestEntryInput]
    ) -> list[ManifestEntry]:
        rows: list[ManifestEntry] = []
        for command in entries:
            row = await repo.manifest_by_key(tenant_id, command.source_id, command.manifest_key)
            if row is None:
                raise ConflictError("Idempotent manifest result is unavailable.")
            rows.append(row)
        return rows

    async def _upload_response(
        self,
        repo: IngestionRepository,
        tenant_id: UUID,
        run_id: UUID,
        item: IngestionRunItem,
        replayed: bool,
    ) -> ManualUploadResponse:
        key = await repo.item_quarantine_key(tenant_id, item.ingestion_run_item_id)
        if key is None or item.declared_content_type is None or item.file_size_bytes is None:
            raise ConflictError("Manual upload storage authorization is unavailable.")
        entry = await repo.manifest(tenant_id, item.manifest_entry_id)
        if entry is None or entry.expected_sha256 is None:
            raise ConflictError("Manual upload manifest is unavailable.")
        try:
            url = await self._storage.create_upload_url(
                key,
                item.declared_content_type,
                item.file_size_bytes,
                entry.expected_sha256,
                self._settings.knowledge_upload_url_seconds,
            )
        except StorageError as error:
            raise ExternalDependencyError("Object storage is unavailable.") from error
        headers = {
            "Content-Type": item.declared_content_type,
            "Content-Length": str(item.file_size_bytes),
            "x-amz-acl": "private",
            "x-amz-meta-expected-size": str(item.file_size_bytes),
            "x-amz-meta-expected-sha256": entry.expected_sha256,
        }
        if self._settings.object_storage_server_side_encryption:
            headers["x-amz-server-side-encryption"] = (
                self._settings.object_storage_server_side_encryption
            )
        if self._settings.object_storage_sse_key_id:
            headers["x-amz-server-side-encryption-aws-kms-key-id"] = (
                self._settings.object_storage_sse_key_id.get_secret_value()
            )
        return ManualUploadResponse(
            run_id=run_id,
            item_id=item.ingestion_run_item_id,
            manifest_entry_id=item.manifest_entry_id,
            upload_url=url,
            upload_headers=headers,
            quarantine_object_key=key,
            expires_at=datetime.now(UTC)
            + timedelta(seconds=self._settings.knowledge_upload_url_seconds),
            replayed=replayed,
        )

    def _require(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError()

    def _require_storage(self) -> None:
        if not self._settings.object_storage_enabled:
            raise ExternalDependencyError("Knowledge object storage is disabled.")


async def _source(uow: SqlAlchemyUnitOfWork, tenant_id: UUID, source_id: UUID) -> KnowledgeSource:
    source = await KnowledgeSourceRepository(uow.session).get(tenant_id, source_id)
    if source is None:
        raise NotFoundError("Knowledge source was not found.")
    return source


def _validate_external_entry(source: KnowledgeSource, entry: ManifestEntryInput) -> str:
    if source.acquisition_method != entry.acquisition_method:
        raise ValidationError("Manifest acquisition method must match the source.")
    acquisition_url = _safe_https_url(entry.acquisition_url)
    source_url = urlsplit(source.canonical_location)
    acquired = urlsplit(acquisition_url)
    if source_url.scheme != "https" or source_url.hostname != acquired.hostname:
        raise ValidationError("Manifest URL must use the approved source host.")
    _require_content(
        entry.original_filename, entry.declared_content_type, entry.declared_size_bytes
    )
    return acquisition_url


def _safe_https_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.hostname.lower() in {"localhost", "localhost.localdomain"}
    ):
        raise ValidationError("Acquisition URL must be an explicit credential-free HTTPS URL.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValidationError("Acquisition URL must use a public host.")
    return urlunsplit(("https", parsed.netloc.lower(), parsed.path or "/", "", ""))


def _require_content(
    filename: str,
    content_type: str,
    file_size: int | None,
    settings: Settings | None = None,
) -> None:
    extension = Path(filename).suffix.lower()
    if content_type.lower() not in _ALLOWED_CONTENT.get(extension, frozenset()):
        raise UnsupportedFileError("Filename extension and declared content type are not allowed.")
    if (
        settings is not None
        and file_size is not None
        and file_size > settings.knowledge_document_max_bytes
    ):
        raise UnsupportedFileError("Knowledge document exceeds the configured size limit.")


def _entry_permission_reasons(
    entry: ManifestEntry,
    source: KnowledgeSource,
    authorization: object,
    settings: Settings,
) -> list[str]:
    from apps.api.app.knowledge.models import SourceAuthorization

    reasons = acquisition_permission_reasons(
        source,
        authorization if isinstance(authorization, SourceAuthorization) else None,
        settings,
    )
    if not entry.enabled_flag:
        reasons.append("MANIFEST_ENTRY_DISABLED")
    if entry.acquisition_permission != "APPROVED":
        reasons.append("MANIFEST_ENTRY_NOT_APPROVED")
    if not entry.permission_reference:
        reasons.append("MANIFEST_PERMISSION_REFERENCE_MISSING")
    if entry.acquisition_method != source.acquisition_method:
        reasons.append("MANIFEST_METHOD_MISMATCH")
    if entry.row_version < 1:
        reasons.append("MANIFEST_VERSION_INVALID")
    return reasons


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


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise AuthorizationError()
    return context.tenant_id, context.user_id


def _manifest_response(value: ManifestEntry) -> ManifestEntryResponse:
    return ManifestEntryResponse(
        id=value.manifest_entry_id,
        source_id=value.source_id,
        scope="GLOBAL" if value.tenant_id is None else "TENANT",
        manifest_key=value.manifest_key,
        document_title=value.document_title,
        document_type=value.document_type,
        audience_code=value.audience_code,
        acquisition_url=value.pdf_url or value.html_url,
        acquisition_method=value.acquisition_method,
        acquisition_permission=value.acquisition_permission,
        permission_reference=value.permission_reference,
        enabled=value.enabled_flag,
        expected_sha256=value.expected_sha256,
        original_filename=value.original_filename,
        declared_content_type=value.declared_content_type,
        declared_size_bytes=value.declared_size_bytes,
        row_version=value.row_version,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


async def _run_response(
    repo: IngestionRepository, tenant_id: UUID, run_id: UUID, replayed: bool
) -> RunResponse:
    run = await repo.run(tenant_id, run_id)
    if run is None:
        raise NotFoundError("Acquisition run was not found.")
    items = await repo.run_items(tenant_id, run_id)
    return RunResponse(
        id=run.ingestion_run_id,
        status=run.run_status,
        requested_by=run.requested_by,
        total_items=run.total_items,
        completed_items=run.completed_items,
        failed_items=run.failed_items,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        row_version=run.row_version,
        items=[_item_response(item) for item in items],
        replayed=replayed,
    )


def _item_response(item: IngestionRunItem) -> RunItemResponse:
    return RunItemResponse(
        id=item.ingestion_run_item_id,
        manifest_entry_id=item.manifest_entry_id,
        status=item.item_status,
        attempt_count=item.attempt_count,
        document_id=item.document_id,
        document_version_id=item.document_version_id,
        sha256_checksum=item.observed_sha256,
        filename=item.original_filename,
        declared_content_type=item.declared_content_type,
        detected_content_type=item.detected_content_type,
        file_size_bytes=item.file_size_bytes,
        malware_scan_status=item.malware_scan_status,
        error_code=item.error_code,
        next_attempt_at=item.next_attempt_at,
        final_failure=item.final_failure,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )
