"""Authorized attachment quarantine, scanning, release, and delivery."""

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from apps.api.app.attachments.clamav import MalwareScanner, ScannerError
from apps.api.app.attachments.models import Attachment, TicketScope
from apps.api.app.attachments.repository import AttachmentRepository
from apps.api.app.attachments.schemas import (
    DownloadResponse,
    FinalizeResponse,
    UploadAuthorizationResponse,
    UploadRequest,
)
from apps.api.app.attachments.storage import ObjectStorage, ObjectTooLargeError, StorageError
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    ExternalDependencyError,
    MalwareDetectedError,
    NotFoundError,
    UnsupportedFileError,
)
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService, Permission

UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]

_ALLOWED: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".png": frozenset({"image/png"}),
    ".jpg": frozenset({"image/jpeg"}),
    ".jpeg": frozenset({"image/jpeg"}),
    ".gif": frozenset({"image/gif"}),
    ".txt": frozenset({"text/plain"}),
    ".csv": frozenset({"text/csv", "text/plain"}),
}


class AttachmentService:
    def __init__(
        self,
        factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        storage: ObjectStorage,
        scanner: MalwareScanner,
        settings: Settings,
    ) -> None:
        self._factory = factory
        self._authorization = authorization
        self._storage = storage
        self._scanner = scanner
        self._settings = settings
        self._enabled = settings.object_storage_enabled

    @property
    def retry_after_seconds(self) -> int:
        return self._settings.clamav_retry_seconds

    async def authorize_upload(
        self, context: RequestContext, ticket_key: str, command: UploadRequest
    ) -> UploadAuthorizationResponse:
        self._require_enabled()
        tenant_id, user_id = _identity(context)
        self._require(context, Permission.ATTACHMENT_UPLOAD)
        if command.file_size_bytes > self._settings.attachment_max_bytes:
            raise UnsupportedFileError("The attachment exceeds the configured size limit.")
        extension = Path(command.filename).suffix.lower()
        if command.content_type not in _ALLOWED.get(extension, frozenset()):
            raise UnsupportedFileError(
                "The filename extension and declared MIME type are not allowed."
            )
        if command.visibility == "INTERNAL":
            self._require(context, Permission.TICKET_COMMENT_INTERNAL)
        attachment_id = uuid4()
        async with self._factory(context) as uow:
            repo = AttachmentRepository(uow.session)
            ticket = await self._ticket(repo, context, tenant_id, user_id, ticket_key, write=True)
            key = f"quarantine/{tenant_id}/{ticket.ticket_id}/{attachment_id}"
            attachment = await repo.create(
                ticket,
                attachment_id,
                user_id,
                command.filename,
                key,
                command.content_type,
                command.file_size_bytes,
                command.sha256_checksum,
                command.visibility,
                (
                    "PROVIDER_MANAGED"
                    if self._settings.object_storage_server_side_encryption
                    else "NOT_APPLICABLE"
                ),
            )
            await repo.lifecycle_event(
                attachment,
                user_id,
                "ATTACHMENT_UPLOAD_AUTHORIZED",
                context.correlation_id,
                context.request_id,
                {"visibility": command.visibility, "file_size_bytes": command.file_size_bytes},
            )
            try:
                url = await self._storage.create_upload_url(
                    key,
                    command.content_type,
                    command.file_size_bytes,
                    command.sha256_checksum,
                    self._settings.attachment_upload_url_seconds,
                )
            except StorageError as exc:
                raise ConflictError("An upload URL could not be issued.") from exc
            await uow.commit()
        expires = datetime.now(UTC) + timedelta(
            seconds=self._settings.attachment_upload_url_seconds
        )
        upload_headers = {
            "Content-Type": command.content_type,
            "Content-Length": str(command.file_size_bytes),
            "x-amz-acl": "private",
            "x-amz-meta-expected-size": str(command.file_size_bytes),
            "x-amz-meta-expected-sha256": command.sha256_checksum,
        }
        if self._settings.object_storage_server_side_encryption is not None:
            upload_headers["x-amz-server-side-encryption"] = (
                self._settings.object_storage_server_side_encryption
            )
        return UploadAuthorizationResponse(
            attachment_id=attachment_id,
            upload_url=url,
            upload_headers=upload_headers,
            expires_at=expires,
        )

    async def finalize(
        self, context: RequestContext, attachment_id: UUID, idempotency_key: str
    ) -> tuple[FinalizeResponse, bool]:
        self._require_enabled()
        tenant_id, user_id = _identity(context)
        self._require(context, Permission.ATTACHMENT_UPLOAD)
        request_hash = hashlib.sha256(str(attachment_id).encode()).hexdigest()
        infected = False
        async with self._factory(context) as uow:
            repo = AttachmentRepository(uow.session)
            attachment = await repo.attachment(tenant_id, attachment_id, lock=True)
            if attachment is None:
                raise NotFoundError("Attachment was not found.")
            ticket = await self._ticket(
                repo, context, tenant_id, user_id, attachment.ticket_key, write=True
            )
            idem = await repo.claim_idempotency(tenant_id, user_id, idempotency_key, request_hash)
            if idem.request_hash != request_hash or idem.principal_id != str(user_id):
                raise ConflictError("The idempotency key was already used for another request.")
            if attachment.quarantine_status == "RELEASED":
                await repo.finish_idempotency(
                    idem.idempotency_record_id,
                    attachment_id,
                    status="COMPLETED",
                    response_status=200,
                )
                await uow.commit()
                return _response(attachment), True
            if attachment.quarantine_status == "REJECTED":
                response_status = 422 if attachment.malware_scan_status == "INFECTED" else 415
                await repo.finish_idempotency(
                    idem.idempotency_record_id,
                    attachment_id,
                    status="FAILED_FINAL",
                    response_status=response_status,
                )
                await uow.commit()
                if attachment.malware_scan_status == "INFECTED":
                    raise MalwareDetectedError("The attachment was rejected by malware scanning.")
                raise UnsupportedFileError("The attachment was rejected by file validation.")
            now = datetime.now(UTC)
            if attachment.next_scan_at is not None and attachment.next_scan_at > now:
                raise ConflictError("The attachment scan retry delay has not elapsed.")
            if attachment.scan_attempt_count >= self._settings.clamav_max_attempts:
                raise ConflictError("The attachment scan retry limit has been reached.")
            await repo.mark_scanning(attachment_id)
            try:
                content = await self._storage.read(
                    attachment.quarantine_object_uri, self._settings.attachment_max_bytes
                )
                detected = _detect_mime(content)
                _validate_content(attachment, content, detected)
                result = await self._scanner.scan(content)
                if result.clean:
                    protected_key = (
                        f"protected/{tenant_id}/{ticket.ticket_id}/"
                        f"{attachment.sha256_checksum[:2]}/{attachment_id}"
                    )
                    await self._storage.promote(
                        attachment.quarantine_object_uri, protected_key, detected
                    )
                    await repo.mark_clean(
                        attachment_id, detected, protected_key, result.engine, result.version
                    )
                    action = "ATTACHMENT_RELEASED"
                    status = "COMPLETED"
                    response_status = 200
                else:
                    await self._storage.reject(attachment.quarantine_object_uri)
                    await repo.mark_infected(
                        attachment_id,
                        detected,
                        result.engine,
                        result.version,
                        result.threat_name or "UNSPECIFIED",
                    )
                    action = "ATTACHMENT_REJECTED_MALWARE"
                    status = "FAILED_FINAL"
                    response_status = 422
                    infected = True
            except (UnsupportedFileError, ObjectTooLargeError) as exc:
                await self._storage.reject(attachment.quarantine_object_uri)
                detail = exc.detail if isinstance(exc, UnsupportedFileError) else str(exc)
                await repo.mark_invalid(attachment_id, _detect_mime_or_unknown(locals()), detail)
                action = "ATTACHMENT_REJECTED_FILE_VALIDATION"
                status = "FAILED_FINAL"
                response_status = 415
            except (ScannerError, StorageError):
                await repo.mark_error(
                    attachment_id,
                    "SCAN_OR_STORAGE_UNAVAILABLE",
                    self._settings.clamav_retry_seconds,
                )
                action = "ATTACHMENT_SCAN_RETRY_SCHEDULED"
                status = "FAILED_RETRYABLE"
                response_status = 503
            updated = await repo.attachment(tenant_id, attachment_id)
            if updated is None:
                raise RuntimeError("Attachment disappeared during finalization")
            await repo.lifecycle_event(
                updated,
                user_id,
                action,
                context.correlation_id,
                context.request_id,
                {
                    "scan_status": updated.malware_scan_status,
                    "quarantine_status": updated.quarantine_status,
                    "scan_attempt_count": updated.scan_attempt_count,
                },
                outcome="FAILED" if status != "COMPLETED" else "SUCCESS",
            )
            await repo.finish_idempotency(
                idem.idempotency_record_id,
                attachment_id,
                status=status,
                response_status=response_status,
                retryable=status == "FAILED_RETRYABLE",
            )
            await uow.commit()
        if infected:
            raise MalwareDetectedError("The attachment was rejected by malware scanning.")
        if updated.quarantine_status == "REJECTED":
            raise UnsupportedFileError("The attachment was rejected by file validation.")
        return _response(updated), False

    async def download(self, context: RequestContext, attachment_id: UUID) -> DownloadResponse:
        self._require_enabled()
        tenant_id, user_id = _identity(context)
        self._require(context, Permission.ATTACHMENT_DOWNLOAD)
        async with self._factory(context) as uow:
            repo = AttachmentRepository(uow.session)
            attachment = await repo.attachment(tenant_id, attachment_id)
            if attachment is None:
                raise NotFoundError("Attachment was not found.")
            await self._ticket(
                repo,
                context,
                tenant_id,
                user_id,
                attachment.ticket_key,
                write=False,
                visibility=attachment.visibility_code,
            )
            if (
                attachment.malware_scan_status != "CLEAN"
                or attachment.quarantine_status != "RELEASED"
                or not attachment.protected_object_uri
            ):
                raise ConflictError("The attachment is not available for download.")
            await repo.lifecycle_event(
                attachment,
                user_id,
                "ATTACHMENT_DOWNLOAD_AUTHORIZED",
                context.correlation_id,
                context.request_id,
                {"visibility": attachment.visibility_code},
            )
            await uow.commit()
        expires = datetime.now(UTC) + timedelta(
            seconds=self._settings.attachment_download_url_seconds
        )
        try:
            url = await self._storage.create_download_url(
                attachment.protected_object_uri,
                attachment.original_filename,
                self._settings.attachment_download_url_seconds,
            )
        except StorageError as exc:
            raise ConflictError("A download URL could not be issued.") from exc
        return DownloadResponse(attachment_id=attachment_id, download_url=url, expires_at=expires)

    async def _ticket(
        self,
        repo: AttachmentRepository,
        context: RequestContext,
        tenant_id: UUID,
        user_id: UUID,
        ticket_key: str,
        *,
        write: bool,
        visibility: str = "PUBLIC",
    ) -> TicketScope:
        ticket = await repo.ticket(tenant_id, ticket_key)
        if ticket is None:
            raise NotFoundError("Ticket was not found.")
        own = user_id in {
            ticket.reporter_user_id,
            ticket.requested_for_user_id,
        } or await repo.is_participant(ticket.ticket_id, user_id)
        all_access = self._authorization.is_allowed(context, Permission.TICKET_READ_ALL)
        group_access = (
            ticket.assignment_group_id is not None
            and ticket.assignment_group_id in context.support_group_ids
            and self._authorization.is_allowed(context, Permission.TICKET_READ_GROUP)
        )
        analyst = all_access or group_access
        allowed = analyst or (own and visibility == "PUBLIC")
        if write and not (analyst or own):
            allowed = False
        if not allowed:
            raise NotFoundError("Ticket was not found.")
        return ticket

    def _require(self, context: RequestContext, permission: Permission) -> None:
        if not self._authorization.is_allowed(context, permission):
            raise AuthorizationError()

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise ExternalDependencyError("Attachment storage is disabled.")


def _identity(context: RequestContext) -> tuple[UUID, UUID]:
    if context.tenant_id is None or context.user_id is None:
        raise AuthorizationError()
    return context.tenant_id, context.user_id


def _detect_mime(content: bytes) -> str:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if b"\x00" not in content:
        try:
            content.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    return "application/octet-stream"


def _validate_content(attachment: Attachment, content: bytes, detected: str) -> None:
    if len(content) != attachment.file_size_bytes:
        raise UnsupportedFileError("The uploaded size does not match the authorized upload.")
    if hashlib.sha256(content).hexdigest() != attachment.sha256_checksum:
        raise UnsupportedFileError("The uploaded checksum does not match the authorized upload.")
    extension = Path(attachment.original_filename).suffix.lower()
    if detected not in _ALLOWED.get(extension, frozenset()):
        raise UnsupportedFileError("The detected MIME type does not match the filename extension.")


def _detect_mime_or_unknown(values: dict[str, object]) -> str:
    detected = values.get("detected")
    return detected if isinstance(detected, str) else "application/octet-stream"


def _response(attachment: Attachment) -> FinalizeResponse:
    return FinalizeResponse(
        attachment_id=attachment.attachment_id,
        ticket_key=attachment.ticket_key,
        filename=attachment.original_filename,
        content_type=attachment.detected_mime_type or attachment.client_declared_content_type or "",
        file_size_bytes=attachment.file_size_bytes,
        sha256_checksum=attachment.sha256_checksum,
        scan_status=attachment.malware_scan_status,  # type: ignore[arg-type]
        quarantine_status=attachment.quarantine_status,  # type: ignore[arg-type]
        scanner_engine=attachment.scanner_engine,
        scanner_version=attachment.scanner_version,
        created_at=attachment.created_at,
    )
