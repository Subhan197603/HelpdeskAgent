"""Tenant-aware, read-only PostgreSQL queries for published catalogue configuration."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.catalog.models import (
    ApplicationEnvironmentReference,
    FormFieldRecord,
    RequestTypeBinding,
    RequestTypeSummary,
    RequestTypeVersion,
    ServiceNode,
    ServiceProject,
    WorkType,
)

_PROJECT_COLUMNS = """
project.project_id, project.project_key, project.project_name,
project.description, project.default_timezone
"""

_LIST_PROJECTS = text(
    f"""
    SELECT {_PROJECT_COLUMNS}
    FROM config.service_project AS project
    JOIN identity.tenant AS tenant ON tenant.tenant_id = project.tenant_id
    WHERE project.tenant_id = :tenant_id
      AND project.active_flag
      AND tenant.active_flag
    ORDER BY project.project_key, project.project_id
    LIMIT :limit OFFSET :offset
    """
)

_GET_PROJECT = text(
    f"""
    SELECT {_PROJECT_COLUMNS}
    FROM config.service_project AS project
    JOIN identity.tenant AS tenant ON tenant.tenant_id = project.tenant_id
    WHERE project.tenant_id = :tenant_id
      AND project.project_id = :project_id
      AND project.active_flag
      AND tenant.active_flag
    """
)

_SERVICE_NODE_EXISTS = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM config.service_node
        WHERE tenant_id = :tenant_id
          AND service_node_id = :service_node_id
          AND active_flag
    )
    """
)

_LIST_SERVICE_NODES = text(
    """
    SELECT service_node_id, parent_node_id, node_code, node_name, node_type,
           display_order, criticality_code, data_classification
    FROM config.service_node
    WHERE tenant_id = :tenant_id
      AND active_flag
      AND parent_node_id IS NOT DISTINCT FROM :parent_node_id
    ORDER BY display_order, node_name, service_node_id
    LIMIT :limit OFFSET :offset
    """
)

_EFFECTIVE_VERSIONS = """
effective_versions AS (
    SELECT version.request_type_version_id, version.request_type_id,
           version.version_number, version.effective_from, version.effective_to,
           count(*) OVER (PARTITION BY version.request_type_id) AS effective_version_count,
           row_number() OVER (
               PARTITION BY version.request_type_id
               ORDER BY version.effective_from DESC NULLS LAST,
                        version.version_number DESC,
                        version.request_type_version_id
           ) AS effective_rank
    FROM config.request_type_version AS version
    WHERE version.version_status = 'PUBLISHED'
      AND version.published_at IS NOT NULL
      AND version.published_at <= :evaluated_at
      AND version.retired_at IS NULL
      AND (version.effective_from IS NULL OR version.effective_from <= :evaluated_at)
      AND (version.effective_to IS NULL OR version.effective_to > :evaluated_at)
)
"""

_REQUEST_TYPE_COLUMNS = """
request_type.request_type_id, request_type.project_id, version.request_type_version_id,
version.version_number, request_type.request_type_code,
request_type.request_type_name, request_type.portal_description,
request_type.portal_group, request_type.display_order,
work_type.work_type_code, work_type.work_type_name,
version.effective_from, version.effective_to, version.effective_version_count
"""

_LIST_REQUEST_TYPES = text(
    f"""
    WITH {_EFFECTIVE_VERSIONS}
    SELECT {_REQUEST_TYPE_COLUMNS}
    FROM config.request_type AS request_type
    JOIN config.service_project AS project
      ON project.project_id = request_type.project_id
     AND project.tenant_id = request_type.tenant_id
    JOIN identity.tenant AS tenant ON tenant.tenant_id = request_type.tenant_id
    JOIN config.work_type AS work_type ON work_type.work_type_id = request_type.work_type_id
    JOIN effective_versions AS version
      ON version.request_type_id = request_type.request_type_id
     AND version.effective_rank = 1
    WHERE request_type.tenant_id = :tenant_id
      AND request_type.project_id = :project_id
      AND request_type.active_flag
      AND request_type.employee_visible_flag
      AND project.active_flag
      AND tenant.active_flag
      AND work_type.active_flag
      AND (work_type.tenant_id IS NULL OR work_type.tenant_id = :tenant_id)
    ORDER BY request_type.display_order, request_type.request_type_name,
             request_type.request_type_id
    LIMIT :limit OFFSET :offset
    """
)

_GET_REQUEST_TYPE = text(
    f"""
    WITH {_EFFECTIVE_VERSIONS}
    SELECT {_REQUEST_TYPE_COLUMNS}
    FROM config.request_type AS request_type
    JOIN config.service_project AS project
      ON project.project_id = request_type.project_id
     AND project.tenant_id = request_type.tenant_id
    JOIN identity.tenant AS tenant ON tenant.tenant_id = request_type.tenant_id
    JOIN config.work_type AS work_type ON work_type.work_type_id = request_type.work_type_id
    JOIN effective_versions AS version
      ON version.request_type_id = request_type.request_type_id
     AND version.effective_rank = 1
    WHERE request_type.tenant_id = :tenant_id
      AND request_type.request_type_id = :request_type_id
      AND (
        CAST(:project_id AS uuid) IS NULL
        OR request_type.project_id = CAST(:project_id AS uuid)
      )
      AND request_type.active_flag
      AND request_type.employee_visible_flag
      AND project.active_flag
      AND tenant.active_flag
      AND work_type.active_flag
      AND (work_type.tenant_id IS NULL OR work_type.tenant_id = :tenant_id)
    """
)

_REQUEST_TYPE_EXISTS = text(
    """
    SELECT EXISTS (
        SELECT 1
        FROM config.request_type AS request_type
        JOIN config.service_project AS project
          ON project.project_id = request_type.project_id
         AND project.tenant_id = request_type.tenant_id
        JOIN identity.tenant AS tenant ON tenant.tenant_id = request_type.tenant_id
        WHERE request_type.tenant_id = :tenant_id
          AND request_type.request_type_id = :request_type_id
          AND request_type.active_flag
          AND request_type.employee_visible_flag
          AND project.active_flag
          AND tenant.active_flag
    )
    """
)

_FORM_FIELDS = text(
    """
    SELECT field.custom_field_id, field.field_code, field.field_name, field.data_type,
           layout.display_label, layout.help_text, layout.display_order,
           layout.required_flag, layout.default_value_json, field.validation_json,
           layout.condition_json, option.option_id, option.option_code,
           option.option_label, option.display_order AS option_display_order
    FROM config.request_type_field AS layout
    JOIN config.custom_field AS field
      ON field.custom_field_id = layout.custom_field_id
     AND field.tenant_id = :tenant_id
     AND field.active_flag
    LEFT JOIN config.custom_field_option AS option
      ON option.custom_field_id = field.custom_field_id
     AND option.active_flag
    WHERE layout.request_type_version_id = :request_type_version_id
      AND NOT layout.hidden_flag
    ORDER BY layout.display_order, field.field_code, field.custom_field_id,
             option.display_order, option.option_label, option.option_id
    """
)

_LIST_ENVIRONMENTS = text(
    """
    SELECT application_environment_id, environment_code, environment_name, service_node_id
    FROM config.application_environment
    WHERE tenant_id = :tenant_id
      AND active_flag
      AND (:service_node_id IS NULL OR service_node_id = :service_node_id)
    ORDER BY environment_name, application_environment_id
    """
)

_REQUEST_TYPE_BINDING = text(
    """
    SELECT request_type.request_type_id, version.request_type_version_id,
           request_type.project_id, request_type.work_type_id,
           request_type.workflow_id, version.version_status,
           request_type.active_flag, request_type.employee_visible_flag
    FROM config.request_type AS request_type
    JOIN config.request_type_version AS version USING (request_type_id)
    WHERE request_type.tenant_id = :tenant_id
      AND request_type.request_type_id = :request_type_id
      AND version.request_type_version_id = :request_type_version_id
    """
)


class CatalogueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_projects(
        self, tenant_id: UUID, *, limit: int, offset: int
    ) -> list[ServiceProject]:
        rows = await self._session.execute(
            _LIST_PROJECTS, {"tenant_id": tenant_id, "limit": limit, "offset": offset}
        )
        return [_project(row) for row in rows]

    async def project(self, tenant_id: UUID, project_id: UUID) -> ServiceProject | None:
        row = (
            await self._session.execute(
                _GET_PROJECT, {"tenant_id": tenant_id, "project_id": project_id}
            )
        ).one_or_none()
        return _project(row) if row is not None else None

    async def service_node_exists(self, tenant_id: UUID, service_node_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                _SERVICE_NODE_EXISTS,
                {"tenant_id": tenant_id, "service_node_id": service_node_id},
            )
        )

    async def request_type_binding(
        self, tenant_id: UUID, request_type_id: UUID, request_type_version_id: UUID
    ) -> RequestTypeBinding | None:
        row = (
            await self._session.execute(
                _REQUEST_TYPE_BINDING,
                {
                    "tenant_id": tenant_id,
                    "request_type_id": request_type_id,
                    "request_type_version_id": request_type_version_id,
                },
            )
        ).one_or_none()
        if row is None:
            return None
        return RequestTypeBinding(
            request_type_id=row.request_type_id,
            request_type_version_id=row.request_type_version_id,
            project_id=row.project_id,
            work_type_id=row.work_type_id,
            workflow_id=row.workflow_id,
            version_status=row.version_status,
            active=row.active_flag,
            employee_visible=row.employee_visible_flag,
        )

    async def list_service_nodes(
        self,
        tenant_id: UUID,
        parent_node_id: UUID | None,
        *,
        limit: int,
        offset: int,
    ) -> list[ServiceNode]:
        rows = await self._session.execute(
            _LIST_SERVICE_NODES,
            {
                "tenant_id": tenant_id,
                "parent_node_id": parent_node_id,
                "limit": limit,
                "offset": offset,
            },
        )
        return [
            ServiceNode(
                row.service_node_id,
                row.parent_node_id,
                row.node_code,
                row.node_name,
                row.node_type,
                row.display_order,
                row.criticality_code,
                row.data_classification,
            )
            for row in rows
        ]

    async def list_request_types(
        self,
        tenant_id: UUID,
        project_id: UUID,
        evaluated_at: datetime,
        *,
        limit: int,
        offset: int,
    ) -> list[RequestTypeSummary]:
        rows = await self._session.execute(
            _LIST_REQUEST_TYPES,
            {
                "tenant_id": tenant_id,
                "project_id": project_id,
                "evaluated_at": evaluated_at,
                "limit": limit,
                "offset": offset,
            },
        )
        return [_request_type(row) for row in rows]

    async def request_type(
        self,
        tenant_id: UUID,
        request_type_id: UUID,
        evaluated_at: datetime,
        *,
        project_id: UUID | None = None,
    ) -> RequestTypeSummary | None:
        row = (
            await self._session.execute(
                _GET_REQUEST_TYPE,
                {
                    "tenant_id": tenant_id,
                    "request_type_id": request_type_id,
                    "project_id": project_id,
                    "evaluated_at": evaluated_at,
                },
            )
        ).one_or_none()
        return _request_type(row) if row is not None else None

    async def request_type_exists(self, tenant_id: UUID, request_type_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                _REQUEST_TYPE_EXISTS,
                {"tenant_id": tenant_id, "request_type_id": request_type_id},
            )
        )

    async def form_fields(
        self, tenant_id: UUID, request_type_version_id: UUID
    ) -> list[FormFieldRecord]:
        rows = await self._session.execute(
            _FORM_FIELDS,
            {
                "tenant_id": tenant_id,
                "request_type_version_id": request_type_version_id,
            },
        )
        return [
            FormFieldRecord(
                row.custom_field_id,
                row.field_code,
                row.field_name,
                row.data_type,
                row.display_label,
                row.help_text,
                row.display_order,
                row.required_flag,
                row.default_value_json,
                row.validation_json,
                row.condition_json,
                row.option_id,
                row.option_code,
                row.option_label,
                row.option_display_order,
            )
            for row in rows
        ]

    async def application_environments(
        self, tenant_id: UUID, service_node_id: UUID | None
    ) -> list[ApplicationEnvironmentReference]:
        rows = await self._session.execute(
            _LIST_ENVIRONMENTS,
            {"tenant_id": tenant_id, "service_node_id": service_node_id},
        )
        return [
            ApplicationEnvironmentReference(
                row.application_environment_id,
                row.environment_code,
                row.environment_name,
                row.service_node_id,
            )
            for row in rows
        ]


def _project(row: Any) -> ServiceProject:
    return ServiceProject(
        row.project_id,
        row.project_key,
        row.project_name,
        row.description,
        row.default_timezone,
    )


def _request_type(row: Any) -> RequestTypeSummary:
    return RequestTypeSummary(
        row.request_type_id,
        row.project_id,
        row.request_type_code,
        row.request_type_name,
        row.portal_description,
        row.portal_group,
        row.display_order,
        WorkType(row.work_type_code, row.work_type_name),
        RequestTypeVersion(
            row.request_type_version_id,
            row.version_number,
            row.effective_from,
            row.effective_to,
            row.effective_version_count,
        ),
    )
