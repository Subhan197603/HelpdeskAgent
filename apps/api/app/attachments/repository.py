"""Tenant-scoped attachment lifecycle persistence."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.attachments.models import Attachment, TicketScope


class AttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ticket(self, tenant_id: UUID, ticket_key: str) -> TicketScope | None:
        row = (
            await self._session.execute(
                text("""
                  SELECT ticket_id,tenant_id,ticket_key,reporter_user_id,requested_for_user_id,
                    assignment_group_id
                  FROM itsm.ticket WHERE tenant_id=:tenant_id AND ticket_key=:ticket_key
                """),
                {"tenant_id": tenant_id, "ticket_key": ticket_key},
            )
        ).one_or_none()
        return TicketScope(*tuple(row)) if row else None

    async def list_for_ticket(self, ticket_id: UUID) -> list[Any]:
        return list(
            (
                await self._session.execute(
                    text("""
                      SELECT attachment.attachment_id,attachment.original_filename,
                        attachment.client_declared_content_type,attachment.file_size_bytes,
                        attachment.malware_scan_status,attachment.visibility_code,
                        uploader.display_name AS uploaded_by_name,attachment.created_at
                      FROM itsm.ticket_attachment AS attachment
                      LEFT JOIN identity.app_user AS uploader
                        ON uploader.user_id=attachment.uploaded_by
                      WHERE attachment.ticket_id=:ticket_id
                      ORDER BY attachment.created_at DESC,attachment.attachment_id DESC
                    """),
                    {"ticket_id": ticket_id},
                )
            ).all()
        )

    async def is_participant(self, ticket_id: UUID, user_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                text("""
                  SELECT EXISTS(SELECT 1 FROM itsm.ticket_participant
                    WHERE ticket_id=:ticket_id AND user_id=:user_id)
                """),
                {"ticket_id": ticket_id, "user_id": user_id},
            )
        )

    async def create(
        self,
        ticket: TicketScope,
        attachment_id: UUID,
        user_id: UUID,
        filename: str,
        object_key: str,
        content_type: str,
        size: int,
        checksum: str,
        visibility: str,
        encryption_status: str,
    ) -> Attachment:
        row = (
            await self._session.execute(
                text("""
                  INSERT INTO itsm.ticket_attachment(
                    attachment_id,ticket_id,uploaded_by,original_filename,quarantine_object_uri,
                    client_declared_content_type,file_size_bytes,sha256_checksum,
                    malware_scan_status,quarantine_status,security_classification,visibility_code,
                    encryption_status)
                  VALUES (:attachment_id,:ticket_id,:user_id,:filename,:object_key,:content_type,
                    :size,:checksum,'PENDING','QUARANTINED',
                    CASE WHEN :visibility='PUBLIC' THEN 'PUBLIC' ELSE 'INTERNAL' END,:visibility,
                    :encryption_status)
                  RETURNING *
                """),
                {
                    "attachment_id": attachment_id,
                    "ticket_id": ticket.ticket_id,
                    "user_id": user_id,
                    "filename": filename,
                    "object_key": object_key,
                    "content_type": content_type,
                    "size": size,
                    "checksum": checksum,
                    "visibility": visibility,
                    "encryption_status": encryption_status,
                },
            )
        ).one()
        return _attachment(row, ticket)

    async def attachment(
        self, tenant_id: UUID, attachment_id: UUID, *, lock: bool = False
    ) -> Attachment | None:
        suffix = " FOR UPDATE OF attachment" if lock else ""
        row = (
            await self._session.execute(
                text(
                    """
                    SELECT attachment.*,ticket.tenant_id,ticket.ticket_key,
                      ticket.reporter_user_id,ticket.requested_for_user_id,
                      ticket.assignment_group_id
                    FROM itsm.ticket_attachment attachment
                    JOIN itsm.ticket ticket ON ticket.ticket_id=attachment.ticket_id
                    WHERE ticket.tenant_id=:tenant_id AND attachment.attachment_id=:attachment_id
                    """
                    + suffix
                ),
                {"tenant_id": tenant_id, "attachment_id": attachment_id},
            )
        ).one_or_none()
        if row is None:
            return None
        ticket = TicketScope(
            row.ticket_id,
            row.tenant_id,
            row.ticket_key,
            row.reporter_user_id,
            row.requested_for_user_id,
            row.assignment_group_id,
        )
        return _attachment(row, ticket)

    async def mark_scanning(self, attachment_id: UUID) -> None:
        await self._session.execute(
            text("""
              UPDATE itsm.ticket_attachment SET malware_scan_status='QUARANTINED',
                quarantine_status='SCANNING',scan_attempt_count=scan_attempt_count+1,
                next_scan_at=NULL,scan_error_details=NULL
              WHERE attachment_id=:attachment_id
            """),
            {"attachment_id": attachment_id},
        )

    async def mark_clean(
        self, attachment_id: UUID, detected_mime: str, protected_key: str, engine: str, version: str
    ) -> None:
        await self._session.execute(
            text("""
              UPDATE itsm.ticket_attachment SET detected_mime_type=:mime,
                protected_object_uri=:protected_key,malware_scan_status='CLEAN',
                quarantine_status='RELEASED',malware_scanned_at=now(),scanner_engine=:engine,
                scanner_version=:version,threat_name=NULL,scan_error_details=NULL,
                released_at=now(),next_scan_at=NULL
              WHERE attachment_id=:attachment_id
            """),
            {
                "attachment_id": attachment_id,
                "mime": detected_mime,
                "protected_key": protected_key,
                "engine": engine,
                "version": version,
            },
        )

    async def mark_infected(
        self, attachment_id: UUID, detected_mime: str, engine: str, version: str, threat: str
    ) -> None:
        await self._session.execute(
            text("""
              UPDATE itsm.ticket_attachment SET detected_mime_type=:mime,
                malware_scan_status='INFECTED',quarantine_status='REJECTED',
                malware_scanned_at=now(),scanner_engine=:engine,scanner_version=:version,
                threat_name=:threat,rejected_at=now(),next_scan_at=NULL
              WHERE attachment_id=:attachment_id
            """),
            {
                "attachment_id": attachment_id,
                "mime": detected_mime,
                "engine": engine,
                "version": version,
                "threat": threat,
            },
        )

    async def mark_error(self, attachment_id: UUID, error_code: str, retry_seconds: int) -> None:
        await self._session.execute(
            text("""
              UPDATE itsm.ticket_attachment SET malware_scan_status='ERROR',
                quarantine_status='QUARANTINED',scan_error_details=:error_code,
                next_scan_at=now()+make_interval(secs => :retry_seconds)
              WHERE attachment_id=:attachment_id
            """),
            {
                "attachment_id": attachment_id,
                "error_code": error_code,
                "retry_seconds": retry_seconds,
            },
        )

    async def mark_invalid(self, attachment_id: UUID, detected_mime: str, reason: str) -> None:
        await self._session.execute(
            text("""
              UPDATE itsm.ticket_attachment SET detected_mime_type=:mime,
                malware_scan_status='ERROR',quarantine_status='REJECTED',
                scan_error_details=:reason,rejected_at=now(),next_scan_at=NULL
              WHERE attachment_id=:attachment_id
            """),
            {"attachment_id": attachment_id, "mime": detected_mime, "reason": reason},
        )

    async def claim_idempotency(
        self, tenant_id: UUID, user_id: UUID, key: str, request_hash: str
    ) -> Any:
        await self._session.execute(
            text("""
              INSERT INTO integration.idempotency_record(
                tenant_id,principal_type,principal_id,operation_code,idempotency_key,
                request_hash,lease_expires_at,expires_at)
              VALUES (:tenant_id,'USER',CAST(:user_id AS varchar),'ATTACHMENT_FINALIZE',:key,
                :request_hash,now()+interval '2 minutes',now()+interval '24 hours')
              ON CONFLICT (tenant_id,operation_code,idempotency_key) DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "key": key,
                "request_hash": request_hash,
            },
        )
        return (
            await self._session.execute(
                text("""
                  SELECT * FROM integration.idempotency_record
                  WHERE tenant_id=:tenant_id AND operation_code='ATTACHMENT_FINALIZE'
                    AND idempotency_key=:key FOR UPDATE
                """),
                {"tenant_id": tenant_id, "key": key},
            )
        ).one()

    async def finish_idempotency(
        self,
        record_id: UUID,
        attachment_id: UUID,
        *,
        status: str,
        response_status: int,
        retryable: bool = False,
    ) -> None:
        await self._session.execute(
            text("""
              UPDATE integration.idempotency_record SET processing_status=CAST(:status AS varchar),
                result_resource_type='ATTACHMENT',
                result_resource_id=CAST(:attachment_id AS varchar),
                response_status=:response_status,retryable_failure=:retryable,
                failure_code=CASE WHEN CAST(:status AS varchar)='FAILED_RETRYABLE'
                  THEN 'SCAN_UNAVAILABLE' END,
                completed_at=CASE WHEN CAST(:status AS varchar) IN ('COMPLETED','FAILED_FINAL')
                  THEN now() END,
                lease_expires_at=NULL
              WHERE idempotency_record_id=:record_id
            """),
            {
                "record_id": record_id,
                "attachment_id": attachment_id,
                "status": status,
                "response_status": response_status,
                "retryable": retryable,
            },
        )

    async def lifecycle_event(
        self,
        attachment: Attachment,
        actor_id: UUID,
        action: str,
        correlation_id: str,
        request_id: str,
        details: dict[str, Any],
        *,
        outcome: str = "SUCCESS",
    ) -> None:
        safe = {**details, "attachment_id": str(attachment.attachment_id)}
        parameters = {
            "tenant_id": attachment.tenant_id,
            "ticket_id": attachment.ticket_id,
            "action": action,
            "actor_id": actor_id,
            "attachment_id": attachment.attachment_id,
            "details": json.dumps(safe),
            "correlation_id": correlation_id,
            "request_id": request_id,
            "outcome": outcome,
        }
        await self._session.execute(
            text("""
              INSERT INTO itsm.ticket_event(
                tenant_id,ticket_id,event_type,actor_type,actor_user_id,event_data_json)
              VALUES (:tenant_id,:ticket_id,:action,'USER',:actor_id,CAST(:details AS jsonb))
            """),
            parameters,
        )
        await self._session.execute(
            text("""
              INSERT INTO audit.audit_event(
                tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                change_summary_json,correlation_id,request_id,source_channel,outcome_code)
              VALUES (:tenant_id,CAST(:actor_id AS varchar),'USER',:action,'ATTACHMENT',
                CAST(:attachment_id AS varchar),CAST(:details AS jsonb),
                CAST(:correlation_id AS uuid),:request_id,'API',:outcome);
            """),
            parameters,
        )


def _attachment(row: Any, ticket: TicketScope) -> Attachment:
    return Attachment(
        row.attachment_id,
        ticket.tenant_id,
        ticket.ticket_id,
        ticket.ticket_key,
        row.uploaded_by,
        row.original_filename,
        row.quarantine_object_uri,
        row.protected_object_uri,
        row.client_declared_content_type,
        row.detected_mime_type,
        row.file_size_bytes,
        row.sha256_checksum,
        row.malware_scan_status,
        row.quarantine_status,
        row.visibility_code,
        row.scanner_engine,
        row.scanner_version,
        row.threat_name,
        row.scan_attempt_count,
        row.next_scan_at,
        row.created_at,
    )
