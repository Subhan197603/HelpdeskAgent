"""Transactional persistence for knowledge-source governance."""

import json
from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.exceptions import ConflictError
from apps.api.app.knowledge.models import (
    IdempotencyClaim,
    KnowledgeSource,
    SourceAuthorization,
)
from apps.api.app.knowledge.schemas import SourceDefinition

_SOURCE_SELECT = """
SELECT source.source_id,source.tenant_id,source.source_code,source.source_name,
  source.source_type,source.publisher_name,source.canonical_location,
  source.acquisition_method,source.automated_access_allowed,
  source.permission_reference,source.audience_scope,source.source_status,
  source.approval_status,source.owner_user_id,source.owner_group_id,
  source.product_node_id,product.product_code,source.module_node_id,
  module.product_code,source.release_id,release.release_family,
  release.release_code,source.language_code,source.approved_by,source.approved_at,
  source.row_version,source.created_at,source.updated_at,
  source.refresh_state,source.refresh_due_at,source.last_refresh_requested_at,
  source.last_refresh_requested_by,source.last_refresh_completed_at,
  acquisition.item_status,acquisition.created_at
FROM kb.source AS source
LEFT JOIN kb.product_node AS product ON product.product_node_id=source.product_node_id
LEFT JOIN kb.product_node AS module ON module.product_node_id=source.module_node_id
LEFT JOIN kb.release AS release ON release.release_id=source.release_id
LEFT JOIN LATERAL (
  SELECT item.item_status,item.created_at
  FROM kb.ingestion_run_item AS item
  JOIN kb.ingestion_manifest_entry AS entry
    ON entry.manifest_entry_id=item.manifest_entry_id
  WHERE entry.source_id=source.source_id
  ORDER BY item.created_at DESC LIMIT 1
) AS acquisition ON true
"""

_SOURCE_LIST_FILTER = """
WHERE (source.tenant_id=:tenant_id OR source.tenant_id IS NULL)
  AND (CAST(:source_type AS varchar) IS NULL
    OR source.source_type=:source_type)
  AND (CAST(:audience AS varchar) IS NULL
    OR source.audience_scope=:audience)
  AND (CAST(:status AS varchar) IS NULL
    OR source.source_status=:status)
  AND (CAST(:approval_status AS varchar) IS NULL
    OR source.approval_status=:approval_status)
  AND (CAST(:refresh_state AS varchar) IS NULL
    OR source.refresh_state=:refresh_state)
  AND (CAST(:search AS varchar) IS NULL
    OR source.source_code ILIKE '%' || :search || '%'
    OR source.source_name ILIKE '%' || :search || '%')
"""


class KnowledgeSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(
        self,
        tenant_id: UUID,
        *,
        source_type: str | None,
        audience: str | None,
        status: str | None,
        approval_status: str | None,
        refresh_state: str | None = None,
        search: str | None = None,
        limit: int,
        offset: int = 0,
    ) -> tuple[list[KnowledgeSource], int]:
        parameters = {
            "tenant_id": tenant_id,
            "source_type": source_type,
            "audience": audience,
            "status": status,
            "approval_status": approval_status,
            "refresh_state": refresh_state,
            "search": search,
        }
        rows = (
            await self._session.execute(
                text(
                    _SOURCE_SELECT
                    + _SOURCE_LIST_FILTER
                    + "ORDER BY source.source_code,source.source_id "
                    + "LIMIT :limit OFFSET :offset"
                ),
                {**parameters, "limit": limit, "offset": offset},
            )
        ).all()
        total = await self._session.scalar(
            text("SELECT count(*) FROM kb.source AS source " + _SOURCE_LIST_FILTER),
            parameters,
        )
        return [KnowledgeSource(*tuple(row)) for row in rows], int(total or 0)

    async def get(
        self, tenant_id: UUID, source_id: UUID, *, lock: bool = False
    ) -> KnowledgeSource | None:
        suffix = " FOR UPDATE OF source" if lock else ""
        row = (
            await self._session.execute(
                text(
                    _SOURCE_SELECT
                    + """
                    WHERE source.source_id=:source_id
                      AND (source.tenant_id=:tenant_id OR source.tenant_id IS NULL)
                    """
                    + suffix
                ),
                {"tenant_id": tenant_id, "source_id": source_id},
            )
        ).one_or_none()
        return KnowledgeSource(*tuple(row)) if row is not None else None

    async def reference_exists(
        self, table: str, identifier_column: str, identifier: UUID, tenant_id: UUID
    ) -> bool:
        allowed = {
            ("identity.app_user", "user_id"),
            ("identity.support_group", "support_group_id"),
            ("kb.product_node", "product_node_id"),
        }
        if (table, identifier_column) not in allowed:
            raise ValueError("Unsupported knowledge reference")
        value = await self._session.scalar(
            text(
                f"SELECT EXISTS(SELECT 1 FROM {table} WHERE {identifier_column}=:identifier "
                "AND active_flag AND (tenant_id=:tenant_id OR tenant_id IS NULL))"
            ),
            {"identifier": identifier, "tenant_id": tenant_id},
        )
        return bool(value)

    async def release_exists(self, release_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                text("SELECT EXISTS(SELECT 1 FROM kb.release WHERE release_id=:release_id)"),
                {"release_id": release_id},
            )
        )

    async def product_level(self, node_id: UUID) -> str | None:
        value = await self._session.scalar(
            text("SELECT product_level FROM kb.product_node WHERE product_node_id=:node_id"),
            {"node_id": node_id},
        )
        return str(value) if value is not None else None

    async def create(
        self,
        tenant_id: UUID | None,
        actor_user_id: UUID,
        definition: SourceDefinition,
        correlation_id: str,
        request_id: str,
    ) -> UUID:
        source_id = uuid4()
        try:
            await self._session.execute(
                text("""
                INSERT INTO kb.source(
                  source_id,tenant_id,source_code,source_name,source_type,publisher_name,
                  base_url,canonical_location,acquisition_method,automated_access_allowed,
                  permission_reference,active_flag,audience_scope,source_status,
                  approval_status,owner_user_id,owner_group_id,product_node_id,
                  module_node_id,release_id,language_code,created_by,updated_by)
                VALUES (:source_id,:tenant_id,:code,:name,:source_type,:publisher_name,
                  :canonical_location,:canonical_location,:acquisition_method,false,
                  :permission_reference,:active_flag,:audience_scope,:status,'DRAFT',
                  :owner_user_id,:owner_group_id,:product_node_id,:module_node_id,
                  :release_id,:language_code,:actor_user_id,:actor_user_id)
                """),
                {
                    "source_id": source_id,
                    "tenant_id": tenant_id,
                    "actor_user_id": actor_user_id,
                    "active_flag": definition.status == "ACTIVE",
                    **definition.model_dump(),
                },
            )
        except IntegrityError as error:
            raise ConflictError("Knowledge source code or metadata conflicts.") from error
        await self._audit(
            tenant_id,
            actor_user_id,
            source_id,
            "KNOWLEDGE_SOURCE_CREATED",
            {"scope": "GLOBAL" if tenant_id is None else "TENANT", "status": definition.status},
            correlation_id,
            request_id,
        )
        return source_id

    async def update(
        self,
        tenant_id: UUID,
        source_id: UUID,
        actor_user_id: UUID,
        definition: SourceDefinition,
        expected_version: int,
        correlation_id: str,
        request_id: str,
    ) -> bool:
        try:
            result = cast(
                "CursorResult[Any]",
                await self._session.execute(
                    text("""
                UPDATE kb.source SET source_code=:code,source_name=:name,
                  source_type=:source_type,publisher_name=:publisher_name,
                  base_url=:canonical_location,canonical_location=:canonical_location,
                  acquisition_method=:acquisition_method,
                  permission_reference=:permission_reference,
                  audience_scope=:audience_scope,source_status=:status,
                  active_flag=:active_flag,owner_user_id=:owner_user_id,
                  owner_group_id=:owner_group_id,product_node_id=:product_node_id,
                  module_node_id=:module_node_id,release_id=:release_id,
                  language_code=:language_code,approval_status='DRAFT',approved_by=NULL,
                  approved_at=NULL,automated_access_allowed=false,updated_by=:actor_user_id,
                  row_version=row_version+1
                WHERE source_id=:source_id AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                  AND row_version=:expected_version
                    """),
                    {
                        "tenant_id": tenant_id,
                        "source_id": source_id,
                        "actor_user_id": actor_user_id,
                        "expected_version": expected_version,
                        "active_flag": definition.status == "ACTIVE",
                        **definition.model_dump(),
                    },
                ),
            )
        except IntegrityError as error:
            raise ConflictError("Knowledge source code or metadata conflicts.") from error
        if result.rowcount != 1:
            return False
        await self._audit(
            tenant_id,
            actor_user_id,
            source_id,
            "KNOWLEDGE_SOURCE_UPDATED",
            {"new_version": expected_version + 1, "approval_reset": True},
            correlation_id,
            request_id,
        )
        return True

    async def decide_approval(
        self,
        tenant_id: UUID,
        source_id: UUID,
        actor_user_id: UUID,
        decision: str,
        expected_version: int,
        correlation_id: str,
        request_id: str,
    ) -> bool:
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                text("""
                UPDATE kb.source SET approval_status=CAST(:decision AS varchar),
                  approved_by=CASE WHEN CAST(:decision AS varchar)='APPROVED'
                    THEN :actor_user_id ELSE NULL END,
                  approved_at=CASE WHEN CAST(:decision AS varchar)='APPROVED'
                    THEN now() ELSE NULL END,
                  automated_access_allowed=false,updated_by=:actor_user_id,
                  row_version=row_version+1
                WHERE source_id=:source_id AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                  AND row_version=:expected_version AND approval_status IN
                    ('DRAFT','UNDER_REVIEW','REJECTED')
                """),
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "actor_user_id": actor_user_id,
                    "decision": decision,
                    "expected_version": expected_version,
                },
            ),
        )
        if result.rowcount != 1:
            return False
        await self._audit(
            tenant_id,
            actor_user_id,
            source_id,
            "KNOWLEDGE_SOURCE_APPROVAL_DECIDED",
            {"decision": decision, "new_version": expected_version + 1},
            correlation_id,
            request_id,
        )
        return True

    async def set_refresh_state(
        self,
        tenant_id: UUID,
        source_id: UUID,
        actor_user_id: UUID,
        *,
        action: str,
        target_state: str,
        previous_state: str,
        refresh_due_at: datetime | None,
        expected_version: int,
        correlation_id: str,
        request_id: str,
    ) -> bool:
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                text("""
                UPDATE kb.source SET refresh_state=:target_state,
                  refresh_due_at=CASE
                    WHEN CAST(:action AS varchar)='MARK_REFRESH_DUE'
                      THEN coalesce(:refresh_due_at,now())
                    WHEN CAST(:action AS varchar)='MARK_CURRENT' THEN NULL
                    ELSE refresh_due_at END,
                  last_refresh_requested_at=CASE
                    WHEN CAST(:action AS varchar)='MARK_REFRESH_DUE' THEN now()
                    ELSE last_refresh_requested_at END,
                  last_refresh_requested_by=CASE
                    WHEN CAST(:action AS varchar)='MARK_REFRESH_DUE' THEN :actor_user_id
                    ELSE last_refresh_requested_by END,
                  last_refresh_completed_at=CASE
                    WHEN CAST(:action AS varchar)='MARK_CURRENT' THEN now()
                    ELSE last_refresh_completed_at END,
                  updated_by=:actor_user_id,row_version=row_version+1
                WHERE source_id=:source_id AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                  AND row_version=:expected_version AND source_status<>'RETIRED'
                  AND refresh_state=:previous_state
                """),
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "actor_user_id": actor_user_id,
                    "action": action,
                    "target_state": target_state,
                    "previous_state": previous_state,
                    "refresh_due_at": refresh_due_at,
                    "expected_version": expected_version,
                },
            ),
        )
        if result.rowcount != 1:
            return False
        await self._audit(
            tenant_id,
            actor_user_id,
            source_id,
            "KNOWLEDGE_SOURCE_REFRESH_LIFECYCLE_CHANGED",
            {
                "action": action,
                "from_state": previous_state,
                "to_state": target_state,
                "new_version": expected_version + 1,
            },
            correlation_id,
            request_id,
        )
        return True

    async def start_refresh(
        self,
        tenant_id: UUID,
        source_id: UUID,
        actor_user_id: UUID,
        *,
        previous_state: str,
        expected_version: int,
        correlation_id: str,
        request_id: str,
    ) -> bool:
        # row_version stays unchanged: acquisition authorizations are pinned to
        # the exact source row version, and starting a refresh must not
        # invalidate the allowlist entry the run relies on.
        result = cast(
            "CursorResult[Any]",
            await self._session.execute(
                text("""
                UPDATE kb.source SET refresh_state='REFRESHING',
                  last_refresh_requested_at=now(),
                  last_refresh_requested_by=:actor_user_id
                WHERE source_id=:source_id AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                  AND row_version=:expected_version AND source_status<>'RETIRED'
                  AND refresh_state=:previous_state
                """),
                {
                    "tenant_id": tenant_id,
                    "source_id": source_id,
                    "actor_user_id": actor_user_id,
                    "previous_state": previous_state,
                    "expected_version": expected_version,
                },
            ),
        )
        if result.rowcount != 1:
            return False
        await self._audit(
            tenant_id,
            actor_user_id,
            source_id,
            "KNOWLEDGE_SOURCE_REFRESH_LIFECYCLE_CHANGED",
            {
                "action": "START_REFRESH",
                "from_state": previous_state,
                "to_state": "REFRESHING",
            },
            correlation_id,
            request_id,
        )
        return True

    async def authorize_acquisition(
        self,
        tenant_id: UUID,
        source: KnowledgeSource,
        actor_user_id: UUID,
        *,
        decision: str,
        acquisition_method: str,
        permission_reference: str,
        valid_from: datetime | None,
        valid_to: datetime | None,
        correlation_id: str,
        request_id: str,
    ) -> UUID | None:
        updated = (
            await self._session.execute(
                text("""
                    UPDATE kb.source SET automated_access_allowed=(
                      CAST(:decision AS varchar)='APPROVED'
                    ),
                      permission_reference=:permission_reference,updated_by=:actor_user_id,
                      row_version=row_version+1
                    WHERE source_id=:source_id
                      AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                      AND row_version=:expected_version
                      AND (CAST(:decision AS varchar)='REVOKED' OR (
                        source_status='ACTIVE' AND approval_status='APPROVED'
                        AND acquisition_method=:acquisition_method
                      ))
                    RETURNING row_version,tenant_id
                """),
                {
                    "tenant_id": tenant_id,
                    "source_id": source.source_id,
                    "expected_version": source.row_version,
                    "decision": decision,
                    "acquisition_method": acquisition_method,
                    "permission_reference": permission_reference,
                    "actor_user_id": actor_user_id,
                },
            )
        ).one_or_none()
        if updated is None:
            return None
        authorization_id = uuid4()
        await self._session.execute(
            text("""
                INSERT INTO kb.source_acquisition_authorization(
                  source_acquisition_authorization_id,tenant_id,source_id,
                  source_row_version,acquisition_method,decision_code,
                  canonical_location,permission_reference,valid_from,valid_to,
                  decided_by,correlation_id,request_id)
                VALUES (:authorization_id,:resource_tenant_id,:source_id,:source_row_version,
                  :acquisition_method,:decision,:canonical_location,:permission_reference,
                  coalesce(:valid_from,now()),:valid_to,:actor_user_id,
                  CAST(:correlation_id AS uuid),:request_id)
            """),
            {
                "authorization_id": authorization_id,
                "resource_tenant_id": updated.tenant_id,
                "source_id": source.source_id,
                "source_row_version": updated.row_version,
                "acquisition_method": acquisition_method,
                "decision": decision,
                "canonical_location": source.canonical_location,
                "permission_reference": permission_reference,
                "valid_from": valid_from,
                "valid_to": valid_to,
                "actor_user_id": actor_user_id,
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
        await self._audit(
            tenant_id,
            actor_user_id,
            source.source_id,
            "KNOWLEDGE_SOURCE_ACQUISITION_AUTHORIZATION_RECORDED",
            {"decision": decision, "source_row_version": updated.row_version},
            correlation_id,
            request_id,
        )
        return authorization_id

    async def authorization(
        self, tenant_id: UUID, authorization_id: UUID
    ) -> SourceAuthorization | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT source_acquisition_authorization_id,decision_code,
                      acquisition_method,permission_reference,valid_from,valid_to,
                      decided_by,decided_at
                    FROM kb.source_acquisition_authorization
                    WHERE source_acquisition_authorization_id=:authorization_id
                      AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                """),
                {"tenant_id": tenant_id, "authorization_id": authorization_id},
            )
        ).one_or_none()
        return SourceAuthorization(*tuple(row)) if row is not None else None

    async def effective_authorization(
        self, tenant_id: UUID, source: KnowledgeSource
    ) -> SourceAuthorization | None:
        row = (
            await self._session.execute(
                text("""
                    SELECT source_acquisition_authorization_id,decision_code,
                      acquisition_method,permission_reference,valid_from,valid_to,
                      decided_by,decided_at
                    FROM kb.source_acquisition_authorization
                    WHERE source_id=:source_id AND source_row_version=:source_row_version
                      AND (tenant_id=:tenant_id OR tenant_id IS NULL)
                      AND valid_from<=now() AND (valid_to IS NULL OR valid_to>now())
                    ORDER BY decided_at DESC LIMIT 1
                """),
                {
                    "tenant_id": tenant_id,
                    "source_id": source.source_id,
                    "source_row_version": source.row_version,
                },
            )
        ).one_or_none()
        return SourceAuthorization(*tuple(row)) if row is not None else None

    async def claim_idempotency(
        self,
        tenant_id: UUID,
        user_id: UUID,
        key: str,
        request_hash: str,
        operation_code: str,
    ) -> IdempotencyClaim:
        await self._session.execute(
            text("""
                INSERT INTO integration.idempotency_record(
                  tenant_id,principal_type,principal_id,operation_code,idempotency_key,
                  request_hash,lease_expires_at,expires_at)
                VALUES (:tenant_id,'USER',CAST(:user_id AS varchar),:operation_code,:key,
                  :request_hash,now()+interval '60 seconds',now()+interval '24 hours')
                ON CONFLICT (tenant_id,operation_code,idempotency_key) DO NOTHING
            """),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "operation_code": operation_code,
                "key": key,
                "request_hash": request_hash,
            },
        )
        row = (
            await self._session.execute(
                text("""
                    SELECT idempotency_record_id,principal_id,request_hash,
                      processing_status,result_resource_id
                    FROM integration.idempotency_record
                    WHERE tenant_id=:tenant_id AND operation_code=:operation_code
                      AND idempotency_key=:key FOR UPDATE
                """),
                {"tenant_id": tenant_id, "operation_code": operation_code, "key": key},
            )
        ).one()
        return IdempotencyClaim(*tuple(row))

    async def complete_idempotency(
        self, record_id: UUID, resource_type: str, resource_id: UUID, status: int
    ) -> None:
        await self._session.execute(
            text("""
                UPDATE integration.idempotency_record
                SET processing_status='COMPLETED',result_resource_type=:resource_type,
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

    async def _audit(
        self,
        tenant_id: UUID | None,
        actor_user_id: UUID,
        source_id: UUID,
        action: str,
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
                  'KNOWLEDGE_SOURCE',CAST(:source_id AS varchar),CAST(:summary AS jsonb),
                  CAST(:correlation_id AS uuid),:request_id,'API','SUCCESS')
            """),
            {
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "action": action,
                "source_id": source_id,
                "summary": json.dumps(summary),
                "correlation_id": correlation_id,
                "request_id": request_id,
            },
        )
