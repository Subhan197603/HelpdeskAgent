"""Tenant-scoped persistence for acquisition administration."""

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.ingestion.models import (
    ChangeReportPage,
    IngestionRun,
    IngestionRunItem,
    ManifestEntry,
)
from apps.api.app.ingestion.schemas import ManifestEntryInput, ManualUploadCommand
from apps.api.app.knowledge.models import IdempotencyClaim

_MANIFEST_COLUMNS = """
manifest_entry_id,tenant_id,source_id,manifest_key,document_title,document_type,
audience_code,canonical_url,pdf_url,html_url,target_collection,security_classification,
acquisition_permission,permission_reference,acquisition_method,enabled_flag,expected_sha256,
original_filename,declared_content_type,declared_size_bytes,source_last_modified_at,
copyright_notice,approved_by,approved_at,row_version,created_at,updated_at
"""


class IngestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def manifest(
        self, tenant_id: UUID, entry_id: UUID, *, lock: bool = False
    ) -> ManifestEntry | None:
        suffix = " FOR UPDATE" if lock else ""
        row = (
            await self._session.execute(
                text(
                    f"SELECT {_MANIFEST_COLUMNS} FROM kb.ingestion_manifest_entry "
                    "WHERE manifest_entry_id=:entry_id "
                    "AND (tenant_id=:tenant_id OR tenant_id IS NULL)" + suffix
                ),
                {"tenant_id": tenant_id, "entry_id": entry_id},
            )
        ).one_or_none()
        return ManifestEntry(*tuple(row)) if row is not None else None

    async def manifests(self, tenant_id: UUID, entry_ids: list[UUID]) -> list[ManifestEntry]:
        statement = text(
            f"SELECT {_MANIFEST_COLUMNS} FROM kb.ingestion_manifest_entry "
            "WHERE (tenant_id=:tenant_id OR tenant_id IS NULL) AND manifest_entry_id IN :entry_ids "
            "ORDER BY manifest_entry_id"
        ).bindparams(bindparam("entry_ids", expanding=True))
        rows = (
            await self._session.execute(statement, {"tenant_id": tenant_id, "entry_ids": entry_ids})
        ).all()
        return [ManifestEntry(*tuple(row)) for row in rows]

    async def manifest_by_key(
        self, tenant_id: UUID, source_id: UUID, manifest_key: str
    ) -> ManifestEntry | None:
        row = (
            await self._session.execute(
                text(
                    f"SELECT {_MANIFEST_COLUMNS} FROM kb.ingestion_manifest_entry "
                    "WHERE source_id=:source_id AND manifest_key=:manifest_key "
                    "AND (tenant_id=:tenant_id OR tenant_id IS NULL)"
                ),
                {"tenant_id": tenant_id, "source_id": source_id, "manifest_key": manifest_key},
            )
        ).one_or_none()
        return ManifestEntry(*tuple(row)) if row is not None else None

    async def approved_entries_for_source(
        self, tenant_id: UUID, source_id: UUID
    ) -> list[ManifestEntry]:
        rows = (
            await self._session.execute(
                text(
                    f"SELECT {_MANIFEST_COLUMNS} FROM kb.ingestion_manifest_entry "
                    "WHERE source_id=:source_id AND enabled_flag "
                    "AND acquisition_permission='APPROVED' "
                    "AND (tenant_id=:tenant_id OR tenant_id IS NULL) "
                    "ORDER BY manifest_key"
                ),
                {"tenant_id": tenant_id, "source_id": source_id},
            )
        ).all()
        return [ManifestEntry(*tuple(row)) for row in rows]

    async def import_entry(
        self,
        resource_tenant_id: UUID | None,
        actor_user_id: UUID,
        entry: ManifestEntryInput,
        correlation_id: str,
        request_id: str,
    ) -> UUID:
        entry_id = uuid4()
        is_pdf = entry.declared_content_type.lower() == "application/pdf"
        row = (
            await self._session.execute(
                text("""
                    INSERT INTO kb.ingestion_manifest_entry(
                      manifest_entry_id,tenant_id,source_id,manifest_key,document_title,
                      document_type,audience_code,canonical_url,pdf_url,html_url,
                      target_collection,security_classification,acquisition_permission,
                      permission_reference,acquisition_method,enabled_flag,expected_sha256,
                      original_filename,declared_content_type,declared_size_bytes,
                      source_last_modified_at,copyright_notice)
                    VALUES (:entry_id,:tenant_id,:source_id,:manifest_key,:document_title,
                      :document_type,:audience_code,:canonical_url,
                      CASE WHEN :is_pdf THEN :acquisition_url END,
                      CASE WHEN NOT :is_pdf THEN :acquisition_url END,
                      :target_collection,:security_classification,'PENDING',NULL,
                      :acquisition_method,true,:expected_sha256,:original_filename,
                      :declared_content_type,:declared_size_bytes,:source_last_modified_at,
                      :copyright_notice)
                    ON CONFLICT (source_id,manifest_key) DO UPDATE SET
                      document_title=excluded.document_title,
                      document_type=excluded.document_type,audience_code=excluded.audience_code,
                      canonical_url=excluded.canonical_url,pdf_url=excluded.pdf_url,
                      html_url=excluded.html_url,target_collection=excluded.target_collection,
                      security_classification=excluded.security_classification,
                      acquisition_permission='PENDING',permission_reference=NULL,
                      acquisition_method=excluded.acquisition_method,enabled_flag=true,
                      expected_sha256=excluded.expected_sha256,
                      original_filename=excluded.original_filename,
                      declared_content_type=excluded.declared_content_type,
                      declared_size_bytes=excluded.declared_size_bytes,
                      source_last_modified_at=excluded.source_last_modified_at,
                      copyright_notice=excluded.copyright_notice,approved_by=NULL,approved_at=NULL,
                      row_version=kb.ingestion_manifest_entry.row_version+1
                    RETURNING manifest_entry_id
                """),
                {
                    "entry_id": entry_id,
                    "tenant_id": resource_tenant_id,
                    "is_pdf": is_pdf,
                    **entry.model_dump(),
                },
            )
        ).one()
        result_id = UUID(str(row.manifest_entry_id))
        await self.audit(
            resource_tenant_id,
            actor_user_id,
            "KNOWLEDGE_MANIFEST_IMPORTED",
            "KNOWLEDGE_MANIFEST_ENTRY",
            result_id,
            {"manifest_key": entry.manifest_key, "permission_reset": True},
            correlation_id,
            request_id,
        )
        return result_id

    async def decide_manifest(
        self,
        tenant_id: UUID,
        entry_id: UUID,
        actor_user_id: UUID,
        decision: str,
        permission_reference: str,
        expected_version: int,
        correlation_id: str,
        request_id: str,
    ) -> bool:
        row = (
            await self._session.execute(
                text("""
                    UPDATE kb.ingestion_manifest_entry SET
                      acquisition_permission=CAST(:decision AS varchar),
                      permission_reference=:permission_reference,
                      approved_by=CASE WHEN CAST(:decision AS varchar)='APPROVED'
                        THEN :actor_user_id ELSE NULL END,
                      approved_at=CASE WHEN CAST(:decision AS varchar)='APPROVED'
                        THEN now() ELSE NULL END,
                      row_version=row_version+1
                    WHERE manifest_entry_id=:entry_id
                      AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                      AND row_version=:expected_version
                    RETURNING tenant_id
                """),
                {
                    "tenant_id": tenant_id,
                    "entry_id": entry_id,
                    "actor_user_id": actor_user_id,
                    "decision": decision,
                    "permission_reference": permission_reference,
                    "expected_version": expected_version,
                },
            )
        ).one_or_none()
        if row is None:
            return False
        await self.audit(
            row.tenant_id,
            actor_user_id,
            "KNOWLEDGE_MANIFEST_PERMISSION_DECIDED",
            "KNOWLEDGE_MANIFEST_ENTRY",
            entry_id,
            {"decision": decision, "new_version": expected_version + 1},
            correlation_id,
            request_id,
        )
        return True

    async def create_run(
        self,
        tenant_id: UUID,
        actor_user_id: UUID,
        entries: list[tuple[ManifestEntry, int, str | None]],
        correlation_id: str,
        request_id: str,
        *,
        awaiting_upload: bool = False,
        run_type: str = "ACQUISITION",
    ) -> tuple[UUID, list[UUID]]:
        run_id = uuid4()
        await self._session.execute(
            text("""
                INSERT INTO kb.ingestion_run(
                  ingestion_run_id,tenant_id,run_type,run_status,requested_by,
                  total_items,correlation_id,request_id)
                VALUES (:run_id,:tenant_id,:run_type,'QUEUED',:actor_user_id,
                  :total_items,CAST(:correlation_id AS uuid),:request_id)
            """),
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "run_type": run_type,
                "actor_user_id": actor_user_id,
                "total_items": len(entries),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
        item_ids: list[UUID] = []
        for entry, source_version, permission_reference in entries:
            item_id = uuid4()
            item_ids.append(item_id)
            quarantine_key = f"quarantine/knowledge/{tenant_id}/{run_id}/{item_id}"
            await self._session.execute(
                text("""
                    INSERT INTO kb.ingestion_run_item(
                      ingestion_run_item_id,ingestion_run_id,manifest_entry_id,tenant_id,
                      item_status,source_row_version,manifest_entry_row_version,
                      permission_reference_snapshot,quarantine_object_key,original_filename,
                      declared_content_type,file_size_bytes,next_attempt_at)
                    VALUES (:item_id,:run_id,:entry_id,:tenant_id,:status,:source_version,
                      :manifest_version,:permission_reference,:quarantine_key,:filename,
                      :content_type,:file_size,now())
                """),
                {
                    "item_id": item_id,
                    "run_id": run_id,
                    "entry_id": entry.manifest_entry_id,
                    "tenant_id": tenant_id,
                    "status": "AWAITING_UPLOAD" if awaiting_upload else "QUEUED",
                    "source_version": source_version,
                    "manifest_version": entry.row_version,
                    "permission_reference": permission_reference,
                    "quarantine_key": quarantine_key,
                    "filename": entry.original_filename,
                    "content_type": entry.declared_content_type,
                    "file_size": entry.declared_size_bytes,
                },
            )
        await self.audit(
            tenant_id,
            actor_user_id,
            "KNOWLEDGE_REFRESH_RUN_CREATED"
            if run_type == "REFRESH"
            else "KNOWLEDGE_ACQUISITION_RUN_CREATED",
            "INGESTION_RUN",
            run_id,
            {"total_items": len(entries), "awaiting_upload": awaiting_upload},
            correlation_id,
            request_id,
        )
        return run_id, item_ids

    async def upsert_manual_manifest(
        self, tenant_id: UUID | None, command: ManualUploadCommand
    ) -> ManifestEntry:
        entry_id = uuid4()
        row = (
            await self._session.execute(
                text(f"""
                    INSERT INTO kb.ingestion_manifest_entry(
                      manifest_entry_id,tenant_id,source_id,manifest_key,document_title,
                      document_type,audience_code,target_collection,security_classification,
                      acquisition_permission,acquisition_method,enabled_flag,expected_sha256,
                      original_filename,declared_content_type,declared_size_bytes,copyright_notice)
                    VALUES (:entry_id,:tenant_id,:source_id,:manifest_key,:document_title,
                      :document_type,:audience_code,:target_collection,:security_classification,
                      'NOT_REQUIRED','MANUAL_UPLOAD',true,:sha256_checksum,:filename,
                      :content_type,:file_size_bytes,:copyright_notice)
                    ON CONFLICT (source_id,manifest_key) DO UPDATE SET
                      document_title=excluded.document_title,document_type=excluded.document_type,
                      audience_code=excluded.audience_code,target_collection=excluded.target_collection,
                      security_classification=excluded.security_classification,
                      acquisition_permission='NOT_REQUIRED',acquisition_method='MANUAL_UPLOAD',
                      enabled_flag=true,expected_sha256=excluded.expected_sha256,
                      original_filename=excluded.original_filename,
                      declared_content_type=excluded.declared_content_type,
                      declared_size_bytes=excluded.declared_size_bytes,
                      copyright_notice=excluded.copyright_notice,approved_by=NULL,approved_at=NULL,
                      row_version=kb.ingestion_manifest_entry.row_version+1
                    RETURNING {_MANIFEST_COLUMNS}
                """),
                {"entry_id": entry_id, "tenant_id": tenant_id, **command.model_dump()},
            )
        ).one()
        return ManifestEntry(*tuple(row))

    async def complete_upload(self, tenant_id: UUID, item_id: UUID) -> tuple[UUID, bool] | None:
        row = (
            await self._session.execute(
                text("""
                    UPDATE kb.ingestion_run_item SET item_status='QUEUED',next_attempt_at=now(),
                      row_version=row_version+1
                    WHERE tenant_id=:tenant_id AND ingestion_run_item_id=:item_id
                      AND item_status='AWAITING_UPLOAD'
                    RETURNING ingestion_run_id
                """),
                {"tenant_id": tenant_id, "item_id": item_id},
            )
        ).one_or_none()
        if row is not None:
            return UUID(str(row.ingestion_run_id)), False
        existing = (
            await self._session.execute(
                text("""
                    SELECT ingestion_run_id,item_status FROM kb.ingestion_run_item
                    WHERE tenant_id=:tenant_id AND ingestion_run_item_id=:item_id
                """),
                {"tenant_id": tenant_id, "item_id": item_id},
            )
        ).one_or_none()
        if existing is None:
            return None
        return UUID(str(existing.ingestion_run_id)), existing.item_status != "AWAITING_UPLOAD"

    async def run(self, tenant_id: UUID, run_id: UUID) -> IngestionRun | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT ingestion_run_id,tenant_id,run_status,requested_by,total_items,
                      completed_items,failed_items,created_at,started_at,completed_at,row_version
                    FROM kb.ingestion_run
                    WHERE tenant_id=:tenant_id AND ingestion_run_id=:run_id
                """),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
        ).one_or_none()
        return IngestionRun(*tuple(row)) if row is not None else None

    async def run_items(self, tenant_id: UUID, run_id: UUID) -> list[IngestionRunItem]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT ingestion_run_item_id,manifest_entry_id,item_status,attempt_count,
                      document_id,document_version_id,observed_sha256,original_filename,
                      declared_content_type,detected_content_type,file_size_bytes,
                      malware_scan_status,error_code,next_attempt_at,final_failure,created_at,updated_at
                    FROM kb.ingestion_run_item
                    WHERE tenant_id=:tenant_id AND ingestion_run_id=:run_id
                    ORDER BY created_at,ingestion_run_item_id
                """),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
        ).all()
        return [IngestionRunItem(*tuple(row)) for row in rows]

    async def latest_refresh_run(self, tenant_id: UUID, source_id: UUID) -> IngestionRun | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT run.ingestion_run_id,run.tenant_id,run.run_status,run.requested_by,
                      run.total_items,run.completed_items,run.failed_items,run.created_at,
                      run.started_at,run.completed_at,run.row_version
                    FROM kb.ingestion_run AS run
                    WHERE run.tenant_id=:tenant_id AND run.run_type='REFRESH'
                      AND EXISTS (
                        SELECT 1 FROM kb.ingestion_run_item AS item
                        JOIN kb.ingestion_manifest_entry AS entry
                          ON entry.manifest_entry_id=item.manifest_entry_id
                        WHERE item.ingestion_run_id=run.ingestion_run_id
                          AND entry.source_id=:source_id
                      )
                    ORDER BY run.created_at DESC,run.ingestion_run_id DESC LIMIT 1
                """),
                {"tenant_id": tenant_id, "source_id": source_id},
            )
        ).one_or_none()
        return IngestionRun(*tuple(row)) if row is not None else None

    async def change_report_pages(self, tenant_id: UUID, run_id: UUID) -> list[ChangeReportPage]:
        rows = (
            await self._session.execute(
                text("""
                    SELECT item.ingestion_run_item_id,entry.manifest_key,entry.document_title,
                      item.item_status,item.change_classification,item.previous_sha256,
                      item.observed_sha256,item.redirect_target_url,item.observed_http_status,
                      item.error_code,item.final_failure,item.completed_at
                    FROM kb.ingestion_run_item AS item
                    JOIN kb.ingestion_manifest_entry AS entry
                      ON entry.manifest_entry_id=item.manifest_entry_id
                    WHERE item.tenant_id=:tenant_id AND item.ingestion_run_id=:run_id
                    ORDER BY entry.manifest_key,item.ingestion_run_item_id
                """),
                {"tenant_id": tenant_id, "run_id": run_id},
            )
        ).all()
        return [ChangeReportPage(*tuple(row)) for row in rows]

    async def item_quarantine_key(self, tenant_id: UUID, item_id: UUID) -> str | None:
        value = await self._session.scalar(
            text("""
                SELECT quarantine_object_key FROM kb.ingestion_run_item
                WHERE tenant_id=:tenant_id AND ingestion_run_item_id=:item_id
            """),
            {"tenant_id": tenant_id, "item_id": item_id},
        )
        return str(value) if value is not None else None

    async def claim_idempotency(
        self, tenant_id: UUID, user_id: UUID, key: str, request_hash: str, operation: str
    ) -> IdempotencyClaim:
        await self._session.execute(
            text("""
                INSERT INTO integration.idempotency_record(
                  tenant_id,principal_type,principal_id,operation_code,idempotency_key,
                  request_hash,lease_expires_at,expires_at)
                VALUES (:tenant_id,'USER',CAST(:user_id AS varchar),:operation,:key,
                  :request_hash,now()+interval '2 minutes',now()+interval '24 hours')
                ON CONFLICT (tenant_id,operation_code,idempotency_key) DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "operation": operation,
                "key": key,
                "request_hash": request_hash,
            },
        )
        row = (
            await self._session.execute(
                text("""
                    SELECT idempotency_record_id,principal_id,request_hash,processing_status,
                      result_resource_id FROM integration.idempotency_record
                    WHERE tenant_id=:tenant_id AND operation_code=:operation
                      AND idempotency_key=:key FOR UPDATE
                """),
                {"tenant_id": tenant_id, "operation": operation, "key": key},
            )
        ).one()
        return IdempotencyClaim(*tuple(row))

    async def complete_idempotency(
        self, record_id: UUID, resource_type: str, resource_id: UUID, status: int
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE integration.idempotency_record SET processing_status='COMPLETED',
                  result_resource_type=:resource_type,
                  result_resource_id=CAST(:resource_id AS varchar),response_status=:status,
                  completed_at=now(),lease_expires_at=NULL
                WHERE idempotency_record_id=:record_id
            """),
            {
                "record_id": record_id,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "status": status,
            },
        )

    async def audit(
        self,
        tenant_id: UUID | None,
        actor_user_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        summary: dict[str, Any],
        correlation_id: str,
        request_id: str,
    ) -> None:
        await self._session.execute(
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,resource_id,
                  change_summary_json,correlation_id,request_id,source_channel,outcome_code)
                VALUES (:tenant_id,CAST(:actor_user_id AS varchar),'USER',:action,
                  :resource_type,CAST(:resource_id AS varchar),CAST(:summary AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "summary": json.dumps(summary),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
