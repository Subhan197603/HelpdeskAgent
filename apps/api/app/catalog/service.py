"""Catalogue use cases, authorization, effective-version checks, and observability."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import groupby
from typing import cast
from uuid import UUID

from pydantic import ValidationError as PydanticValidationError

from apps.api.app.catalog.models import (
    FormFieldRecord,
    RequestTypeSummary,
    ServiceNode,
    ServiceProject,
)
from apps.api.app.catalog.repository import CatalogueRepository
from apps.api.app.catalog.rules import parse_conditional_rule
from apps.api.app.catalog.schemas import (
    CatalogueFieldType,
    FieldOptionResponse,
    FieldValidationResponse,
    FormFieldResponse,
    ProjectResponse,
    RequestFormResponse,
    RequestTypeResponse,
    WorkTypeResponse,
)
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import (
    AuthorizationResource,
    AuthorizationService,
    Permission,
)

logger = logging.getLogger(__name__)
UnitOfWorkFactory = Callable[[RequestContext], SqlAlchemyUnitOfWork]


class CatalogueConfigurationError(ConflictError):
    error_code = "catalogue_configuration_conflict"

    def __init__(self) -> None:
        super().__init__("Published catalogue configuration is inconsistent.")


@dataclass(slots=True)
class CatalogueMetrics:
    requests: int = 0
    query_duration_ms_total: float = 0.0
    query_count: int = 0
    missing_request_types: int = 0
    unauthorized_access: int = 0
    missing_published_versions: int = 0
    overlapping_published_versions: int = 0
    forms_returned: int = 0
    form_field_count: int = 0
    operation_counts: dict[str, int] = field(default_factory=dict)

    def record(self, operation: str, duration_ms: float) -> None:
        self.requests += 1
        self.query_count += 1
        self.query_duration_ms_total += duration_ms
        self.operation_counts[operation] = self.operation_counts.get(operation, 0) + 1


class CatalogueService:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        authorization: AuthorizationService,
        metrics: CatalogueMetrics,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._authorization = authorization
        self._metrics = metrics

    async def list_projects(
        self, context: RequestContext, *, limit: int, offset: int
    ) -> list[ServiceProject]:
        tenant_id = _tenant_id(context)
        self._authorize(context, Permission.CATALOG_PROJECT_LIST)
        async with self._unit_of_work_factory(context) as unit_of_work:
            started = time.perf_counter()
            rows = await CatalogueRepository(unit_of_work.session).list_projects(
                tenant_id, limit=limit, offset=offset
            )
            self._record("list_projects", started, len(rows))
            return rows

    async def project(self, context: RequestContext, project_id: UUID) -> ServiceProject:
        tenant_id = _tenant_id(context)
        self._authorize(context, Permission.CATALOG_PROJECT_LIST)
        async with self._unit_of_work_factory(context) as unit_of_work:
            started = time.perf_counter()
            project = await CatalogueRepository(unit_of_work.session).project(tenant_id, project_id)
            self._record("get_project", started, int(project is not None))
        if project is None:
            raise NotFoundError("Catalogue project was not found.")
        self._authorize(
            context,
            Permission.CATALOG_PROJECT_LIST,
            AuthorizationResource(tenant_id=tenant_id, service_project_id=project.project_id),
        )
        return project

    async def list_services(
        self,
        context: RequestContext,
        project_id: UUID,
        parent_id: UUID | None,
        *,
        limit: int,
        offset: int,
    ) -> list[ServiceNode]:
        tenant_id = _tenant_id(context)
        self._authorize(context, Permission.CATALOG_SERVICE_READ)
        await self.project(context, project_id)
        async with self._unit_of_work_factory(context) as unit_of_work:
            repository = CatalogueRepository(unit_of_work.session)
            if parent_id is not None and not await repository.service_node_exists(
                tenant_id, parent_id
            ):
                raise NotFoundError("Service node was not found.")
            started = time.perf_counter()
            rows = await repository.list_service_nodes(
                tenant_id, parent_id, limit=limit, offset=offset
            )
            self._record("list_service_nodes", started, len(rows))
            return rows

    async def list_request_types(
        self,
        context: RequestContext,
        project_id: UUID,
        *,
        limit: int,
        offset: int,
        evaluated_at: datetime | None = None,
    ) -> tuple[datetime, list[RequestTypeSummary]]:
        tenant_id = _tenant_id(context)
        self._authorize(context, Permission.CATALOG_REQUEST_TYPE_LIST)
        await self.project(context, project_id)
        timestamp = evaluated_at or datetime.now(UTC)
        async with self._unit_of_work_factory(context) as unit_of_work:
            started = time.perf_counter()
            rows = await CatalogueRepository(unit_of_work.session).list_request_types(
                tenant_id,
                project_id,
                timestamp,
                limit=limit,
                offset=offset,
            )
            self._record("list_request_types", started, len(rows))
        self._ensure_unambiguous(rows)
        return timestamp, rows

    async def request_type(
        self,
        context: RequestContext,
        request_type_id: UUID,
        *,
        evaluated_at: datetime | None = None,
    ) -> tuple[datetime, RequestTypeSummary]:
        tenant_id = _tenant_id(context)
        self._authorize(context, Permission.CATALOG_REQUEST_TYPE_LIST)
        timestamp = evaluated_at or datetime.now(UTC)
        async with self._unit_of_work_factory(context) as unit_of_work:
            repository = CatalogueRepository(unit_of_work.session)
            started = time.perf_counter()
            result = await repository.request_type(tenant_id, request_type_id, timestamp)
            exists = result is not None or await repository.request_type_exists(
                tenant_id, request_type_id
            )
            self._record("get_request_type", started, int(result is not None))
        if result is None:
            if exists:
                self._metrics.missing_published_versions += 1
                raise CatalogueConfigurationError()
            self._metrics.missing_request_types += 1
            raise NotFoundError("Request type was not found.")
        self._ensure_unambiguous([result])
        return timestamp, result

    async def form(
        self,
        context: RequestContext,
        request_type_id: UUID,
        *,
        evaluated_at: datetime | None = None,
    ) -> RequestFormResponse:
        tenant_id = _tenant_id(context)
        self._authorize(context, Permission.CATALOG_FORM_READ)
        timestamp, request_type = await self.request_type(
            context, request_type_id, evaluated_at=evaluated_at
        )
        project = await self.project(context, request_type.project_id)
        async with self._unit_of_work_factory(context) as unit_of_work:
            started = time.perf_counter()
            records = await CatalogueRepository(unit_of_work.session).form_fields(
                tenant_id, request_type.version.request_type_version_id
            )
            self._record("get_form_fields", started, len(records))
        try:
            fields = _form_fields(records)
        except PydanticValidationError:
            logger.warning(
                "Catalogue form configuration rejected",
                extra={"error_code": "catalogue_configuration_invalid"},
            )
            raise CatalogueConfigurationError() from None
        self._metrics.forms_returned += 1
        self._metrics.form_field_count += len(fields)
        return RequestFormResponse(
            request_type_id=request_type.request_type_id,
            request_type_version_id=request_type.version.request_type_version_id,
            version_number=request_type.version.version_number,
            code=request_type.request_type_code,
            name=request_type.request_type_name,
            description=request_type.portal_description,
            evaluated_at=timestamp,
            effective_from=request_type.version.effective_from,
            effective_to=request_type.version.effective_to,
            project=_project_response(project),
            work_type=WorkTypeResponse(
                code=request_type.work_type.code, name=request_type.work_type.name
            ),
            fields=fields,
        )

    def _ensure_unambiguous(self, rows: list[RequestTypeSummary]) -> None:
        if any(row.version.effective_version_count != 1 for row in rows):
            self._metrics.overlapping_published_versions += 1
            raise CatalogueConfigurationError()

    def _authorize(
        self,
        context: RequestContext,
        permission: Permission,
        resource: AuthorizationResource | None = None,
    ) -> None:
        if not self._authorization.is_allowed(context, permission, resource):
            self._metrics.unauthorized_access += 1
            raise AuthorizationError(
                "The authenticated user is not permitted to access this catalogue resource."
            )

    def _record(self, operation: str, started: float, row_count: int) -> None:
        duration_ms = (time.perf_counter() - started) * 1000
        self._metrics.record(operation, duration_ms)
        logger.info(
            "Catalogue query completed",
            extra={
                "catalogue_operation": operation,
                "duration_ms": round(duration_ms, 3),
                "row_count": row_count,
            },
        )


def _tenant_id(context: RequestContext) -> UUID:
    if context.tenant_id is None:
        raise AuthorizationError("An authenticated tenant context is required.")
    return context.tenant_id


def _project_response(project: ServiceProject) -> ProjectResponse:
    return ProjectResponse(
        id=project.project_id,
        code=project.project_key,
        name=project.project_name,
        description=project.description,
        default_timezone=project.default_timezone,
    )


def request_type_response(request_type: RequestTypeSummary) -> RequestTypeResponse:
    return RequestTypeResponse(
        id=request_type.request_type_id,
        version_id=request_type.version.request_type_version_id,
        version_number=request_type.version.version_number,
        code=request_type.request_type_code,
        name=request_type.request_type_name,
        description=request_type.portal_description,
        portal_group=request_type.portal_group,
        display_order=request_type.display_order,
        work_type=WorkTypeResponse(
            code=request_type.work_type.code, name=request_type.work_type.name
        ),
        effective_from=request_type.version.effective_from,
        effective_to=request_type.version.effective_to,
    )


def _form_fields(records: list[FormFieldRecord]) -> list[FormFieldResponse]:
    fields: list[FormFieldResponse] = []
    for _, grouped in groupby(records, key=lambda item: item.custom_field_id):
        rows = list(grouped)
        first = rows[0]
        options = [
            FieldOptionResponse(
                id=row.option_id,
                value=cast("str", row.option_code),
                label=cast("str", row.option_label),
                display_order=cast("int", row.option_display_order),
            )
            for row in rows
            if row.option_id is not None
        ]
        fields.append(
            FormFieldResponse(
                field_id=first.custom_field_id,
                field_code=first.field_code,
                data_type=cast("CatalogueFieldType", first.data_type),
                label=first.display_label or first.field_name,
                description=first.help_text,
                required=first.required,
                display_order=first.display_order,
                default_value=first.default_value,
                validation=FieldValidationResponse.model_validate(first.validation),
                condition=parse_conditional_rule(first.condition),
                options=options,
            )
        )
    return fields
