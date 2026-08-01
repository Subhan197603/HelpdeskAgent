"""Authenticated, read-only service catalogue HTTP endpoints."""

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from apps.api.app.catalog.models import ServiceProject
from apps.api.app.catalog.schemas import (
    PageMetadata,
    ProblemResponse,
    ProjectListResponse,
    ProjectResponse,
    RequestFormResponse,
    RequestTypeListResponse,
    RequestTypeResponse,
    ServiceNodeListResponse,
    ServiceNodeResponse,
)
from apps.api.app.catalog.service import CatalogueService, request_type_response
from apps.api.app.core.context import RequestContext
from apps.api.app.dependencies.request_context import require_permission
from apps.api.app.identity.authorization import Permission

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"model": ProblemResponse, "description": "Authentication required"},
    403: {"model": ProblemResponse, "description": "Access denied"},
    404: {"model": ProblemResponse, "description": "Catalogue resource not found"},
    409: {"model": ProblemResponse, "description": "Published configuration conflict"},
    422: {"model": ProblemResponse, "description": "Invalid request parameters"},
}

router = APIRouter(prefix="/api/v1/catalog", tags=["catalogue"])
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=100_000)]


def _service(request: Request) -> CatalogueService:
    return cast("CatalogueService", request.app.state.catalogue_service)


@router.get("/projects", response_model=ProjectListResponse, responses=ERROR_RESPONSES)
async def list_projects(
    request: Request,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.CATALOG_PROJECT_LIST))
    ],
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ProjectListResponse:
    rows = await _service(request).list_projects(context, limit=limit, offset=offset)
    items = [_project(row) for row in rows]
    return ProjectListResponse(
        items=items,
        page=PageMetadata(limit=limit, offset=offset, returned=len(items)),
    )


@router.get("/projects/{project_id}", response_model=ProjectResponse, responses=ERROR_RESPONSES)
async def get_project(
    request: Request,
    project_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.CATALOG_PROJECT_LIST))
    ],
) -> ProjectResponse:
    return _project(await _service(request).project(context, project_id))


@router.get(
    "/projects/{project_id}/services",
    response_model=ServiceNodeListResponse,
    responses=ERROR_RESPONSES,
)
async def list_services(
    request: Request,
    project_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.CATALOG_SERVICE_READ))
    ],
    parent_id: UUID | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> ServiceNodeListResponse:
    rows = await _service(request).list_services(
        context, project_id, parent_id, limit=limit, offset=offset
    )
    items = [
        ServiceNodeResponse(
            id=row.service_node_id,
            parent_id=row.parent_node_id,
            code=row.node_code,
            name=row.node_name,
            node_type=row.node_type,
            display_order=row.display_order,
            criticality=row.criticality_code,
            data_classification=row.data_classification,
        )
        for row in rows
    ]
    return ServiceNodeListResponse(
        project_id=project_id,
        parent_id=parent_id,
        items=items,
        page=PageMetadata(limit=limit, offset=offset, returned=len(items)),
    )


@router.get(
    "/projects/{project_id}/request-types",
    response_model=RequestTypeListResponse,
    responses=ERROR_RESPONSES,
)
async def list_request_types(
    request: Request,
    project_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.CATALOG_REQUEST_TYPE_LIST))
    ],
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> RequestTypeListResponse:
    evaluated_at, rows = await _service(request).list_request_types(
        context, project_id, limit=limit, offset=offset
    )
    items = [request_type_response(row) for row in rows]
    return RequestTypeListResponse(
        project_id=project_id,
        evaluated_at=evaluated_at,
        items=items,
        page=PageMetadata(limit=limit, offset=offset, returned=len(items)),
    )


@router.get(
    "/request-types/{request_type_id}",
    response_model=RequestTypeResponse,
    responses=ERROR_RESPONSES,
)
async def get_request_type(
    request: Request,
    request_type_id: UUID,
    context: Annotated[
        RequestContext, Depends(require_permission(Permission.CATALOG_REQUEST_TYPE_LIST))
    ],
) -> RequestTypeResponse:
    _, result = await _service(request).request_type(context, request_type_id)
    return request_type_response(result)


@router.get(
    "/request-types/{request_type_id}/form",
    response_model=RequestFormResponse,
    responses=ERROR_RESPONSES,
)
async def get_request_form(
    request: Request,
    request_type_id: UUID,
    context: Annotated[RequestContext, Depends(require_permission(Permission.CATALOG_FORM_READ))],
) -> RequestFormResponse:
    return await _service(request).form(context, request_type_id)


def _project(value: ServiceProject) -> ProjectResponse:
    return ProjectResponse(
        id=value.project_id,
        code=value.project_key,
        name=value.project_name,
        description=value.description,
        default_timezone=value.default_timezone,
    )
