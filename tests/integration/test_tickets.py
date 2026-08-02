"""Real PostgreSQL tests for the draft-to-ticket transactional boundary."""

import asyncio
import logging
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ConcurrencyError
from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app
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
            VALUES ('22000000-0000-0000-0000-000000000099',
              '20000000-0000-0000-0000-000000000099','customer',
              'other-customer@example.invalid','Other Customer');
            INSERT INTO identity.user_role(tenant_id,user_id,role_code,valid_from)
            VALUES ('20000000-0000-0000-0000-000000000099',
              '22000000-0000-0000-0000-000000000099','CUSTOMER',now());
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


def _draft(client: TestClient) -> dict[str, object]:
    headers = {"X-Developer-User": "DEV/customer"}
    created = client.post("/api/v1/ticket-drafts", headers=headers, json=_body())
    assert created.status_code == 201
    value = created.json()
    validated = client.post(
        f"/api/v1/ticket-drafts/{value['id']}/validate",
        headers=headers,
        json={"row_version": value["row_version"]},
    )
    assert validated.status_code == 200
    return cast("dict[str, object]", validated.json()["draft"])


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
