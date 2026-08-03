"""Task 10.2 authorization and tenant-isolation penetration regression."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-security-test"
PORT = "55461"
DATABASE = "security_model"
TENANT_A = UUID("20000000-0000-0000-0000-000000000001")
TENANT_B = UUID("20000000-0000-0000-0000-000000000002")
TICKET_A = UUID("85000000-0000-0000-0000-000000000001")
CUSTOMER = {"X-Developer-User": "DEV/customer"}
AGENT_A = {"X-Developer-User": "DEV/agent"}
INTRUDER = {"X-Developer-User": "PEN/intruder"}


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["POSTGRES_HOST_PORT"] = PORT
    return environment


def _compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *arguments],
        cwd=ROOT,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if check and result.returncode:
        pytest.fail(result.stdout + result.stderr)
    return result


def _psql(sql: str) -> str:
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
        DATABASE,
        "-Atqc",
        sql,
    ).stdout.strip()


def _migrate(*arguments: str) -> None:
    environment = _environment()
    environment["MIGRATION_DATABASE_URL"] = (
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}"
    )
    result = subprocess.run(
        ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", *arguments],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(scope="module", autouse=True)
def security_database() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            command = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                command += ["-v", "app_password=helpdesk"]
            _compose(*command, "-U", "postgres", "-d", DATABASE, "-f", file)
        _migrate("stamp")
        _migrate("upgrade")
        for file in ("/development/identity_personas.sql", "/development/catalogue.sql"):
            _compose(
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
                DATABASE,
                "-f",
                file,
            )
        _seed()
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _seed() -> None:
    _psql(
        f"""
        INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name,default_timezone)
        VALUES ('{TENANT_B}','PEN','Penetration Tenant','UTC')
        ON CONFLICT (tenant_id) DO NOTHING;

        INSERT INTO identity.app_user(
          user_id,tenant_id,external_subject,email_address,display_name,active_flag)
        VALUES ('22000000-0000-0000-0000-000000000021','{TENANT_B}','intruder',
          'intruder@example.invalid','Cross Tenant Analyst',true)
        ON CONFLICT (user_id) DO NOTHING;

        INSERT INTO identity.user_role(tenant_id,user_id,role_code,valid_from)
        VALUES ('{TENANT_B}','22000000-0000-0000-0000-000000000021','AGENT',
          '2025-01-01T00:00:00Z')
        ON CONFLICT DO NOTHING;

        INSERT INTO identity.support_group(
          support_group_id,tenant_id,group_code,group_name,assignment_method)
        VALUES ('23000000-0000-0000-0000-000000000021','{TENANT_B}','PEN_DESK',
          'Penetration Desk','GROUP_ONLY')
        ON CONFLICT (support_group_id) DO NOTHING;

        INSERT INTO identity.support_group_member(
          support_group_id,user_id,member_role,capacity_points)
        VALUES ('23000000-0000-0000-0000-000000000021',
          '22000000-0000-0000-0000-000000000021','AGENT',10)
        ON CONFLICT DO NOTHING;

        INSERT INTO itsm.ticket(
          ticket_id,tenant_id,project_id,request_type_id,request_type_version_id,
          work_type_id,workflow_version_id,status_id,summary,description,
          reporter_user_id,priority_code,channel_code,assignment_group_id,
          created_by,updated_by)
        SELECT '{TICKET_A}','{TENANT_A}',request_type.project_id,
          request_type.request_type_id,request_version.request_type_version_id,
          request_type.work_type_id,'32100000-0000-0000-0000-000000000001',
          '32200000-0000-0000-0000-000000000002','Tenant A confidential ticket',
          'Sensitive tenant A content','22000000-0000-0000-0000-000000000005','P3',
          'PORTAL','23000000-0000-0000-0000-000000000001',
          '22000000-0000-0000-0000-000000000005','22000000-0000-0000-0000-000000000005'
        FROM config.request_type request_type
        JOIN config.request_type_version request_version
          ON request_version.request_type_id=request_type.request_type_id
         AND request_version.version_status='PUBLISHED'
        WHERE request_type.request_type_id='33000000-0000-0000-0000-000000000001'
        ON CONFLICT (ticket_id) DO NOTHING;
        """
    )


def _client() -> TestClient:
    settings = Settings.model_validate(
        {
            "app_env": "test",
            "database_url": (f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}"),
            "redis_url": "redis://localhost:6379/15",
            "trusted_hosts": ["testserver"],
            "developer_identity_enabled": True,
        }
    )

    class _HealthyProbe:
        async def check(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    app = create_app(
        settings,
        resource_factory=lambda s: ApplicationResources(
            Database(s), _HealthyProbe(), _HealthyProbe(), _HealthyProbe()
        ),
    )
    return TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop})


@pytest.mark.integration
def test_cross_tenant_analyst_cannot_see_or_touch_other_tenant_tickets() -> None:
    with _client() as client:
        ticket_key = _psql(f"SELECT ticket_key FROM itsm.ticket WHERE ticket_id='{TICKET_A}'")
        listing = client.get("/api/v1/agent/tickets", headers=INTRUDER)
        assert listing.status_code == 200
        assert all(item["key"] != ticket_key for item in listing.json()["items"])
        direct = client.get(f"/api/v1/tickets/{ticket_key}", headers=INTRUDER)
        assert direct.status_code in (403, 404)
        timeline = client.get(f"/api/v1/agent/tickets/{ticket_key}/timeline", headers=INTRUDER)
        assert timeline.status_code == 404
        copilot = client.post(
            f"/api/v1/agent/tickets/{ticket_key}/copilot/analysis",
            headers=INTRUDER,
            json={},
        )
        assert copilot.status_code == 404
        comment = client.post(
            f"/api/v1/agent/tickets/{ticket_key}/comments",
            headers={**INTRUDER, "Idempotency-Key": "pen-comment-1"},
            json={"visibility": "INTERNAL", "body": "cross-tenant probe"},
        )
        assert comment.status_code == 404
        assert (
            _psql(f"SELECT count(*) FROM itsm.ticket_comment WHERE ticket_id='{TICKET_A}'") == "0"
        )


@pytest.mark.integration
def test_customer_cannot_reach_analyst_or_oversight_surfaces() -> None:
    with _client() as client:
        ticket_key = _psql(f"SELECT ticket_key FROM itsm.ticket WHERE ticket_id='{TICKET_A}'")
        for path in (
            "/api/v1/agent/queues",
            "/api/v1/agent/tickets",
            "/api/v1/admin/ai/copilot/metrics",
            "/api/v1/admin/ai/copilot/evaluation-dataset",
        ):
            response = client.get(path, headers=CUSTOMER)
            assert response.status_code == 403, path
        copilot = client.post(
            f"/api/v1/agent/tickets/{ticket_key}/copilot/analysis",
            headers=CUSTOMER,
            json={},
        )
        assert copilot.status_code == 403


@pytest.mark.integration
def test_unauthenticated_and_forged_identities_are_rejected() -> None:
    with _client() as client:
        anonymous = client.get("/api/v1/agent/tickets")
        assert anonymous.status_code == 401
        forged = client.get(
            "/api/v1/agent/tickets", headers={"X-Developer-User": "DEV/nonexistent"}
        )
        assert forged.status_code == 401
        cross_tenant_subject = client.get(
            "/api/v1/agent/tickets", headers={"X-Developer-User": "PEN/agent"}
        )
        assert cross_tenant_subject.status_code == 401
    assert (
        int(
            _psql(
                "SELECT count(*) FROM audit.security_event "
                "WHERE event_type LIKE 'DEVELOPER_IDENTITY%' AND decision_code='DENIED'"
            )
        )
        >= 1
    )


@pytest.mark.integration
def test_authorized_analyst_still_reads_own_tenant_ticket() -> None:
    with _client() as client:
        ticket_key = _psql(f"SELECT ticket_key FROM itsm.ticket WHERE ticket_id='{TICKET_A}'")
        timeline = client.get(f"/api/v1/agent/tickets/{ticket_key}/timeline", headers=AGENT_A)
        assert timeline.status_code == 200
        listing = client.get("/api/v1/agent/tickets", headers=AGENT_A)
        assert listing.status_code == 200
        assert any(item["key"] == ticket_key for item in listing.json()["items"])
