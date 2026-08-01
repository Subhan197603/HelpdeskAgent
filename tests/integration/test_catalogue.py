"""PostgreSQL integration tests for catalogue publication, forms, tenancy, and RLS."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PROJECT = "fusion-helpdesk-catalogue-test"
POSTGRES_PORT = "55446"
DATABASES = ("catalogue_api", "catalogue_rls")
DEV_PROJECT_ID = "30000000-0000-0000-0000-000000000002"
BASE_REQUEST_TYPE_ID = "33000000-0000-0000-0000-000000000001"
BASE_VERSION_ID = "33100000-0000-0000-0000-000000000001"


class HealthyProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


@pytest.fixture(scope="module")
def anyio_backend() -> tuple[str, dict[str, object]]:
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["POSTGRES_HOST_PORT"] = POSTGRES_PORT
    return environment


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["docker", "compose", "--project-name", COMPOSE_PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and completed.returncode != 0:
        pytest.fail(
            f"Docker Compose failed ({completed.returncode}).\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return completed


def _psql(database: str, *arguments: str) -> str:
    return _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        database,
        *arguments,
    ).stdout.strip()


def _admin_url(database: str) -> str:
    return f"postgresql+psycopg://postgres:postgres@127.0.0.1:{POSTGRES_PORT}/{database}"


def _app_url(database: str) -> str:
    return f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{POSTGRES_PORT}/{database}"


def _migrate(database: str) -> None:
    environment = os.environ.copy()
    environment.update({"APP_ENV": "integration", "MIGRATION_DATABASE_URL": _admin_url(database)})
    for command in ("stamp", "upgrade"):
        completed = subprocess.run(
            ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", command],
            cwd=ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0:
            pytest.fail(completed.stdout + completed.stderr)


@pytest.fixture(scope="module", autouse=True)
def catalogue_databases() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        for database in DATABASES:
            _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", database)
            _psql(database, "-f", "/baseline/install_all.sql")
            _psql(
                database,
                "-v",
                "app_password=helpdesk",
                "-f",
                "/runtime-config/configure_local_runtime.sql",
            )
            _migrate(database)
            _psql(database, "-f", "/development/identity_personas.sql")
            _psql(database, "-f", "/development/catalogue.sql")
        _install_edge_cases()
        _psql("catalogue_rls", "-f", "/baseline/09_optional_rls.sql")
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _install_edge_cases() -> None:
    _psql(
        "catalogue_api",
        "-c",
        """
        INSERT INTO identity.tenant(tenant_id, tenant_code, tenant_name)
        VALUES ('20000000-0000-0000-0000-000000000002', 'OTHER', 'Other Tenant');
        INSERT INTO identity.app_user(
            user_id, tenant_id, external_subject, email_address, display_name
        ) VALUES (
            '22000000-0000-0000-0000-000000000020',
            '20000000-0000-0000-0000-000000000002',
            'customer', 'other@example.invalid', 'Other Customer'
        );
        INSERT INTO identity.user_role(tenant_id, user_id, role_code, valid_from)
        VALUES (
            '20000000-0000-0000-0000-000000000002',
            '22000000-0000-0000-0000-000000000020',
            'CUSTOMER', '2025-01-01T00:00:00Z'
        );
        INSERT INTO config.service_project(
            project_id, tenant_id, project_key, project_name
        ) VALUES (
            '30000000-0000-0000-0000-000000000020',
            '20000000-0000-0000-0000-000000000002', 'OTHER', 'Other Project'
        );
        INSERT INTO config.service_project(
            project_id, tenant_id, project_key, project_name, active_flag
        ) VALUES (
            '30000000-0000-0000-0000-000000000007',
            '20000000-0000-0000-0000-000000000001',
            'OFF', 'Inactive Project', false
        ), (
            '30000000-0000-0000-0000-000000000008',
            '20000000-0000-0000-0000-000000000001',
            'OVR', 'Overlapping Configuration Project', true
        );

        INSERT INTO config.request_type_version(
            request_type_version_id, request_type_id, version_number, version_status,
            effective_from, effective_to, published_at
        ) VALUES
        ('33100000-0000-0000-0000-000000000101',
         '33000000-0000-0000-0000-000000000001',2,'DRAFT','2025-01-01T00:00:00Z',NULL,NULL),
        ('33100000-0000-0000-0000-000000000102',
         '33000000-0000-0000-0000-000000000001',3,'PUBLISHED','2099-01-01T00:00:00Z',NULL,'2025-01-01T00:00:00Z'),
        ('33100000-0000-0000-0000-000000000103',
         '33000000-0000-0000-0000-000000000001',4,'PUBLISHED','2024-01-01T00:00:00Z','2024-12-31T00:00:00Z','2024-01-01T00:00:00Z');

        INSERT INTO config.request_type(
            request_type_id, tenant_id, project_id, work_type_id, workflow_id,
            request_type_code, request_type_name, active_flag
        )
        SELECT fixture.request_type_id,
               '20000000-0000-0000-0000-000000000001', fixture.project_id,
               work_type.work_type_id, '32000000-0000-0000-0000-000000000001',
               fixture.code, fixture.name, fixture.active_flag
        FROM (VALUES
          ('35000000-0000-0000-0000-000000000001'::uuid,
           '30000000-0000-0000-0000-000000000003'::uuid,
           'ONLY_DRAFT','Only draft',true),
          ('35000000-0000-0000-0000-000000000002'::uuid,
           '30000000-0000-0000-0000-000000000004'::uuid,
           'RETIRED_TYPE','Retired type',false),
          ('35000000-0000-0000-0000-000000000003'::uuid,
           '30000000-0000-0000-0000-000000000008'::uuid,
           'OVERLAP','Overlapping published versions',true),
          ('35000000-0000-0000-0000-000000000004'::uuid,
           '30000000-0000-0000-0000-000000000002'::uuid,
           'HIDDEN','Employee-hidden request',true)
        ) AS fixture(request_type_id,project_id,code,name,active_flag)
        JOIN config.work_type AS work_type
          ON work_type.work_type_code = 'QUESTION' AND work_type.tenant_id IS NULL;
        UPDATE config.request_type
        SET employee_visible_flag = false
        WHERE request_type_id = '35000000-0000-0000-0000-000000000004';

        INSERT INTO config.request_type_version(
            request_type_version_id, request_type_id, version_number, version_status,
            effective_from, effective_to, published_at, retired_at
        ) VALUES
        ('35100000-0000-0000-0000-000000000001','35000000-0000-0000-0000-000000000001',1,'DRAFT','2025-01-01T00:00:00Z',NULL,NULL,NULL),
        ('35100000-0000-0000-0000-000000000002','35000000-0000-0000-0000-000000000002',1,'RETIRED','2025-01-01T00:00:00Z',NULL,'2025-01-01T00:00:00Z','2026-01-01T00:00:00Z'),
        ('35100000-0000-0000-0000-000000000003','35000000-0000-0000-0000-000000000003',1,'PUBLISHED','2025-01-01T00:00:00Z',NULL,'2025-01-01T00:00:00Z',NULL),
        ('35100000-0000-0000-0000-000000000004','35000000-0000-0000-0000-000000000003',2,'PUBLISHED','2025-06-01T00:00:00Z',NULL,'2025-06-01T00:00:00Z',NULL),
        ('35100000-0000-0000-0000-000000000005','35000000-0000-0000-0000-000000000004',1,'PUBLISHED','2025-01-01T00:00:00Z',NULL,'2025-01-01T00:00:00Z',NULL);
        """,
    )


def _settings(database: str, *, rls_enabled: bool = False) -> Settings:
    return Settings.model_validate(
        {
            "app_env": "integration",
            "database_url": _app_url(database),
            "developer_identity_enabled": True,
            "rls_enabled": rls_enabled,
            "object_storage_enabled": False,
            "trusted_hosts": ["testserver"],
        }
    )


def _resources(settings: Settings) -> ApplicationResources:
    return ApplicationResources(Database(settings), HealthyProbe(), HealthyProbe(), HealthyProbe())


@pytest.fixture
def catalogue_client() -> Iterator[TestClient]:
    settings = _settings("catalogue_api")
    app = create_app(settings, resource_factory=_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        yield client


def _get(client: TestClient, path: str, selector: str = "DEV/customer") -> httpx.Response:
    return cast("httpx.Response", client.get(path, headers={"X-Developer-User": selector}))


@pytest.mark.integration
def test_customer_lists_only_active_tenant_projects(catalogue_client: TestClient) -> None:
    response = _get(catalogue_client, "/api/v1/catalog/projects")
    assert response.status_code == 200
    codes = [item["code"] for item in response.json()["items"]]
    assert codes == ["BI", "ERP", "HCM", "IT", "OVR", "SCM", "SEC"]
    assert "OFF" not in codes
    assert "OTHER" not in codes


@pytest.mark.integration
def test_cross_tenant_project_is_non_disclosing(catalogue_client: TestClient) -> None:
    response = _get(
        catalogue_client,
        "/api/v1/catalog/projects/30000000-0000-0000-0000-000000000020",
    )
    assert response.status_code == 404
    assert "Other Project" not in response.text


@pytest.mark.integration
def test_service_hierarchy_is_active_tenant_scoped_and_deterministic(
    catalogue_client: TestClient,
) -> None:
    roots = _get(
        catalogue_client,
        f"/api/v1/catalog/projects/{DEV_PROJECT_ID}/services",
    )
    assert roots.status_code == 200
    assert [item["code"] for item in roots.json()["items"]] == [
        "CORPORATE_IT",
        "ORACLE_FUSION",
    ]
    children = _get(
        catalogue_client,
        f"/api/v1/catalog/projects/{DEV_PROJECT_ID}/services"
        "?parent_id=31000000-0000-0000-0000-000000000002",
    )
    assert [item["code"] for item in children.json()["items"]] == ["ERP", "HCM"]


@pytest.mark.integration
def test_request_types_select_only_current_published_version(
    catalogue_client: TestClient,
) -> None:
    response = _get(
        catalogue_client,
        f"/api/v1/catalog/projects/{DEV_PROJECT_ID}/request-types",
    )
    assert response.status_code == 200
    items = response.json()["items"]
    target = next(item for item in items if item["id"] == BASE_REQUEST_TYPE_ID)
    assert target["version_id"] == BASE_VERSION_ID
    assert target["version_number"] == 1
    assert all(item["code"] != "HIDDEN" for item in items)


@pytest.mark.integration
def test_draft_only_and_retired_request_types_are_hidden(catalogue_client: TestClient) -> None:
    draft_list = _get(
        catalogue_client,
        "/api/v1/catalog/projects/30000000-0000-0000-0000-000000000003/request-types",
    )
    retired_list = _get(
        catalogue_client,
        "/api/v1/catalog/projects/30000000-0000-0000-0000-000000000004/request-types",
    )
    draft_detail = _get(
        catalogue_client,
        "/api/v1/catalog/request-types/35000000-0000-0000-0000-000000000001",
    )
    retired_detail = _get(
        catalogue_client,
        "/api/v1/catalog/request-types/35000000-0000-0000-0000-000000000002",
    )
    assert draft_list.json()["items"] == []
    assert retired_list.json()["items"] == []
    assert draft_detail.status_code == 409
    assert retired_detail.status_code == 404


@pytest.mark.integration
def test_overlapping_published_versions_fail_safely(catalogue_client: TestClient) -> None:
    response = _get(
        catalogue_client,
        "/api/v1/catalog/projects/30000000-0000-0000-0000-000000000008/request-types",
    )
    assert response.status_code == 409
    assert response.json()["type"].endswith("catalogue_configuration_conflict")
    assert "35100000" not in response.text


@pytest.mark.integration
def test_form_is_versioned_ordered_and_hides_inactive_options(
    catalogue_client: TestClient,
) -> None:
    response = _get(
        catalogue_client,
        f"/api/v1/catalog/request-types/{BASE_REQUEST_TYPE_ID}/form",
    )
    assert response.status_code == 200
    form = response.json()
    assert form["request_type_version_id"] == BASE_VERSION_ID
    assert [field["field_code"] for field in form["fields"]] == [
        "summary",
        "description",
        "environment",
    ]
    assert [field["display_order"] for field in form["fields"]] == [10, 20, 30]
    assert all(field["required"] for field in form["fields"])
    assert form["fields"][0]["validation"]["minimum_length"] == 5
    assert [option["value"] for option in form["fields"][2]["options"]] == ["PROD", "TEST"]
    assert form["fields"][2]["condition"]["all"][0]["operator"] == "is_not_empty"


@pytest.mark.integration
def test_published_form_components_are_database_immutable() -> None:
    attempted_update = _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        "-d",
        "catalogue_api",
        "-c",
        "UPDATE config.custom_field SET field_name = 'Changed' "
        "WHERE custom_field_id = '34000000-0000-0000-0000-000000000001'",
        check=False,
    )
    assert attempted_update.returncode != 0
    assert "Published request-form configuration is immutable" in attempted_update.stderr


@pytest.mark.integration
def test_unknown_request_type_returns_safe_404(catalogue_client: TestClient) -> None:
    response = _get(
        catalogue_client,
        "/api/v1/catalog/request-types/ffffffff-ffff-ffff-ffff-ffffffffffff/form",
    )
    assert response.status_code == 404
    assert "SELECT" not in response.text
    assert "config." not in response.text


@pytest.mark.integration
@pytest.mark.anyio
async def test_concurrent_catalogue_requests_do_not_leak_tenants() -> None:
    settings = _settings("catalogue_api")
    app = create_app(settings, resource_factory=_resources)
    transport = httpx.ASGITransport(app=app)
    selectors = ["DEV/customer", "OTHER/customer"] * 6
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        responses = await asyncio.gather(
            *(
                client.get(
                    "/api/v1/catalog/projects",
                    headers={"X-Developer-User": selector},
                )
                for selector in selectors
            )
        )
    await app.state.resources.close()
    codes = [[item["code"] for item in response.json()["items"]] for response in responses]
    assert all("OTHER" not in item for item in codes[::2])
    assert all(item == ["OTHER"] for item in codes[1::2])


@pytest.mark.integration
def test_catalogue_operates_with_optional_rls() -> None:
    settings = _settings("catalogue_rls", rls_enabled=True)
    app = create_app(settings, resource_factory=_resources)
    with TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop}) as client:
        projects = _get(client, "/api/v1/catalog/projects")
        form = _get(client, f"/api/v1/catalog/request-types/{BASE_REQUEST_TYPE_ID}/form")
    assert projects.status_code == 200
    assert form.status_code == 200
    assert form.json()["request_type_version_id"] == BASE_VERSION_ID


def test_catalogue_fixture_is_not_in_production_baseline() -> None:
    installer = (ROOT / "database/baseline/fusion_helpdesk_postgres/sql/install_all.sql").read_text(
        encoding="utf-8"
    )
    assert "catalogue.sql" not in installer
    assert "30000000-0000-0000-0000-000000000001" not in installer
