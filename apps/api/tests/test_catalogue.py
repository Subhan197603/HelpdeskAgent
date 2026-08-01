"""Catalogue API contract, authorization, and safe-rule unit tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from apps.api.app.catalog.models import (
    RequestTypeSummary,
    RequestTypeVersion,
    ServiceNode,
    ServiceProject,
    WorkType,
)
from apps.api.app.catalog.rules import parse_conditional_rule
from apps.api.app.catalog.schemas import (
    FieldValidationResponse,
    FormFieldResponse,
    ProjectResponse,
    RequestFormResponse,
    WorkTypeResponse,
)
from apps.api.app.core.context import RequestContext
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

from .conftest import FakeProbe, make_test_settings
from .test_identity import FakeDeveloperIdentityService, identity

TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("30000000-0000-0000-0000-000000000002")
REQUEST_TYPE_ID = UUID("33000000-0000-0000-0000-000000000001")
VERSION_ID = UUID("33100000-0000-0000-0000-000000000001")
EVALUATED_AT = datetime(2026, 8, 1, tzinfo=UTC)


class FakeCatalogueService:
    def __init__(self) -> None:
        self.project_value = ServiceProject(
            PROJECT_ID, "ERP", "Oracle Fusion ERP Support", "ERP support", "Europe/London"
        )
        self.request_type_value = RequestTypeSummary(
            REQUEST_TYPE_ID,
            PROJECT_ID,
            "REPORT_FUSION_ERROR",
            "Report an Oracle Fusion error",
            "Report an issue affecting Oracle Fusion.",
            "Oracle Fusion",
            10,
            WorkType("INCIDENT", "Incident"),
            RequestTypeVersion(VERSION_ID, 1, datetime(2025, 1, 1, tzinfo=UTC), None, 1),
        )

    async def list_projects(
        self, context: RequestContext, *, limit: int, offset: int
    ) -> list[ServiceProject]:
        return [self.project_value]

    async def project(self, context: RequestContext, project_id: UUID) -> ServiceProject:
        return self.project_value

    async def list_services(
        self,
        context: RequestContext,
        project_id: UUID,
        parent_id: UUID | None,
        *,
        limit: int,
        offset: int,
    ) -> list[ServiceNode]:
        return [
            ServiceNode(
                UUID("31000000-0000-0000-0000-000000000002"),
                None,
                "ORACLE_FUSION",
                "Oracle Fusion Cloud Applications",
                "SERVICE_FAMILY",
                20,
                "HIGH",
                "INTERNAL",
            )
        ]

    async def list_request_types(
        self,
        context: RequestContext,
        project_id: UUID,
        *,
        limit: int,
        offset: int,
    ) -> tuple[datetime, list[RequestTypeSummary]]:
        return EVALUATED_AT, [self.request_type_value]

    async def request_type(
        self, context: RequestContext, request_type_id: UUID
    ) -> tuple[datetime, RequestTypeSummary]:
        return EVALUATED_AT, self.request_type_value

    async def form(self, context: RequestContext, request_type_id: UUID) -> RequestFormResponse:
        return RequestFormResponse(
            request_type_id=REQUEST_TYPE_ID,
            request_type_version_id=VERSION_ID,
            version_number=1,
            code="REPORT_FUSION_ERROR",
            name="Report an Oracle Fusion error",
            description="Report an issue affecting Oracle Fusion.",
            evaluated_at=EVALUATED_AT,
            effective_from=datetime(2025, 1, 1, tzinfo=UTC),
            effective_to=None,
            project=ProjectResponse(
                id=PROJECT_ID,
                code="ERP",
                name="Oracle Fusion ERP Support",
                description="ERP support",
                default_timezone="Europe/London",
            ),
            work_type=WorkTypeResponse(code="INCIDENT", name="Incident"),
            fields=[
                FormFieldResponse(
                    field_id=UUID("34000000-0000-0000-0000-000000000001"),
                    field_code="summary",
                    data_type="TEXT",
                    label="Brief summary",
                    description=None,
                    required=True,
                    display_order=10,
                    validation=FieldValidationResponse(minimum_length=5, maximum_length=200),
                    condition=None,
                    options=[],
                )
            ],
        )


@contextmanager
def catalogue_client(
    identity_service: FakeDeveloperIdentityService | None = None,
) -> Iterator[TestClient]:
    resources = ApplicationResources(FakeProbe(), FakeProbe(), FakeProbe(), FakeProbe())
    app = create_app(
        make_test_settings(developer_identity_enabled=True),
        resource_factory=lambda _: resources,
    )
    app.state.developer_identity_service = identity_service or FakeDeveloperIdentityService()
    app.state.catalogue_service = FakeCatalogueService()
    with TestClient(app) as client:
        yield client


def test_catalogue_requires_authentication() -> None:
    with catalogue_client() as client:
        response = client.get("/api/v1/catalog/projects")
    assert response.status_code == 401


def test_roleless_or_unknown_identity_is_denied_and_audited() -> None:
    service = FakeDeveloperIdentityService(identity(roles=frozenset()))
    with catalogue_client(service) as client:
        response = client.get(
            "/api/v1/catalog/projects", headers={"X-Developer-User": "DEV/roleless"}
        )
    assert response.status_code == 403
    assert service.events[-1].event_type == "AUTHORIZATION_DENIED"


def test_catalogue_endpoints_return_stable_versioned_contracts() -> None:
    headers = {"X-Developer-User": "DEV/customer"}
    paths = [
        "/api/v1/catalog/projects",
        f"/api/v1/catalog/projects/{PROJECT_ID}",
        f"/api/v1/catalog/projects/{PROJECT_ID}/services",
        f"/api/v1/catalog/projects/{PROJECT_ID}/request-types",
        f"/api/v1/catalog/request-types/{REQUEST_TYPE_ID}",
        f"/api/v1/catalog/request-types/{REQUEST_TYPE_ID}/form",
    ]
    with catalogue_client() as client:
        responses = [client.get(path, headers=headers) for path in paths]
    assert all(response.status_code == 200 for response in responses)
    form = responses[-1].json()
    assert form["request_type_version_id"] == str(VERSION_ID)
    assert form["fields"][0]["validation"] == {
        "minimum_length": 5,
        "maximum_length": 200,
        "minimum": None,
        "maximum": None,
        "minimum_items": None,
        "maximum_items": None,
        "pattern": None,
    }


def test_catalogue_rejects_pagination_and_scope_injection() -> None:
    with catalogue_client() as client:
        invalid_page = client.get(
            "/api/v1/catalog/projects?limit=101",
            headers={"X-Developer-User": "DEV/customer"},
        )
        injected = client.get(
            "/api/v1/catalog/projects",
            headers={
                "X-Developer-User": "DEV/customer",
                "X-Tenant-ID": "20000000-0000-0000-0000-000000000002",
            },
        )
    assert invalid_page.status_code == 422
    assert injected.status_code == 401


def test_conditional_rule_language_is_data_only_and_allowlisted() -> None:
    rule = parse_conditional_rule(
        {"all": [{"field": "environment", "operator": "equals", "value": "PROD"}]}
    )
    assert rule is not None and rule.all is not None
    assert rule.all[0].field == "environment"
    with pytest.raises(PydanticValidationError):
        parse_conditional_rule(
            {"all": [{"field": "environment", "operator": "eval", "value": "alert(1)"}]}
        )
    with pytest.raises(PydanticValidationError):
        parse_conditional_rule({"expression": "{{ dangerous_template }}"})


def test_openapi_documents_catalogue_contract_and_problem_responses() -> None:
    with catalogue_client() as client:
        contract = client.get("/openapi.json").json()
    form_operation = contract["paths"]["/api/v1/catalog/request-types/{request_type_id}/form"][
        "get"
    ]
    assert form_operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert form_operation["responses"]["401"]["content"]["application/json"]["schema"]
    assert form_operation["security"] == [{"HTTPBearer": []}]
    assert "RequestFormResponse" in contract["components"]["schemas"]
