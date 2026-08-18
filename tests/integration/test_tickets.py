"""Real PostgreSQL tests for the draft-to-ticket transactional boundary."""

import asyncio
import hashlib
import logging
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.app.approvals.repository import ApprovalRepository
from apps.api.app.approvals.service import ApprovalEngine
from apps.api.app.attachments.clamav import ScannerError, ScanResult
from apps.api.app.attachments.service import AttachmentService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ConcurrencyError
from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app
from apps.api.app.routing.schemas import AssignmentResponse, RouteCommand
from apps.api.app.tickets.repository import TicketRepository
from apps.api.app.workflows.schemas import TransitionCommand, TransitionResponse

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-ticket-test"
PORT = "55447"
DATABASE = "ticket_api"
REQUEST_TYPE = "33000000-0000-0000-0000-000000000001"


class HealthyProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


def _env() -> dict[str, str]:
    result = os.environ.copy()
    result["POSTGRES_HOST_PORT"] = PORT
    return result


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", "compose", "--project-name", PROJECT, *args],
        cwd=ROOT,
        env=_env(),
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


@pytest.fixture(scope="module", autouse=True)
def ticket_database() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            args = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                args += ["-v", "app_password=helpdesk"]
            _compose(*args, "-U", "postgres", "-d", DATABASE, "-f", file)
        environment = os.environ.copy()
        environment["MIGRATION_DATABASE_URL"] = (
            f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}"
        )
        for command in ("stamp", "upgrade"):
            result = subprocess.run(
                ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", command],
                cwd=ROOT,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, result.stdout + result.stderr
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
            "/development/identity_personas.sql",
        )
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
            "/development/catalogue.sql",
        )
        _psql(
            """
            INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name)
            VALUES ('20000000-0000-0000-0000-000000000099','OTHER','Other Tenant');
            INSERT INTO identity.app_user(
              user_id,tenant_id,external_subject,email_address,display_name)
            VALUES
              ('22000000-0000-0000-0000-000000000099',
               '20000000-0000-0000-0000-000000000099','customer',
               'other-customer@example.invalid','Other Customer'),
              ('22000000-0000-0000-0000-000000000098',
               '20000000-0000-0000-0000-000000000099','agent',
               'other-agent@example.invalid','Other Agent');
            INSERT INTO identity.user_role(tenant_id,user_id,role_code,valid_from)
            VALUES
              ('20000000-0000-0000-0000-000000000099',
               '22000000-0000-0000-0000-000000000099','CUSTOMER',now()),
              ('20000000-0000-0000-0000-000000000099',
               '22000000-0000-0000-0000-000000000098','AGENT',now());
            INSERT INTO config.request_type(
              request_type_id,tenant_id,project_id,work_type_id,workflow_id,
              request_type_code,request_type_name)
            SELECT '33000000-0000-0000-0000-000000000099',
              '20000000-0000-0000-0000-000000000001',
              '30000000-0000-0000-0000-000000000002',work_type_id,
              '32000000-0000-0000-0000-000000000001','UNPUBLISHED_TEST',
              'Unpublished test request'
            FROM config.work_type WHERE work_type_code='INCIDENT';
            INSERT INTO config.request_type_version(
              request_type_version_id,request_type_id,version_number,version_status)
            VALUES ('33100000-0000-0000-0000-000000000099',
              '33000000-0000-0000-0000-000000000099',1,'DRAFT');
            """
        )
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _settings() -> Settings:
    return Settings.model_validate(
        {
            "app_env": "integration",
            "database_url": f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}",
            "developer_identity_enabled": True,
            "object_storage_enabled": False,
            "trusted_hosts": ["testserver"],
        }
    )


def _resources(settings: Settings) -> ApplicationResources:
    return ApplicationResources(Database(settings), HealthyProbe(), HealthyProbe(), HealthyProbe())


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(
        create_app(_settings(), resource_factory=_resources),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as value:
        yield value


def _body() -> dict[str, object]:
    return {
        "request_type_id": REQUEST_TYPE,
        "summary": "  Fusion   invoice failure ",
        "description": "Invoice validation fails with a reproducible error.",
        "impact": "LIMITED",
        "urgency": "NORMAL",
        "custom_fields": [{"field_code": "environment", "value": "PROD"}],
    }


def _draft(client: TestClient, body: dict[str, object] | None = None) -> dict[str, object]:
    headers = {"X-Developer-User": "DEV/customer"}
    created = client.post("/api/v1/ticket-drafts", headers=headers, json=body or _body())
    assert created.status_code == 201
    value = created.json()
    validated = client.post(
        f"/api/v1/ticket-drafts/{value['id']}/validate",
        headers=headers,
        json={"row_version": value["row_version"]},
    )
    assert validated.status_code == 200
    return cast("dict[str, object]", validated.json()["draft"])


def _access_ticket(client: TestClient, prefix: str) -> dict[str, object]:
    draft = _draft(
        client,
        {
            "request_type_id": "33000000-0000-0000-0000-000000000002",
            "summary": "Request Fusion access",
            "description": "Access is needed for the approved finance responsibilities.",
            "impact": "LIMITED",
            "urgency": "NORMAL",
            "custom_fields": [],
        },
    )
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"{prefix}-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    assert submitted.status_code == 201
    return cast("dict[str, object]", submitted.json())


def _request_access_approval(
    client: TestClient, prefix: str
) -> tuple[dict[str, object], dict[str, object]]:
    ticket = _access_ticket(client, prefix)
    requested = client.post(
        f"/api/v1/agent/tickets/{ticket['key']}/transitions",
        headers={
            "X-Developer-User": "DEV/agent",
            "Idempotency-Key": f"{prefix}-request-{uuid4()}",
        },
        json={"transition_code": "REQUEST_APPROVAL", "row_version": ticket["row_version"]},
    )
    assert requested.status_code == 200
    listing = client.get("/api/v1/my/approvals", headers={"X-Developer-User": "DEV/approver"})
    approval = next(item for item in listing.json()["items"] if item["ticket_key"] == ticket["key"])
    return ticket, cast("dict[str, object]", approval)


@pytest.mark.integration
def test_draft_auth_version_validation_and_ownership(client: TestClient) -> None:
    assert client.post("/api/v1/ticket-drafts", json=_body()).status_code == 401
    unknown = _body()
    unknown["custom_fields"] = [{"field_code": "injected", "value": "x"}]
    assert (
        client.post(
            "/api/v1/ticket-drafts", headers={"X-Developer-User": "DEV/customer"}, json=unknown
        ).status_code
        == 422
    )
    draft = _draft(client)
    assert draft["request_type_version_id"] == "33100000-0000-0000-0000-000000000001"
    assert (
        client.get(
            f"/api/v1/ticket-drafts/{draft['id']}", headers={"X-Developer-User": "DEV/agent"}
        ).status_code
        == 404
    )
    assert (
        _psql(
            "SELECT count(*) FROM audit.audit_event "
            f"WHERE resource_id='{draft['id']}' AND action_code='TICKET_DRAFT_ACCESS_DENIED' "
            "AND actor_id='22000000-0000-0000-0000-000000000004' AND outcome_code='DENIED'"
        )
        == "1"
    )
    stale = client.patch(
        f"/api/v1/ticket-drafts/{draft['id']}",
        headers={"X-Developer-User": "DEV/customer"},
        json={"row_version": 1, "summary": "stale"},
    )
    assert stale.status_code == 409
    assert (
        client.get(
            f"/api/v1/ticket-drafts/{draft['id']}",
            headers={"X-Developer-User": "OTHER/customer"},
        ).status_code
        == 404
    )


@pytest.mark.integration
def test_requested_for_requires_explicit_permission(client: TestClient) -> None:
    requested_for = "22000000-0000-0000-0000-000000000004"
    body = {**_body(), "requested_for_user_id": requested_for}
    denied = client.post(
        "/api/v1/ticket-drafts", headers={"X-Developer-User": "DEV/customer"}, json=body
    )
    assert denied.status_code == 403
    allowed = client.post(
        "/api/v1/ticket-drafts",
        headers={"X-Developer-User": "DEV/platform-admin"},
        json=body,
    )
    assert allowed.status_code == 201
    assert allowed.json()["requested_for_user_id"] == requested_for


@pytest.mark.integration
def test_sensitive_ticket_content_is_not_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    marker = "PRIVATE-DESCRIPTION-MARKER-93A7"
    body = {**_body(), "description": marker}
    caplog.set_level(logging.INFO)
    response = client.post(
        "/api/v1/ticket-drafts",
        headers={"X-Developer-User": "DEV/customer"},
        json=body,
    )
    assert response.status_code == 201
    assert marker not in caplog.text


@pytest.mark.integration
def test_unpublished_form_and_invalid_priority_configuration_fail_closed(
    client: TestClient,
) -> None:
    unpublished = {**_body(), "request_type_id": "33000000-0000-0000-0000-000000000099"}
    assert (
        client.post(
            "/api/v1/ticket-drafts",
            headers={"X-Developer-User": "DEV/customer"},
            json=unpublished,
        ).status_code
        == 404
    )

    _psql(
        "UPDATE config.priority_matrix SET approval_status='RETIRED' "
        "WHERE tenant_id IS NULL AND project_id IS NULL AND service_node_id IS NULL "
        "AND impact_code='LIMITED' AND urgency_code='NORMAL'"
    )
    try:
        missing = client.post(
            "/api/v1/ticket-drafts",
            headers={"X-Developer-User": "DEV/customer"},
            json=_body(),
        )
        assert missing.status_code == 409
    finally:
        _psql(
            "UPDATE config.priority_matrix SET approval_status='APPROVED' "
            "WHERE tenant_id IS NULL AND project_id IS NULL AND service_node_id IS NULL "
            "AND impact_code='LIMITED' AND urgency_code='NORMAL'"
        )

    _psql(
        """
        INSERT INTO config.priority_matrix(
          priority_matrix_id,tenant_id,project_id,impact_code,urgency_code,
          priority_code,evaluation_order,effective_from)
        VALUES
          ('35000000-0000-0000-0000-000000000098',
           '20000000-0000-0000-0000-000000000001',
           '30000000-0000-0000-0000-000000000002','LIMITED','NORMAL','P3',10,
           '2024-01-01T00:00:00Z'),
          ('35000000-0000-0000-0000-000000000099',
           '20000000-0000-0000-0000-000000000001',
           '30000000-0000-0000-0000-000000000002','LIMITED','NORMAL','P4',10,
           '2025-01-01T00:00:00Z')
        """
    )
    try:
        overlapping = client.post(
            "/api/v1/ticket-drafts",
            headers={"X-Developer-User": "DEV/customer"},
            json=_body(),
        )
        assert overlapping.status_code == 409
    finally:
        _psql(
            "DELETE FROM config.priority_matrix WHERE priority_matrix_id IN "
            "('35000000-0000-0000-0000-000000000098',"
            "'35000000-0000-0000-0000-000000000099')"
        )


@pytest.mark.integration
def test_submission_is_atomic_idempotent_and_customer_safe(client: TestClient) -> None:
    draft = _draft(client)
    assert (
        _psql(
            "SELECT (submitted_ticket_id IS NULL)::int FROM itsm.ticket_draft "
            f"WHERE draft_id='{draft['id']}'"
        )
        == "1"
    )
    key = f"submit-{uuid4()}"
    headers = {"X-Developer-User": "DEV/customer", "Idempotency-Key": key}
    path = f"/api/v1/ticket-drafts/{draft['id']}/submit"
    submitted = client.post(path, headers=headers, json={"row_version": draft["row_version"]})
    assert submitted.status_code == 201
    replay = client.post(path, headers=headers, json={"row_version": draft["row_version"]})
    assert replay.status_code == 200 and replay.json()["id"] == submitted.json()["id"]
    conflict = client.post(
        path,
        headers={**headers, "Idempotency-Key": key},
        json={"row_version": int(cast(int, draft["row_version"])) + 1},
    )
    assert conflict.status_code == 409
    ticket_key = submitted.json()["key"]
    assert (
        client.get(
            f"/api/v1/tickets/{ticket_key}", headers={"X-Developer-User": "DEV/customer"}
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/tickets/{ticket_key}", headers={"X-Developer-User": "DEV/agent"}
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/tickets/{ticket_key}",
            headers={"X-Developer-User": "OTHER/customer"},
        ).status_code
        == 404
    )
    ticket_id = submitted.json()["id"]
    assert _psql(f"SELECT count(*) FROM itsm.ticket WHERE ticket_id='{ticket_id}'") == "1"
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_event "
            f"WHERE ticket_id='{ticket_id}' AND event_type='TICKET_CREATED'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT (new_values_json IS NULL AND event_data_json ? 'correlation_id')::int "
            f"FROM itsm.ticket_event WHERE ticket_id='{ticket_id}' "
            "AND event_type='TICKET_CREATED'"
        )
        == "1"
    )
    assert (
        _psql(f"SELECT count(*) FROM integration.outbox_event WHERE aggregate_id='{ticket_id}'")
        == "3"
    )
    assert (
        _psql(f"SELECT count(*) FROM itsm.ticket_custom_value WHERE ticket_id='{ticket_id}'") == "3"
    )
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_custom_value "
            f"WHERE ticket_id='{ticket_id}' "
            "AND (text_value IS NOT NULL OR option_value IS NOT NULL)"
        )
        == "3"
    )
    assert (
        _psql(
            "SELECT (ticket.request_type_version_id=draft.request_type_version_id "
            "AND ticket.priority_matrix_id=draft.priority_matrix_id "
            "AND status.initial_flag)::int FROM itsm.ticket ticket "
            "JOIN itsm.ticket_draft draft ON draft.submitted_ticket_id=ticket.ticket_id "
            "JOIN config.workflow_status status ON status.status_id=ticket.status_id "
            f"WHERE ticket.ticket_id='{ticket_id}'"
        )
        == "1"
    )
    submitted_draft = client.get(
        f"/api/v1/ticket-drafts/{draft['id']}", headers={"X-Developer-User": "DEV/customer"}
    ).json()
    immutable = client.patch(
        f"/api/v1/ticket-drafts/{draft['id']}",
        headers={"X-Developer-User": "DEV/customer"},
        json={"row_version": submitted_draft["row_version"], "summary": "must not change"},
    )
    assert immutable.status_code == 409
    assert (
        _psql(
            "SELECT count(*) FROM audit.audit_event "
            f"WHERE resource_id='{draft['id']}' AND action_code='TICKET_SUBMITTED'"
        )
        == "1"
    )
    assert (
        _psql("SELECT relrowsecurity::int FROM pg_class WHERE oid='itsm.ticket_draft'::regclass")
        == "1"
    )


@pytest.mark.integration
def test_parallel_submissions_allocate_unique_project_keys(client: TestClient) -> None:
    drafts = [_draft(client) for _ in range(4)]

    async def submit_all() -> list[httpx.Response]:
        app = create_app(_settings(), resource_factory=_resources)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as async_client:
            responses = await asyncio.gather(
                *(
                    async_client.post(
                        f"/api/v1/ticket-drafts/{draft['id']}/submit",
                        headers={
                            "X-Developer-User": "DEV/customer",
                            "Idempotency-Key": f"parallel-{draft['id']}",
                        },
                        json={"row_version": draft["row_version"]},
                    )
                    for draft in drafts
                )
            )
        await app.state.resources.close()
        return list(responses)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        responses = runner.run(submit_all())
    assert all(response.status_code == 201 for response in responses)
    keys = [response.json()["key"] for response in responses]
    assert len(keys) == len(set(keys)) == 4


@pytest.mark.integration
def test_concurrent_identical_submission_executes_once(client: TestClient) -> None:
    draft = _draft(client)
    idempotency_key = f"duplicate-{uuid4()}"

    async def submit_twice() -> list[httpx.Response]:
        app = create_app(_settings(), resource_factory=_resources)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as async_client:
            responses = await asyncio.gather(
                *(
                    async_client.post(
                        f"/api/v1/ticket-drafts/{draft['id']}/submit",
                        headers={
                            "X-Developer-User": "DEV/customer",
                            "Idempotency-Key": idempotency_key,
                        },
                        json={"row_version": draft["row_version"]},
                    )
                    for _ in range(2)
                )
            )
        await app.state.resources.close()
        return list(responses)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        responses = runner.run(submit_twice())
    assert sorted(response.status_code for response in responses) == [200, 201]
    assert len({response.json()["id"] for response in responses}) == 1
    assert (
        _psql(
            "SELECT count(*) FROM integration.idempotency_record "
            f"WHERE idempotency_key='{idempotency_key}' AND processing_status='COMPLETED'"
        )
        == "1"
    )


@pytest.mark.integration
def test_failed_submission_rolls_back_every_business_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before_ticket_count = int(_psql("SELECT count(*) FROM itsm.ticket"))
    before_counter = int(
        _psql(
            "SELECT next_ticket_number FROM itsm.project_ticket_counter "
            "WHERE project_id='30000000-0000-0000-0000-000000000002'"
        )
    )
    with TestClient(
        create_app(_settings(), resource_factory=_resources),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
        raise_server_exceptions=False,
    ) as local_client:
        draft = _draft(local_client)
        key = f"rollback-{uuid4()}"

        async def fail_after_ticket_insert(*args: object, **kwargs: object) -> None:
            raise RuntimeError("forced transactional rollback")

        monkeypatch.setattr(TicketRepository, "finish_submission", fail_after_ticket_insert)
        response = local_client.post(
            f"/api/v1/ticket-drafts/{draft['id']}/submit",
            headers={"X-Developer-User": "DEV/customer", "Idempotency-Key": key},
            json={"row_version": draft["row_version"]},
        )
    assert response.status_code == 500
    assert int(_psql("SELECT count(*) FROM itsm.ticket")) == before_ticket_count
    assert (
        int(
            _psql(
                "SELECT next_ticket_number FROM itsm.project_ticket_counter "
                "WHERE project_id='30000000-0000-0000-0000-000000000002'"
            )
        )
        == before_counter
    )
    assert (
        _psql(f"SELECT count(*) FROM integration.idempotency_record WHERE idempotency_key='{key}'")
        == "0"
    )
    assert (
        _psql(f"SELECT draft_status FROM itsm.ticket_draft WHERE draft_id='{draft['id']}'")
        == "READY_FOR_REVIEW"
    )


@pytest.mark.integration
def test_customer_ticket_pagination_is_stable_and_tenant_safe(client: TestClient) -> None:
    created_ids: set[str] = set()
    for _ in range(3):
        draft = _draft(client)
        response = client.post(
            f"/api/v1/ticket-drafts/{draft['id']}/submit",
            headers={
                "X-Developer-User": "DEV/customer",
                "Idempotency-Key": f"page-{uuid4()}",
            },
            json={"row_version": draft["row_version"]},
        )
        assert response.status_code == 201
        created_ids.add(response.json()["id"])
    first = client.get("/api/v1/my/tickets?limit=2", headers={"X-Developer-User": "DEV/customer"})
    assert first.status_code == 200 and first.json()["next_cursor"]
    second = client.get(
        "/api/v1/my/tickets",
        headers={"X-Developer-User": "DEV/customer"},
        params={"limit": 100, "cursor": first.json()["next_cursor"]},
    )
    first_ids = {item["id"] for item in first.json()["items"]}
    second_ids = {item["id"] for item in second.json()["items"]}
    assert not first_ids & second_ids
    assert created_ids <= first_ids | second_ids
    other = client.get("/api/v1/my/tickets", headers={"X-Developer-User": "OTHER/customer"})
    assert other.status_code == 200 and other.json()["items"] == []


@pytest.mark.integration
def test_analyst_reads_unassigned_ticket_and_public_comment_is_idempotent(
    client: TestClient,
) -> None:
    draft = _draft(client)
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"analyst-flow-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    assert submitted.status_code == 201
    ticket_key = submitted.json()["key"]

    analyst_headers = {"X-Developer-User": "DEV/agent"}
    listing = client.get("/api/v1/agent/tickets", headers=analyst_headers)
    assert listing.status_code == 200
    assert ticket_key in {item["key"] for item in listing.json()["items"]}
    assert (
        client.get(f"/api/v1/agent/tickets/{ticket_key}", headers=analyst_headers).status_code
        == 200
    )
    assert (
        client.get(
            "/api/v1/agent/tickets", headers={"X-Developer-User": "DEV/customer"}
        ).status_code
        == 403
    )

    comment_key = f"comment-{uuid4()}"
    comment_headers = {**analyst_headers, "Idempotency-Key": comment_key}
    comment_path = f"/api/v1/tickets/{ticket_key}/comments"
    created = client.post(
        comment_path,
        headers=comment_headers,
        json={"body": "  Please retry the invoice validation and confirm the result.  "},
    )
    assert created.status_code == 201
    replay = client.post(
        comment_path,
        headers=comment_headers,
        json={"body": "Please retry the invoice validation and confirm the result."},
    )
    assert replay.status_code == 200
    assert len(replay.json()["public_comments"]) == 1

    customer = client.get(
        f"/api/v1/tickets/{ticket_key}", headers={"X-Developer-User": "DEV/customer"}
    )
    assert customer.status_code == 200
    assert customer.json()["public_comments"][0]["author_name"] == "Development Agent"
    ticket_id = submitted.json()["id"]
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_event "
            f"WHERE ticket_id='{ticket_id}' AND event_type='PUBLIC_COMMENT_ADDED'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT count(*) FROM audit.audit_event "
            "WHERE action_code='TICKET_PUBLIC_COMMENT_ADDED' "
            f"AND change_summary_json->>'ticket_id'='{ticket_id}'"
        )
        == "1"
    )


@pytest.mark.integration
def test_workflow_transition_is_authorized_validated_idempotent_and_audited(
    client: TestClient,
) -> None:
    draft = _draft(client)
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"workflow-submit-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    assert submitted.status_code == 201
    ticket, ticket_id = submitted.json(), submitted.json()["id"]
    path = f"/api/v1/agent/tickets/{ticket['key']}/transitions"
    assert client.get(path, headers={"X-Developer-User": "DEV/customer"}).status_code == 403
    agent = {"X-Developer-User": "DEV/agent"}
    available = client.get(path, headers=agent)
    assert available.status_code == 200
    assert available.json()["current_status"] == "NEW"
    assert [item["code"] for item in available.json()["transitions"]] == ["START_PROGRESS"]

    invalid = client.post(
        path,
        headers={**agent, "Idempotency-Key": f"invalid-transition-{uuid4()}"},
        json={"transition_code": "RESOLVE", "row_version": ticket["row_version"]},
    )
    assert invalid.status_code == 409
    stale = client.post(
        path,
        headers={**agent, "Idempotency-Key": f"stale-transition-{uuid4()}"},
        json={"transition_code": "START_PROGRESS", "row_version": 999999},
    )
    assert stale.status_code == 409

    key = f"transition-{uuid4()}"
    command = {
        "transition_code": "START_PROGRESS",
        "row_version": ticket["row_version"],
        "comment": "Investigation has started.",
    }
    transitioned = client.post(path, headers={**agent, "Idempotency-Key": key}, json=command)
    assert transitioned.status_code == 200
    result = transitioned.json()
    assert result["ticket"]["status"] == "IN_PROGRESS"
    assert result["ticket"]["row_version"] == ticket["row_version"] + 1
    assert result["ticket"]["public_comments"][0]["body"] == "Investigation has started."
    replay = client.post(path, headers={**agent, "Idempotency-Key": key}, json=command)
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["replayed"] is True
    conflict = client.post(
        path,
        headers={**agent, "Idempotency-Key": key},
        json={**command, "comment": "Different request"},
    )
    assert conflict.status_code == 409
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_event event JOIN itsm.ticket ticket "
            "ON ticket.ticket_id=event.ticket_id "
            f"WHERE event.ticket_id='{ticket_id}' "
            "AND event.event_type='WORKFLOW_TRANSITION_EXECUTED' "
            "AND event.event_data_json->>'workflow_version_id'="
            "ticket.workflow_version_id::text"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_event "
            f"WHERE ticket_id='{ticket_id}' AND event_type='STATUS_CHANGED'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT count(*) FROM integration.outbox_event "
            f"WHERE aggregate_id='{ticket_id}' AND event_type='TICKET_WORKFLOW_TRANSITIONED'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT count(*) FROM audit.audit_event "
            f"WHERE resource_id='{ticket_id}' AND action_code='TICKET_WORKFLOW_TRANSITIONED'"
        )
        == "1"
    )


@pytest.mark.integration
def test_manager_approval_is_versioned_authorized_idempotent_and_advances_workflow(
    client: TestClient,
) -> None:
    access_body: dict[str, object] = {
        "request_type_id": "33000000-0000-0000-0000-000000000002",
        "summary": "Request Fusion access",
        "description": "Access is needed for the approved finance responsibilities.",
        "impact": "LIMITED",
        "urgency": "NORMAL",
        "custom_fields": [],
    }
    draft = _draft(client, access_body)
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"approval-submit-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    assert submitted.status_code == 201
    ticket = submitted.json()
    transition_path = f"/api/v1/agent/tickets/{ticket['key']}/transitions"
    agent = {"X-Developer-User": "DEV/agent"}
    available = client.get(transition_path, headers=agent)
    assert available.status_code == 200
    assert {item["code"] for item in available.json()["transitions"]} == {
        "START_PROGRESS",
        "REQUEST_APPROVAL",
    }
    requested = client.post(
        transition_path,
        headers={**agent, "Idempotency-Key": f"approval-request-{uuid4()}"},
        json={"transition_code": "REQUEST_APPROVAL", "row_version": ticket["row_version"]},
    )
    assert requested.status_code == 200
    assert requested.json()["ticket"]["status"] == "AWAITING_APPROVAL"
    after_request = client.get(transition_path, headers=agent)
    assert after_request.status_code == 200
    assert after_request.json()["transitions"] == []
    direct_continuation = client.post(
        transition_path,
        headers={**agent, "Idempotency-Key": f"direct-approval-{uuid4()}"},
        json={
            "transition_code": "APPROVE_ACCESS",
            "row_version": requested.json()["ticket"]["row_version"],
        },
    )
    assert direct_continuation.status_code == 409

    assert (
        client.get("/api/v1/my/approvals", headers={"X-Developer-User": "DEV/customer"}).status_code
        == 403
    )
    approver = {"X-Developer-User": "DEV/approver"}
    listing = client.get("/api/v1/my/approvals", headers=approver)
    assert listing.status_code == 200
    approval = next(item for item in listing.json()["items"] if item["ticket_key"] == ticket["key"])
    assert approval["status"] == "PENDING"
    assert approval["approval_mode"] == "MANAGER_APPROVAL"
    assert (
        _psql(
            "SELECT approval_definition_version_id FROM itsm.ticket_approval "
            f"WHERE ticket_approval_id='{approval['approval_id']}'"
        )
        == "38700000-0000-0000-0000-000000000001"
    )
    decision_path = f"/api/v1/approvals/{approval['approval_id']}/decisions"
    missing_comment = client.post(
        decision_path,
        headers={**approver, "Idempotency-Key": f"reject-no-comment-{uuid4()}"},
        json={"decision": "REJECT", "expected_version": approval["row_version"]},
    )
    assert missing_comment.status_code == 422
    stale = client.post(
        decision_path,
        headers={**approver, "Idempotency-Key": f"approval-stale-{uuid4()}"},
        json={"decision": "APPROVE", "expected_version": 999},
    )
    assert stale.status_code == 409
    key = f"approval-decision-{uuid4()}"
    command = {
        "decision": "APPROVE",
        "comment": "Access request is justified.",
        "expected_version": approval["row_version"],
    }
    decided = client.post(
        decision_path,
        headers={**approver, "Idempotency-Key": key},
        json=command,
    )
    assert decided.status_code == 200
    assert decided.json()["approval"]["status"] == "APPROVED"
    replay = client.post(
        decision_path,
        headers={**approver, "Idempotency-Key": key},
        json=command,
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["replayed"] is True
    duplicate = client.post(
        decision_path,
        headers={**approver, "Idempotency-Key": f"approval-duplicate-{uuid4()}"},
        json={**command, "expected_version": decided.json()["approval"]["row_version"]},
    )
    assert duplicate.status_code == 409
    customer_ticket = client.get(
        f"/api/v1/tickets/{ticket['key']}",
        headers={"X-Developer-User": "DEV/customer"},
    )
    assert customer_ticket.status_code == 200
    assert customer_ticket.json()["status"] == "IN_PROGRESS"
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_approval_decision "
            f"WHERE ticket_approval_id='{approval['approval_id']}'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT count(*) FROM integration.outbox_event "
            f"WHERE aggregate_id='{approval['approval_id']}' "
            "AND event_type IN ('APPROVAL_REQUESTED','APPROVAL_DECIDED')"
        )
        == "2"
    )
    assert (
        _psql(
            "SELECT count(*) FROM audit.audit_event "
            f"WHERE resource_id='{approval['approval_id']}' "
            "AND action_code IN ('APPROVAL_REQUESTED','APPROVAL_DECIDED')"
        )
        == "2"
    )


@pytest.mark.integration
def test_approval_rejection_expiry_and_cancellation_are_persisted(client: TestClient) -> None:
    approver = {"X-Developer-User": "DEV/approver"}

    rejected_ticket, rejected = _request_access_approval(client, "approval-reject")
    rejected_response = client.post(
        f"/api/v1/approvals/{rejected['approval_id']}/decisions",
        headers={**approver, "Idempotency-Key": f"approval-reject-{uuid4()}"},
        json={
            "decision": "REJECT",
            "comment": "The requested responsibility is not authorized.",
            "expected_version": rejected["row_version"],
        },
    )
    assert rejected_response.status_code == 200
    assert rejected_response.json()["approval"]["status"] == "REJECTED"
    rejected_view = client.get(
        f"/api/v1/tickets/{rejected_ticket['key']}",
        headers={"X-Developer-User": "DEV/customer"},
    )
    assert rejected_view.json()["status"] == "REJECTED"

    _, expired = _request_access_approval(client, "approval-expire")
    _psql(
        "UPDATE itsm.ticket_approval SET requested_at=now()-interval '2 minutes', "
        "expires_at=now()-interval '1 minute' "
        f"WHERE ticket_approval_id='{expired['approval_id']}'"
    )
    expired_response = client.post(
        f"/api/v1/approvals/{expired['approval_id']}/decisions",
        headers={**approver, "Idempotency-Key": f"approval-expired-{uuid4()}"},
        json={"decision": "APPROVE", "expected_version": expired["row_version"]},
    )
    assert expired_response.status_code == 409
    assert (
        _psql(
            "SELECT approval_status FROM itsm.ticket_approval "
            f"WHERE ticket_approval_id='{expired['approval_id']}'"
        )
        == "EXPIRED"
    )

    cancelled_ticket, cancelled = _request_access_approval(client, "approval-cancel")

    async def cancel() -> int:
        settings = _settings()
        database = Database(settings)
        tenant_id = UUID("20000000-0000-0000-0000-000000000001")
        actor_user_id = UUID("22000000-0000-0000-0000-000000000004")
        context = RequestContext(
            tenant_id,
            actor_user_id,
            "agent",
            frozenset({"AGENT"}),
            frozenset(),
            UUID("21000000-0000-0000-0000-000000000001"),
            str(uuid4()),
            str(uuid4()),
        )
        try:
            async with SqlAlchemyUnitOfWork(
                database.session_factory, context, rls_enabled=False
            ) as uow:
                count = await ApprovalEngine(ApprovalRepository(uow.session)).cancel_for_ticket(
                    tenant_id,
                    UUID(cast("str", cancelled_ticket["id"])),
                    actor_user_id,
                    context.correlation_id,
                    context.request_id,
                )
                await uow.commit()
                return count
        finally:
            await database.close()

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        assert runner.run(cancel()) == 1
    assert (
        _psql(
            "SELECT approval_status FROM itsm.ticket_approval "
            f"WHERE ticket_approval_id='{cancelled['approval_id']}'"
        )
        == "CANCELLED"
    )


@pytest.mark.integration
def test_transition_required_fields_and_concurrent_conflict(client: TestClient) -> None:
    draft = _draft(client)
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"workflow-concurrency-submit-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    ticket = submitted.json()
    path = f"/api/v1/agent/tickets/{ticket['key']}/transitions"

    async def race() -> list[TransitionResponse | BaseException]:
        app = create_app(_settings(), resource_factory=_resources)
        contexts = [
            RequestContext(
                tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
                user_id=UUID("22000000-0000-0000-0000-000000000004"),
                external_subject="agent",
                roles=frozenset({"AGENT"}),
                support_group_ids=frozenset(),
                business_unit_id=None,
                correlation_id=str(uuid4()),
                request_id=str(uuid4()),
            )
            for _ in range(2)
        ]
        command = TransitionCommand(
            transition_code="START_PROGRESS", row_version=ticket["row_version"]
        )
        responses = await asyncio.gather(
            *(
                app.state.workflow_service.execute(
                    context, ticket["key"], command, f"transition-race-{uuid4()}"
                )
                for context in contexts
            ),
            return_exceptions=True,
        )
        await app.state.resources.close()
        return list(responses)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        responses = runner.run(race())
    assert sum(isinstance(response, TransitionResponse) for response in responses) == 1
    assert sum(isinstance(response, ConcurrencyError) for response in responses) == 1, responses
    current = next(
        response.ticket.model_dump(mode="json")
        for response in responses
        if isinstance(response, TransitionResponse)
    )
    missing = client.post(
        path,
        headers={
            "X-Developer-User": "DEV/agent",
            "Idempotency-Key": f"resolve-missing-{uuid4()}",
        },
        json={"transition_code": "RESOLVE", "row_version": current["row_version"]},
    )
    assert missing.status_code == 422
    resolved = client.post(
        path,
        headers={
            "X-Developer-User": "DEV/agent",
            "Idempotency-Key": f"resolve-valid-{uuid4()}",
        },
        json={
            "transition_code": "RESOLVE",
            "row_version": current["row_version"],
            "field_updates": {
                "resolution_code": "FIXED",
                "resolution_summary": "Configuration corrected.",
            },
        },
    )
    assert resolved.status_code == 200
    assert resolved.json()["ticket"]["status"] == "RESOLVED"


@pytest.mark.integration
def test_ap_issue_routes_by_published_version_and_manual_assignment_is_audited(
    client: TestClient,
) -> None:
    body = _body()
    body["service_node_id"] = "31000000-0000-0000-0000-000000000005"
    draft = _draft(client, body)
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"routing-submit-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    assert submitted.status_code == 201
    ticket = submitted.json()
    path = f"/api/v1/agent/tickets/{ticket['key']}/route"
    assert (
        client.post(
            path,
            headers={
                "X-Developer-User": "DEV/customer",
                "Idempotency-Key": f"route-denied-{uuid4()}",
            },
            json={"row_version": ticket["row_version"]},
        ).status_code
        == 403
    )
    assert (
        client.post(
            path,
            headers={
                "X-Developer-User": "DEV/agent",
                "Idempotency-Key": f"route-agent-denied-{uuid4()}",
            },
            json={"row_version": ticket["row_version"]},
        ).status_code
        == 403
    )

    route_key = f"route-ap-{uuid4()}"
    headers = {
        "X-Developer-User": "DEV/support-manager",
        "Idempotency-Key": route_key,
    }
    routed = client.post(path, headers=headers, json={"row_version": ticket["row_version"]})
    assert routed.status_code == 200
    decision = routed.json()
    assert decision["assignment_group_code"] == "FUSION_AP"
    assert decision["assignee_user_id"] == "22000000-0000-0000-0000-000000000004"
    assert decision["routing_rule_version_id"] == "36100000-0000-0000-0000-000000000001"
    assert decision["fallback"] is False
    replay = client.post(path, headers=headers, json={"row_version": ticket["row_version"]})
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json()["replayed"] is True
    reused = client.post(
        path,
        headers=headers,
        json={"row_version": decision["ticket"]["row_version"]},
    )
    assert reused.status_code == 409

    assignment_path = f"/api/v1/agent/tickets/{ticket['key']}/assignment"
    assert (
        client.post(
            assignment_path,
            headers={
                "X-Developer-User": "DEV/agent",
                "Idempotency-Key": f"manual-denied-{uuid4()}",
            },
            json={
                "assignment_group_id": "23000000-0000-0000-0000-000000000001",
                "row_version": decision["ticket"]["row_version"],
                "reason": "Escalation requested",
            },
        ).status_code
        == 403
    )
    manual_key = f"manual-assignment-{uuid4()}"
    manual_headers = {
        "X-Developer-User": "DEV/support-manager",
        "Idempotency-Key": manual_key,
    }
    manual_command = {
        "assignment_group_id": "23000000-0000-0000-0000-000000000001",
        "assignee_user_id": "22000000-0000-0000-0000-000000000003",
        "row_version": decision["ticket"]["row_version"],
        "reason": "Manager triage escalation",
    }
    manual = client.post(assignment_path, headers=manual_headers, json=manual_command)
    assert manual.status_code == 200
    assert manual.json()["assignment_group_code"] == "DEV_SERVICE_DESK"
    assert manual.json()["routing_rule_version_id"] is None
    assert (
        client.post(assignment_path, headers=manual_headers, json=manual_command).headers[
            "Idempotent-Replayed"
        ]
        == "true"
    )

    ticket_id = ticket["id"]
    assert (
        _psql(
            "SELECT count(*) FROM itsm.assignment_history "
            f"WHERE ticket_id='{ticket_id}' "
            "AND routing_rule_id='36000000-0000-0000-0000-000000000001' "
            "AND routing_rule_version_id='36100000-0000-0000-0000-000000000001'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT count(*) FROM itsm.assignment_history "
            f"WHERE ticket_id='{ticket_id}' AND assignment_reason LIKE 'MANUAL:%' "
            "AND routing_rule_id IS NULL AND routing_rule_version_id IS NULL"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_event "
            f"WHERE ticket_id='{ticket_id}' AND event_type IN ('TICKET_ROUTED','TICKET_REASSIGNED')"
        )
        == "2"
    )

    second_draft = _draft(client, body)
    second_submitted = client.post(
        f"/api/v1/ticket-drafts/{second_draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"routing-round-robin-submit-{uuid4()}",
        },
        json={"row_version": second_draft["row_version"]},
    ).json()
    second_route = client.post(
        f"/api/v1/agent/tickets/{second_submitted['key']}/route",
        headers={
            "X-Developer-User": "DEV/support-manager",
            "Idempotency-Key": f"routing-round-robin-{uuid4()}",
        },
        json={"row_version": second_submitted["row_version"]},
    )
    assert second_route.status_code == 200
    assert second_route.json()["assignee_user_id"] == "22000000-0000-0000-0000-000000000012"
    assert (
        _psql(
            "SELECT (event_data_json->'routing_trace'->>'routing_source'="
            "'CONFIGURATION_ONLY' AND "
            "event_data_json->'routing_trace'->'inputs'->>'module_code'="
            "'ACCOUNTS_PAYABLE' AND "
            "jsonb_array_length(event_data_json->'routing_trace'->'evaluated_rules')=1 "
            "AND length(event_data_json->'routing_trace'->>'input_hash')=64)::int "
            f"FROM itsm.ticket_event WHERE ticket_id='{ticket_id}' "
            "AND event_type='TICKET_ROUTED'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT count(*) FROM integration.outbox_event "
            f"WHERE aggregate_id='{ticket_id}' AND event_type='TICKET_ASSIGNED'"
        )
        == "2"
    )
    assert (
        _psql(
            "SELECT count(*) FROM audit.audit_event "
            f"WHERE resource_id='{ticket_id}' "
            "AND action_code IN ('TICKET_ROUTED','TICKET_REASSIGNED')"
        )
        == "2"
    )


@pytest.mark.integration
def test_explicit_default_route_and_concurrent_assignment_conflict(client: TestClient) -> None:
    draft = _draft(client)
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"routing-fallback-submit-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    ticket = submitted.json()

    async def race() -> list[AssignmentResponse | BaseException]:
        app = create_app(_settings(), resource_factory=_resources)
        contexts = [
            RequestContext(
                tenant_id=UUID("20000000-0000-0000-0000-000000000001"),
                user_id=UUID("22000000-0000-0000-0000-000000000003"),
                external_subject="support-manager",
                roles=frozenset({"SUPPORT_MANAGER"}),
                support_group_ids=frozenset(
                    {
                        UUID("23000000-0000-0000-0000-000000000001"),
                        UUID("23000000-0000-0000-0000-000000000002"),
                    }
                ),
                business_unit_id=None,
                correlation_id=str(uuid4()),
                request_id=str(uuid4()),
            )
            for _ in range(2)
        ]
        command = RouteCommand(row_version=ticket["row_version"])
        responses = await asyncio.gather(
            *(
                app.state.routing_service.route(
                    context, ticket["key"], command, f"routing-race-{uuid4()}"
                )
                for context in contexts
            ),
            return_exceptions=True,
        )
        await app.state.resources.close()
        return list(responses)

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        responses = runner.run(race())
    assert sum(isinstance(response, AssignmentResponse) for response in responses) == 1
    assert sum(isinstance(response, ConcurrencyError) for response in responses) == 1, responses
    winner = next(response for response in responses if isinstance(response, AssignmentResponse))
    assert winner.assignment_group_code == "DEV_SERVICE_DESK"
    assert winner.assignee_user_id is None
    assert winner.fallback is True
    assert winner.routing_rule_version_id == "36100000-0000-0000-0000-000000000002"


@pytest.mark.integration
def test_versioned_queues_are_scoped_searchable_and_stably_paginated(
    client: TestClient,
) -> None:
    customer_headers = {"X-Developer-User": "DEV/customer"}
    agent_headers = {"X-Developer-User": "DEV/agent"}
    assert client.get("/api/v1/agent/queues", headers=customer_headers).status_code == 403

    queues = client.get("/api/v1/agent/queues", headers=agent_headers)
    assert queues.status_code == 200
    items = queues.json()["items"]
    assert [item["name"] for item in items] == [
        "Unassigned",
        "Assigned to me",
        "Fusion AP group",
        "ERP project",
    ]
    assert all(item["version_id"].startswith("37100000-") for item in items)
    assert (
        _psql(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='itsm' AND indexname IN ("
            "'ticket_queue_unassigned_created_ix','ticket_queue_assignee_created_ix',"
            "'ticket_queue_group_created_ix','ticket_queue_project_created_ix',"
            "'ticket_queue_search_ix')"
        )
        == "5"
    )

    body = _body()
    body["summary"] = "Unique queue search invoice failure"
    body["service_node_id"] = "31000000-0000-0000-0000-000000000005"
    draft = _draft(client, body)
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            **customer_headers,
            "Idempotency-Key": f"queue-submit-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    assert submitted.status_code == 201
    ticket = submitted.json()

    unassigned_id = "37000000-0000-0000-0000-000000000001"
    unassigned = client.get(
        f"/api/v1/agent/queues/{unassigned_id}/tickets",
        headers=agent_headers,
        params={"search": "Unique queue"},
    )
    assert unassigned.status_code == 200
    assert [item["key"] for item in unassigned.json()["items"]] == [ticket["key"]]
    safe_search = client.get(
        f"/api/v1/agent/queues/{unassigned_id}/tickets",
        headers=agent_headers,
        params={"search": "' OR true --"},
    )
    assert safe_search.status_code == 200

    routed = client.post(
        f"/api/v1/agent/tickets/{ticket['key']}/route",
        headers={
            "X-Developer-User": "DEV/support-manager",
            "Idempotency-Key": f"queue-route-{uuid4()}",
        },
        json={"row_version": ticket["row_version"]},
    )
    assert routed.status_code == 200
    assert routed.json()["assignee_user_id"] == "22000000-0000-0000-0000-000000000004"

    for queue_id in (
        "37000000-0000-0000-0000-000000000002",
        "37000000-0000-0000-0000-000000000003",
        "37000000-0000-0000-0000-000000000004",
    ):
        page = client.get(
            f"/api/v1/agent/queues/{queue_id}/tickets",
            headers=agent_headers,
            params={"search": "Unique queue"},
        )
        assert page.status_code == 200
        assert ticket["key"] in {item["key"] for item in page.json()["items"]}

    project_path = "/api/v1/agent/queues/37000000-0000-0000-0000-000000000004/tickets"
    first = client.get(project_path, headers=agent_headers, params={"limit": 1})
    assert first.status_code == 200 and first.json()["next_cursor"]
    second = client.get(
        project_path,
        headers=agent_headers,
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200
    assert first.json()["items"][0]["id"] != second.json()["items"][0]["id"]
    assert (
        client.get(
            project_path,
            headers=agent_headers,
            params={"limit": 1, "cursor": first.json()["next_cursor"], "search": "invoice"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            project_path,
            headers=agent_headers,
            params={"assignment_group_id": str(uuid4())},
        ).status_code
        == 403
    )


@pytest.mark.integration
def test_activity_timeline_classifies_comments_without_customer_leakage(
    client: TestClient,
) -> None:
    customer_headers = {"X-Developer-User": "DEV/customer"}
    agent_headers = {"X-Developer-User": "DEV/agent"}
    draft = _draft(client)
    submitted = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            **customer_headers,
            "Idempotency-Key": f"timeline-submit-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    ).json()
    comment_path = f"/api/v1/agent/tickets/{submitted['key']}/comments"
    assert (
        client.post(
            comment_path,
            headers={
                **customer_headers,
                "Idempotency-Key": f"customer-agent-comment-{uuid4()}",
            },
            json={"visibility": "PUBLIC", "body": "attempt"},
        ).status_code
        == 403
    )

    internal_key = f"internal-comment-{uuid4()}"
    internal_headers = {**agent_headers, "Idempotency-Key": internal_key}
    internal = client.post(
        comment_path,
        headers=internal_headers,
        json={"visibility": "INTERNAL", "body": "Private investigation detail"},
    )
    assert internal.status_code == 201
    assert internal.json()["classification"] == "INTERNAL"
    assert (
        _psql(
            "SELECT count(*) FROM integration.outbox_event "
            f"WHERE aggregate_id='{submitted['id']}' AND event_type LIKE 'NOTIFY_%COMMENT%'"
        )
        == "0"
    )
    replay = client.post(
        comment_path,
        headers=internal_headers,
        json={"visibility": "INTERNAL", "body": "Private investigation detail"},
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"

    public = client.post(
        comment_path,
        headers={**agent_headers, "Idempotency-Key": f"agent-public-{uuid4()}"},
        json={"visibility": "PUBLIC", "body": "Public investigation update"},
    )
    assert public.status_code == 201
    notification_events = _psql(
        "SELECT event_type||':'||payload_json::text FROM integration.outbox_event "
        f"WHERE aggregate_id='{submitted['id']}' ORDER BY created_at"
    )
    assert "NOTIFY_AGENT_PUBLIC_RESPONSE_ADDED" in notification_events, notification_events
    assert "actor_user_id" in notification_events
    assert "Private investigation detail" not in notification_events
    assert "Public investigation update" not in notification_events
    customer_timeline = client.get(
        f"/api/v1/tickets/{submitted['key']}/timeline", headers=customer_headers
    )
    assert customer_timeline.status_code == 200
    serialized = customer_timeline.text
    assert "Public investigation update" in serialized
    assert "Private investigation detail" not in serialized
    assert {item["classification"] for item in customer_timeline.json()["items"]} == {"PUBLIC"}

    analyst_timeline = client.get(
        f"/api/v1/agent/tickets/{submitted['key']}/timeline", headers=agent_headers
    )
    assert analyst_timeline.status_code == 200
    assert {item["classification"] for item in analyst_timeline.json()["items"]} >= {
        "PUBLIC",
        "INTERNAL",
    }
    ticket_id = submitted["id"]
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_event "
            f"WHERE ticket_id='{ticket_id}' "
            "AND event_type IN ('PUBLIC_COMMENT_ADDED','INTERNAL_COMMENT_ADDED')"
        )
        == "2"
    )
    assert (
        _psql(
            "SELECT count(*) FROM audit.audit_event "
            f"WHERE change_summary_json->>'ticket_id'='{ticket_id}' "
            "AND action_code IN ('TICKET_PUBLIC_COMMENT_ADDED',"
            "'TICKET_INTERNAL_COMMENT_ADDED')"
        )
        == "2"
    )


class AttachmentStorageFake:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.upload_key: str | None = None
        self.rejected: list[str] = []

    async def create_upload_url(
        self, key: str, content_type: str, size: int, checksum: str, expires: int
    ) -> str:
        self.upload_key = key
        assert key.startswith("quarantine/")
        assert content_type and size > 0 and len(checksum) == 64 and expires > 0
        return f"https://objects.example.invalid/upload/{key}"

    async def read(self, key: str, maximum_bytes: int) -> bytes:
        content = self.objects[key]
        assert len(content) <= maximum_bytes
        return content

    async def promote(self, source: str, destination: str, content_type: str) -> None:
        assert destination.startswith("protected/")
        assert content_type
        self.objects[destination] = self.objects.pop(source)

    async def reject(self, key: str) -> None:
        self.rejected.append(key)
        self.objects.pop(key, None)

    async def create_download_url(self, key: str, filename: str, expires: int) -> str:
        assert key.startswith("protected/") and key in self.objects
        assert filename and expires > 0
        return f"https://objects.example.invalid/download/{key}"


class AttachmentScannerFake:
    def __init__(self, result: ScanResult | Exception) -> None:
        self.result = result
        self.calls = 0

    async def scan(self, content: bytes) -> ScanResult:
        self.calls += 1
        assert content
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _install_attachment_service(
    client: TestClient, storage: AttachmentStorageFake, scanner: AttachmentScannerFake
) -> None:
    settings = _settings().model_copy(update={"object_storage_enabled": True})
    application = cast("FastAPI", client.app)
    database = cast("Database", application.state.resources.database)

    def factory(context: RequestContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.session_factory, context, rls_enabled=False)

    application.state.attachment_service = AttachmentService(
        factory, AuthorizationService(), storage, scanner, settings
    )


def _submitted_ticket(client: TestClient) -> dict[str, object]:
    draft = _draft(client)
    response = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"attachment-ticket-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    assert response.status_code == 201
    return cast("dict[str, object]", response.json())


def _authorize_attachment(
    client: TestClient,
    ticket_key: object,
    content: bytes,
    *,
    user: str = "DEV/customer",
    visibility: str = "PUBLIC",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/tickets/{ticket_key}/attachments/uploads",
        headers={"X-Developer-User": user},
        json={
            "filename": "evidence.txt",
            "content_type": "text/plain",
            "file_size_bytes": len(content),
            "sha256_checksum": hashlib.sha256(content).hexdigest(),
            "visibility": visibility,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["upload_url"].startswith("https://objects.example.invalid/upload/")
    assert response.json()["upload_headers"]["x-amz-acl"] == "private"
    assert response.json()["upload_headers"]["Content-Length"] == str(len(content))
    return cast("dict[str, object]", response.json())


@pytest.mark.integration
def test_clean_attachment_is_released_only_after_scan_and_authorized(client: TestClient) -> None:
    storage = AttachmentStorageFake()
    scanner = AttachmentScannerFake(ScanResult(True, "ClamAV", "1.4.3/12345"))
    _install_attachment_service(client, storage, scanner)
    ticket = _submitted_ticket(client)
    content = b"safe customer evidence\n"
    upload = _authorize_attachment(client, ticket["key"], content)
    attachment_id = upload["attachment_id"]
    customer = {"X-Developer-User": "DEV/customer"}

    before = client.post(f"/api/v1/attachments/{attachment_id}/download", headers=customer)
    assert before.status_code == 409
    assert storage.upload_key is not None
    storage.objects[storage.upload_key] = content
    finalize_headers = {
        **customer,
        "Idempotency-Key": f"attachment-finalize-{uuid4()}",
    }
    finalized = client.post(
        f"/api/v1/attachments/{attachment_id}/finalize",
        headers=finalize_headers,
    )
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["scan_status"] == "CLEAN"
    assert finalized.json()["scanner_engine"] == "ClamAV"
    replay = client.post(f"/api/v1/attachments/{attachment_id}/finalize", headers=finalize_headers)
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert scanner.calls == 1
    downloaded = client.post(f"/api/v1/attachments/{attachment_id}/download", headers=customer)
    assert downloaded.status_code == 200
    assert "/protected/" in downloaded.json()["download_url"]
    assert (
        client.post(
            f"/api/v1/attachments/{attachment_id}/download",
            headers={"X-Developer-User": "OTHER/customer"},
        ).status_code
        == 404
    )
    assert (
        _psql(
            "SELECT count(*) FROM audit.audit_event "
            f"WHERE resource_id='{attachment_id}' AND action_code IN "
            "('ATTACHMENT_UPLOAD_AUTHORIZED','ATTACHMENT_RELEASED',"
            "'ATTACHMENT_DOWNLOAD_AUTHORIZED')"
        )
        == "3"
    )
    assert (
        _psql(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_schema='itsm' AND table_name='ticket_attachment' "
            "AND (data_type='bytea' OR column_name IN "
            "('access_key','secret_key','signing_secret','encryption_key'))"
        )
        == "0"
    )


@pytest.mark.integration
def test_infected_attachment_is_rejected_and_never_downloadable(client: TestClient) -> None:
    storage = AttachmentStorageFake()
    scanner = AttachmentScannerFake(
        ScanResult(False, "ClamAV", "1.4.3/12345", "Win.Test.EICAR_HDB-1")
    )
    _install_attachment_service(client, storage, scanner)
    ticket = _submitted_ticket(client)
    content = b"malware-scanner-test-surrogate\n"
    upload = _authorize_attachment(client, ticket["key"], content)
    attachment_id = upload["attachment_id"]
    assert storage.upload_key is not None
    storage.objects[storage.upload_key] = content
    headers = {
        "X-Developer-User": "DEV/customer",
        "Idempotency-Key": f"infected-finalize-{uuid4()}",
    }
    rejected = client.post(f"/api/v1/attachments/{attachment_id}/finalize", headers=headers)
    assert rejected.status_code == 422
    assert storage.rejected and not storage.objects
    assert (
        client.post(
            f"/api/v1/attachments/{attachment_id}/download",
            headers={"X-Developer-User": "DEV/customer"},
        ).status_code
        == 409
    )
    assert (
        _psql(
            "SELECT malware_scan_status || ':' || quarantine_status || ':' || scanner_engine "
            f"FROM itsm.ticket_attachment WHERE attachment_id='{attachment_id}'"
        )
        == "INFECTED:REJECTED:ClamAV"
    )


@pytest.mark.integration
def test_internal_attachment_and_retry_state_fail_closed(client: TestClient) -> None:
    storage = AttachmentStorageFake()
    scanner = AttachmentScannerFake(ScannerError("simulated timeout"))
    _install_attachment_service(client, storage, scanner)
    ticket = _submitted_ticket(client)
    content = b"internal diagnostic\n"
    upload = _authorize_attachment(
        client,
        ticket["key"],
        content,
        user="DEV/platform-admin",
        visibility="INTERNAL",
    )
    attachment_id = upload["attachment_id"]
    assert storage.upload_key is not None
    storage.objects[storage.upload_key] = content
    failed = client.post(
        f"/api/v1/attachments/{attachment_id}/finalize",
        headers={
            "X-Developer-User": "DEV/platform-admin",
            "Idempotency-Key": f"retry-finalize-{uuid4()}",
        },
    )
    assert failed.status_code == 503
    assert failed.headers["Retry-After"] == "30"
    assert failed.json()["scan_status"] == "ERROR"
    assert (
        client.post(
            f"/api/v1/attachments/{attachment_id}/download",
            headers={"X-Developer-User": "DEV/customer"},
        ).status_code
        == 404
    )
    assert (
        _psql(
            "SELECT (scan_attempt_count=1 AND next_scan_at>now() AND "
            "protected_object_uri IS NULL)::int FROM itsm.ticket_attachment "
            f"WHERE attachment_id='{attachment_id}'"
        )
        == "1"
    )


def _first_agent_queue(client: TestClient) -> str:
    response = client.get("/api/v1/agent/queues", headers={"X-Developer-User": "DEV/agent"})
    assert response.status_code == 200
    return cast("str", response.json()["items"][0]["id"])


def _saved_filter_body(queue_id: str, name: str = "My invoice work") -> dict[str, object]:
    return {
        "name": name,
        "queue_id": queue_id,
        "status_code": "NEW",
        "priority_code": "P3",
        "search": "invoice",
        "assignment_group_id": "23000000-0000-0000-0000-000000000002",
        "assignee": "unassigned",
    }


@pytest.mark.integration
def test_personal_saved_filter_crud_reorder_and_apply(client: TestClient) -> None:
    headers = {
        "X-Developer-User": "DEV/agent",
        "Idempotency-Key": f"saved-filter-{uuid4()}",
    }
    queue_id = _first_agent_queue(client)
    created = client.post(
        "/api/v1/agent/saved-filters",
        headers=headers,
        json=_saved_filter_body(queue_id),
    )
    assert created.status_code == 201
    item = created.json()

    replayed = client.post(
        "/api/v1/agent/saved-filters",
        headers=headers,
        json=_saved_filter_body(queue_id),
    )
    assert replayed.status_code == 200
    assert replayed.headers["Idempotent-Replayed"] == "true"
    assert replayed.json()["id"] == item["id"]

    second = client.post(
        "/api/v1/agent/saved-filters",
        headers={
            "X-Developer-User": "DEV/agent",
            "Idempotency-Key": f"saved-filter-{uuid4()}",
        },
        json=_saved_filter_body(queue_id, "My second filter"),
    )
    assert second.status_code == 201
    second_item = second.json()

    listing = client.get("/api/v1/agent/saved-filters", headers={"X-Developer-User": "DEV/agent"})
    assert listing.status_code == 200
    assert [value["id"] for value in listing.json()["items"]] == [
        item["id"],
        second_item["id"],
    ]

    applied = client.get(
        f"/api/v1/agent/saved-filters/{item['id']}/tickets",
        headers={"X-Developer-User": "DEV/agent"},
    )
    assert applied.status_code == 200
    assert all("invoice" in ticket["summary"].lower() for ticket in applied.json()["items"])

    updated_body = {**_saved_filter_body(queue_id, "My urgent invoice work"), "row_version": 1}
    updated = client.patch(
        f"/api/v1/agent/saved-filters/{item['id']}",
        headers={"X-Developer-User": "DEV/agent", "If-Match": '"1"'},
        json=updated_body,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "My urgent invoice work"
    assert updated.json()["row_version"] == 2

    reordered = client.put(
        "/api/v1/agent/saved-filters/order",
        headers={"X-Developer-User": "DEV/agent"},
        json={
            "items": [
                {"id": second_item["id"], "row_version": second_item["row_version"]},
                {"id": item["id"], "row_version": updated.json()["row_version"]},
            ]
        },
    )
    assert reordered.status_code == 200
    assert [value["id"] for value in reordered.json()["items"]] == [
        second_item["id"],
        item["id"],
    ]

    deleted_item = next(value for value in reordered.json()["items"] if value["id"] == item["id"])
    deleted = client.request(
        "DELETE",
        f"/api/v1/agent/saved-filters/{item['id']}",
        headers={"X-Developer-User": "DEV/agent"},
        json={"row_version": deleted_item["row_version"]},
    )
    assert deleted.status_code == 204
    assert (
        client.get(
            f"/api/v1/agent/saved-filters/{item['id']}",
            headers={"X-Developer-User": "DEV/agent"},
        ).status_code
        == 404
    )


@pytest.mark.integration
def test_saved_filters_fail_closed_across_users_tenants_and_roles(client: TestClient) -> None:
    queue_id = _first_agent_queue(client)
    created = client.post(
        "/api/v1/agent/saved-filters",
        headers={
            "X-Developer-User": "DEV/agent",
            "Idempotency-Key": f"saved-filter-isolation-{uuid4()}",
        },
        json=_saved_filter_body(queue_id, "Private filter"),
    )
    assert created.status_code == 201
    item = created.json()
    path = f"/api/v1/agent/saved-filters/{item['id']}"
    update_body = {**_saved_filter_body(queue_id, "Stolen filter"), "row_version": 1}

    for selector in ("DEV/agent-two", "OTHER/agent"):
        request_headers = {"X-Developer-User": selector}
        assert client.get(path, headers=request_headers).status_code == 404
        assert client.patch(path, headers=request_headers, json=update_body).status_code == 404
        assert (
            client.request(
                "DELETE", path, headers=request_headers, json={"row_version": 1}
            ).status_code
            == 404
        )

    for method, path_suffix in (
        ("GET", "/api/v1/agent/saved-filters"),
        ("GET", path),
    ):
        assert (
            client.request(
                method, path_suffix, headers={"X-Developer-User": "DEV/customer"}
            ).status_code
            == 403
        )

    arbitrary_expression = {
        **_saved_filter_body(queue_id, "Unsafe filter"),
        "where": "1=1; DROP TABLE itsm.ticket",
    }
    rejected = client.post(
        "/api/v1/agent/saved-filters",
        headers={
            "X-Developer-User": "DEV/agent",
            "Idempotency-Key": f"saved-filter-invalid-{uuid4()}",
        },
        json=arbitrary_expression,
    )
    assert rejected.status_code == 422


@pytest.mark.integration
def test_personal_canned_response_crud_reorder_and_isolation(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    agent = {"X-Developer-User": "DEV/agent"}
    private_body = "Please provide the affected invoice. PRIVATE-CANNED-121"
    first = client.post(
        "/api/v1/agent/canned-responses",
        headers={**agent, "Idempotency-Key": f"canned-response-{uuid4()}"},
        json={"name": "Request details", "body": private_body},
    )
    assert first.status_code == 201
    item = first.json()
    assert item["body"] == private_body
    assert "PRIVATE-CANNED-121" not in caplog.text

    replay_key = f"canned-response-{uuid4()}"
    second_body = {"name": "Resolution", "body": "The invoice has been reprocessed."}
    second = client.post(
        "/api/v1/agent/canned-responses",
        headers={**agent, "Idempotency-Key": replay_key},
        json=second_body,
    )
    assert second.status_code == 201
    replay = client.post(
        "/api/v1/agent/canned-responses",
        headers={**agent, "Idempotency-Key": replay_key},
        json=second_body,
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotent-Replayed"] == "true"

    listing = client.get("/api/v1/agent/canned-responses", headers=agent)
    assert listing.status_code == 200
    assert [value["name"] for value in listing.json()["items"]] == [
        "Request details",
        "Resolution",
    ]

    updated = client.patch(
        f"/api/v1/agent/canned-responses/{item['id']}",
        headers={**agent, "If-Match": "1"},
        json={
            "name": "Request invoice details",
            "body": "Please provide the affected invoice number.",
            "row_version": 1,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["row_version"] == 2

    second_item = second.json()
    reordered = client.put(
        "/api/v1/agent/canned-responses/order",
        headers=agent,
        json={
            "items": [
                {"id": second_item["id"], "row_version": second_item["row_version"]},
                {"id": item["id"], "row_version": 2},
            ]
        },
    )
    assert reordered.status_code == 200
    assert reordered.json()["items"][0]["id"] == second_item["id"]

    path = f"/api/v1/agent/canned-responses/{item['id']}"
    for selector in ("DEV/agent-two", "OTHER/agent"):
        headers = {"X-Developer-User": selector}
        assert client.get(path, headers=headers).status_code == 404
        assert (
            client.put(
                "/api/v1/agent/canned-responses/order",
                headers=headers,
                json={"items": [{"id": item["id"], "row_version": 3}]},
            ).status_code
            == 422
        )
        assert (
            client.patch(
                path,
                headers=headers,
                json={
                    "name": "Stolen",
                    "body": "Stolen body",
                    "row_version": 3,
                },
            ).status_code
            == 404
        )
        assert (
            client.request("DELETE", path, headers=headers, json={"row_version": 3}).status_code
            == 404
        )

    customer = {"X-Developer-User": "DEV/customer"}
    assert client.get("/api/v1/agent/canned-responses", headers=customer).status_code == 403
    assert client.get(path, headers=customer).status_code == 403
    assert (
        client.put(
            "/api/v1/agent/canned-responses/order",
            headers=customer,
            json={"items": [{"id": item["id"], "row_version": 3}]},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            path,
            headers=customer,
            json={"name": "Denied", "body": "Denied", "row_version": 3},
        ).status_code
        == 403
    )
    assert (
        client.request("DELETE", path, headers=customer, json={"row_version": 3}).status_code == 403
    )
    rejected = client.post(
        "/api/v1/agent/canned-responses",
        headers={**agent, "Idempotency-Key": f"canned-response-{uuid4()}"},
        json={
            "name": "Unsafe",
            "body": "This is inert plain text.",
            "query": {"sql": "DROP TABLE itsm.ticket"},
        },
    )
    assert rejected.status_code == 422

    current = next(value for value in reordered.json()["items"] if value["id"] == item["id"])
    deleted = client.request(
        "DELETE",
        path,
        headers={**agent, "If-Match": str(current["row_version"])},
        json={"row_version": current["row_version"]},
    )
    assert deleted.status_code == 204


@pytest.mark.integration
def test_canned_response_migration_is_minimal_and_owner_scoped() -> None:
    assert _psql("SELECT version_num FROM config.alembic_version") == ("0035_chunk_error_codes")
    assert (
        _psql(
            "SELECT relrowsecurity FROM pg_class "
            "WHERE oid='config.analyst_canned_response'::regclass"
        )
        == "t"
    )
    assert (
        _psql(
            "SELECT count(*) FROM pg_policies WHERE schemaname='config' "
            "AND tablename='analyst_canned_response' "
            "AND policyname='analyst_canned_response_owner_isolation'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT has_table_privilege('helpdesk_app',"
            "'config.analyst_canned_response','SELECT,INSERT,UPDATE,DELETE')"
        )
        == "t"
    )
    assert (
        _psql(
            "SELECT has_table_privilege('helpdesk_app',"
            "'config.analyst_canned_response','TRUNCATE,TRIGGER,REFERENCES')"
        )
        == "f"
    )
    assert (
        _psql(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='config' "
            "AND tablename='analyst_canned_response'"
        )
        == "3"
    )


def _watch_side_effect_counts(ticket_ids: list[str]) -> str:
    identifiers = ",".join(f"'{value}'" for value in ticket_ids)
    return _psql(
        "SELECT "
        f"(SELECT count(*) FROM itsm.ticket_participant WHERE ticket_id IN ({identifiers}))"
        "||':'||"
        f"(SELECT count(*) FROM itsm.ticket_event WHERE ticket_id IN ({identifiers}))"
        "||':'||"
        "(SELECT count(*) FROM integration.outbox_event "
        f"WHERE aggregate_id IN ({identifiers}))"
        "||':'||"
        "(SELECT count(*) FROM integration.notification_delivery "
        f"WHERE resource_id IN ({identifiers}))"
    )


def _watchlist_ticket(client: TestClient, prefix: str) -> dict[str, object]:
    draft = _draft(
        client,
        {
            **_body(),
            "summary": f"Watchlist validation {prefix}",
        },
    )
    response = client.post(
        f"/api/v1/ticket-drafts/{draft['id']}/submit",
        headers={
            "X-Developer-User": "DEV/customer",
            "Idempotency-Key": f"watchlist-{prefix}-{uuid4()}",
        },
        json={"row_version": draft["row_version"]},
    )
    assert response.status_code == 201
    return cast("dict[str, object]", response.json())


@pytest.mark.integration
def test_personal_ticket_watchlist_is_idempotent_paginated_and_isolated(
    client: TestClient,
) -> None:
    first = _watchlist_ticket(client, "first")
    second = _watchlist_ticket(client, "second")
    ticket_ids = [str(first["id"]), str(second["id"])]
    before_side_effects = _watch_side_effect_counts(ticket_ids)
    agent = {"X-Developer-User": "DEV/agent"}
    first_path = f"/api/v1/agent/tickets/{first['key']}/watch"
    second_path = f"/api/v1/agent/tickets/{second['key']}/watch"

    detail = client.get(f"/api/v1/agent/tickets/{first['key']}", headers=agent)
    assert detail.status_code == 200
    assert detail.json()["watched"] is False

    watched = client.put(first_path, headers=agent)
    assert watched.status_code == 200
    assert watched.json()["watched"] is True
    watched_at = watched.json()["watched_at"]
    replay = client.put(first_path, headers=agent)
    assert replay.status_code == 200
    assert replay.json()["watched_at"] == watched_at
    assert (
        _psql(
            "SELECT count(*) FROM config.analyst_ticket_watchlist "
            f"WHERE owner_user_id='22000000-0000-0000-0000-000000000004' "
            f"AND ticket_id='{first['id']}'"
        )
        == "1"
    )
    assert client.put(second_path, headers=agent).status_code == 200

    page_one = client.get("/api/v1/agent/watched-tickets", headers=agent, params={"limit": 1})
    assert page_one.status_code == 200
    assert page_one.json()["next_cursor"]
    page_two = client.get(
        "/api/v1/agent/watched-tickets",
        headers=agent,
        params={"limit": 1, "cursor": page_one.json()["next_cursor"]},
    )
    assert page_two.status_code == 200
    assert {
        page_one.json()["items"][0]["key"],
        page_two.json()["items"][0]["key"],
    } == {first["key"], second["key"]}
    assert (
        client.get(
            "/api/v1/agent/watched-tickets",
            headers=agent,
            params={"cursor": "not-a-watchlist-cursor"},
        ).status_code
        == 422
    )

    other_user = {"X-Developer-User": "DEV/agent-two"}
    assert (
        client.get(first_path.removesuffix("/watch"), headers=other_user).json()["watched"] is False
    )
    assert client.get("/api/v1/agent/watched-tickets", headers=other_user).json()["items"] == []
    assert client.delete(first_path, headers=other_user).status_code == 204
    assert client.get(first_path.removesuffix("/watch"), headers=agent).json()["watched"] is True

    assert client.put(first_path, headers={"X-Developer-User": "OTHER/agent"}).status_code == 404
    customer = {"X-Developer-User": "DEV/customer"}
    assert client.get("/api/v1/agent/watched-tickets", headers=customer).status_code == 403
    assert client.put(first_path, headers=customer).status_code == 403
    assert client.delete(first_path, headers=customer).status_code == 403

    assert client.delete(first_path, headers=agent).status_code == 204
    assert client.delete(first_path, headers=agent).status_code == 204
    assert client.get(first_path.removesuffix("/watch"), headers=agent).json()["watched"] is False
    assert _watch_side_effect_counts(ticket_ids) == before_side_effects


@pytest.mark.integration
def test_inaccessible_watched_ticket_is_not_returned_or_followed(client: TestClient) -> None:
    ticket = _watchlist_ticket(client, "authorization-change")
    agent_two = {"X-Developer-User": "DEV/agent-two"}
    watch_path = f"/api/v1/agent/tickets/{ticket['key']}/watch"
    assert client.put(watch_path, headers=agent_two).status_code == 200
    _psql(
        "UPDATE itsm.ticket SET "
        "assignment_group_id='23000000-0000-0000-0000-000000000001' "
        f"WHERE ticket_id='{ticket['id']}'"
    )
    listing = client.get("/api/v1/agent/watched-tickets", headers=agent_two)
    assert listing.status_code == 200
    assert ticket["key"] not in {item["key"] for item in listing.json()["items"]}
    assert (
        client.get(f"/api/v1/agent/tickets/{ticket['key']}", headers=agent_two).status_code == 404
    )
    assert client.delete(watch_path, headers=agent_two).status_code == 404
    assert (
        _psql(
            "SELECT count(*) FROM config.analyst_ticket_watchlist "
            f"WHERE owner_user_id='22000000-0000-0000-0000-000000000012' "
            f"AND ticket_id='{ticket['id']}'"
        )
        == "1"
    )


@pytest.mark.integration
def test_ticket_watchlist_migration_is_minimal_and_owner_scoped() -> None:
    assert _psql("SELECT version_num FROM config.alembic_version") == ("0035_chunk_error_codes")
    assert (
        _psql(
            "SELECT relrowsecurity FROM pg_class "
            "WHERE oid='config.analyst_ticket_watchlist'::regclass"
        )
        == "t"
    )
    assert (
        _psql(
            "SELECT count(*) FROM pg_policies WHERE schemaname='config' "
            "AND tablename='analyst_ticket_watchlist' "
            "AND policyname='analyst_ticket_watchlist_owner_isolation'"
        )
        == "1"
    )
    assert (
        _psql(
            "SELECT has_table_privilege('helpdesk_app',"
            "'config.analyst_ticket_watchlist','SELECT,INSERT,DELETE')"
        )
        == "t"
    )
    assert (
        _psql(
            "SELECT has_table_privilege('helpdesk_app',"
            "'config.analyst_ticket_watchlist','UPDATE,TRUNCATE,TRIGGER,REFERENCES')"
        )
        == "f"
    )
    assert (
        _psql(
            "SELECT count(*) FROM pg_indexes WHERE schemaname='config' "
            "AND tablename='analyst_ticket_watchlist'"
        )
        == "3"
    )
