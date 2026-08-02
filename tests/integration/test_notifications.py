"""PostgreSQL and Mailpit coverage for notification planning and delivery."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.api.app.core.settings import Settings
from apps.api.app.db.engine import Database
from apps.api.app.infrastructure.health import ApplicationResources
from apps.api.app.main import create_app
from apps.worker.worker.notification_worker import (
    NotificationWorker,
    PermanentNotificationError,
    RetryableNotificationError,
)
from apps.worker.worker.settings import WorkerSettings

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-notification-test"
POSTGRES_PORT = "55453"
MAILPIT_SMTP_PORT = "51025"
MAILPIT_HTTP_PORT = "58025"
DATABASE = "notification_test"
TENANT_ID = "20000000-0000-0000-0000-000000000001"
CUSTOMER_ID = "22000000-0000-0000-0000-000000000005"
TICKET_ID = "39200000-0000-0000-0000-000000000001"


class HealthyProbe:
    async def check(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class SequenceSender:
    def __init__(self, outcomes: list[str]) -> None:
        self.outcomes = outcomes

    async def send(self, **_: Any) -> str:
        outcome = self.outcomes.pop(0)
        if outcome == "retry":
            raise RetryableNotificationError("temporary")
        if outcome == "permanent":
            raise PermanentNotificationError("invalid recipient")
        return "provider-id"


def _env() -> dict[str, str]:
    result = os.environ.copy()
    result.update(
        {
            "POSTGRES_HOST_PORT": POSTGRES_PORT,
            "MAILPIT_SMTP_HOST_PORT": MAILPIT_SMTP_PORT,
            "MAILPIT_UI_HOST_PORT": MAILPIT_HTTP_PORT,
        }
    )
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


def _psql(sql: str, *, check: bool = True) -> subprocess.CompletedProcess[str]:
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
        check=check,
    )


def _value(sql: str) -> str:
    return _psql(sql).stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def notification_stack() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres", "mailpit")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            args = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                args += ["-v", "app_password=helpdesk"]
            _compose(*args, "-U", "postgres", "-d", DATABASE, "-f", file)
        migration_env = os.environ.copy()
        migration_env["MIGRATION_DATABASE_URL"] = (
            f"postgresql+psycopg://postgres:postgres@127.0.0.1:{POSTGRES_PORT}/{DATABASE}"
        )
        for command in ("stamp", "upgrade"):
            result = subprocess.run(
                ["uv", "run", "python", "-m", "apps.api.app.db.migrations_cli", command],
                cwd=ROOT,
                env=migration_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert result.returncode == 0, result.stdout + result.stderr
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
        _seed_ticket()
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


def _seed_ticket() -> None:
    _psql(
        f"""
        INSERT INTO itsm.ticket(
          ticket_id,tenant_id,project_id,request_type_id,request_type_version_id,
          work_type_id,workflow_version_id,status_id,summary,description,
          reporter_user_id,requested_for_user_id,priority_code,channel_code,
          created_by,updated_by
        ) SELECT
          '{TICKET_ID}','{TENANT_ID}','30000000-0000-0000-0000-000000000002',
          '33000000-0000-0000-0000-000000000001',
          '33100000-0000-0000-0000-000000000001',work_type.work_type_id,
          '32100000-0000-0000-0000-000000000001',
          '32200000-0000-0000-0000-000000000001','Notification integration ticket',
          'Sensitive description must never enter a notification.',
          '{CUSTOMER_ID}','{CUSTOMER_ID}','P2','PORTAL','{CUSTOMER_ID}','{CUSTOMER_ID}'
        FROM config.work_type AS work_type
        WHERE work_type.work_type_code='INCIDENT' AND work_type.tenant_id IS NULL;
        """
    )


def _event(number: int, event_type: str = "NOTIFY_TICKET_CREATED") -> str:
    event_id = f"39300000-0000-0000-0000-{number:012d}"
    _psql(
        f"""
        INSERT INTO integration.outbox_event(
          outbox_event_id,tenant_id,aggregate_type,aggregate_id,event_type,
          payload_json,deduplication_key
        ) VALUES ('{event_id}','{TENANT_ID}','TICKET','{TICKET_ID}',
          '{event_type}','{{}}'::jsonb,'notification-integration-{number}');
        """
    )
    return event_id


def _settings(worker_id: str) -> WorkerSettings:
    return WorkerSettings.model_validate(
        {
            "app_env": "integration",
            "worker_database_url": (
                "postgresql+psycopg://helpdesk_worker_login:helpdesk@127.0.0.1:"
                f"{POSTGRES_PORT}/{DATABASE}"
            ),
            "worker_id": worker_id,
            "smtp_host": "127.0.0.1",
            "smtp_port": int(MAILPIT_SMTP_PORT),
            "smtp_from": "helpdesk@example.invalid",
        }
    )


def _worker(
    worker_id: str, sender: SequenceSender | None = None
) -> tuple[NotificationWorker, AsyncEngine]:
    settings = _settings(worker_id)
    engine = create_async_engine(settings.worker_database_url.get_secret_value())
    return (
        NotificationWorker(async_sessionmaker(engine, expire_on_commit=False), settings, sender),
        engine,
    )


def _run(coroutine: Any) -> Any:
    return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)


def _api_settings() -> Settings:
    return Settings.model_validate(
        {
            "app_env": "integration",
            "database_url": (
                f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{POSTGRES_PORT}/{DATABASE}"
            ),
            "developer_identity_enabled": True,
            "object_storage_enabled": False,
            "trusted_hosts": ["testserver"],
        }
    )


def _resources(settings: Settings) -> ApplicationResources:
    return ApplicationResources(Database(settings), HealthyProbe(), HealthyProbe(), HealthyProbe())


@pytest.mark.integration
def test_ticket_event_creates_exactly_one_email_and_in_app_notification() -> None:
    event_id = _event(1)
    first, first_engine = _worker("notification-one")
    second, second_engine = _worker("notification-two")

    async def process() -> None:
        try:
            claims = await asyncio.gather(first.plan_one(), second.plan_one())
            assert sorted(claims) == [False, True]
            assert await first.deliver_one()
            assert not await first.deliver_one()
        finally:
            await first_engine.dispose()
            await second_engine.dispose()

    _run(process())
    assert (
        _value(
            "SELECT count(*) FROM integration.notification_delivery "
            f"WHERE outbox_event_id='{event_id}'"
        )
        == "1"
    )
    assert (
        _value(
            "SELECT count(*) FROM integration.in_app_notification "
            f"WHERE outbox_event_id='{event_id}'"
        )
        == "1"
    )
    assert (
        _value(
            f"SELECT count(DISTINCT notification_template_version_id) FROM "
            f"integration.notification_delivery WHERE outbox_event_id='{event_id}'"
        )
        == "1"
    )
    messages = httpx.get(f"http://127.0.0.1:{MAILPIT_HTTP_PORT}/api/v1/messages", timeout=5).json()
    assert messages["total"] == 1
    assert messages["messages"][0]["To"][0]["Address"] == "customer@example.invalid"
    assert "Sensitive description" not in str(messages)

    _psql(
        f"UPDATE integration.outbox_event SET status_code='PENDING',processed_at=NULL "
        f"WHERE outbox_event_id='{event_id}'"
    )
    replay, replay_engine = _worker("notification-replay")

    async def replay_event() -> None:
        try:
            assert await replay.plan_one()
            assert not await replay.deliver_one()
        finally:
            await replay_engine.dispose()

    _run(replay_event())
    assert _value("SELECT count(*) FROM integration.notification_delivery") == "1"
    assert _value("SELECT count(*) FROM integration.in_app_notification") == "1"

    with TestClient(
        create_app(_api_settings(), resource_factory=_resources),
        backend_options={"loop_factory": asyncio.SelectorEventLoop},
    ) as client:
        customer = {"X-Developer-User": "DEV/customer"}
        inbox = client.get("/api/v1/my/notifications", headers=customer)
        assert inbox.status_code == 200
        assert inbox.json()["unread_count"] == 1
        notification_id = inbox.json()["items"][0]["id"]
        assert (
            client.get(
                "/api/v1/my/notifications", headers={"X-Developer-User": "DEV/agent"}
            ).json()["items"]
            == []
        )
        marked = client.post(f"/api/v1/my/notifications/{notification_id}/read", headers=customer)
        assert marked.status_code == 200 and marked.json()["unread"] is False
        assert (
            client.get("/api/v1/my/notifications?unread_only=true", headers=customer).json()[
                "items"
            ]
            == []
        )


@pytest.mark.integration
def test_retry_backoff_permanent_failure_and_immutable_attempts() -> None:
    retry_event = _event(2, "NOTIFY_STATUS_CHANGED")
    sender = SequenceSender(["retry", "success"])
    worker, engine = _worker("notification-retry", sender)

    async def retry_delivery() -> None:
        try:
            assert await worker.plan_one()
            assert await worker.deliver_one()
            assert not await worker.deliver_one()
            _psql(
                f"UPDATE integration.notification_delivery SET next_attempt_at=now() "
                f"WHERE outbox_event_id='{retry_event}'"
            )
            assert await worker.deliver_one()
        finally:
            await engine.dispose()

    _run(retry_delivery())
    assert (
        _value(
            f"SELECT delivery_status||':'||attempt_count||':'||final_failure FROM "
            f"integration.notification_delivery WHERE outbox_event_id='{retry_event}'"
        )
        == "DELIVERED:2:false"
    )

    permanent_event = _event(3, "NOTIFY_STATUS_CHANGED")
    permanent, permanent_engine = _worker("notification-permanent", SequenceSender(["permanent"]))

    async def permanent_delivery() -> None:
        try:
            assert await permanent.plan_one()
            assert await permanent.deliver_one()
        finally:
            await permanent_engine.dispose()

    _run(permanent_delivery())
    assert (
        _value(
            f"SELECT delivery_status||':'||attempt_count||':'||final_failure FROM "
            f"integration.notification_delivery WHERE outbox_event_id='{permanent_event}'"
        )
        == "FAILED:1:true"
    )
    assert (
        _value(
            "SELECT count(*) FROM integration.notification_delivery_attempt AS attempt "
            "JOIN integration.notification_delivery AS delivery USING (notification_delivery_id) "
            f"WHERE delivery.outbox_event_id IN ('{retry_event}','{permanent_event}')"
        )
        == "3"
    )
    mutation = _psql(
        "UPDATE integration.notification_delivery_attempt SET error_code='changed'", check=False
    )
    assert mutation.returncode != 0
    assert "immutable" in mutation.stderr.lower()


@pytest.mark.integration
def test_assignment_recipient_comes_from_authoritative_ticket_state() -> None:
    _psql(
        f"UPDATE itsm.ticket SET assignee_user_id="
        "'22000000-0000-0000-0000-000000000004' "
        f"WHERE ticket_id='{TICKET_ID}'"
    )
    event_id = _event(4, "NOTIFY_TICKET_ASSIGNED")
    worker, engine = _worker("notification-assignment")

    async def plan() -> None:
        try:
            assert await worker.plan_one()
        finally:
            await engine.dispose()

    _run(plan())
    assert (
        _value(
            "SELECT recipient_user_id||':'||recipient_reference FROM "
            f"integration.notification_delivery WHERE outbox_event_id='{event_id}'"
        )
        == "22000000-0000-0000-0000-000000000004:agent@example.invalid"
    )
