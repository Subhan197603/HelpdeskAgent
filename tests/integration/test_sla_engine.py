"""PostgreSQL integration coverage for the SLA worker and runtime state."""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.worker.worker.settings import WorkerSettings
from apps.worker.worker.sla_worker import SlaWorker

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-sla-test"
PORT = "55450"
DATABASE = "sla_engine"
TENANT_ID = "20000000-0000-0000-0000-000000000001"
TICKET_ID = "39000000-0000-0000-0000-000000000001"


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


def _psql(sql: str, *, user: str = "postgres") -> str:
    return _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        user,
        "-d",
        DATABASE,
        "-Atqc",
        sql,
    ).stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def sla_database() -> Iterator[None]:
    _compose("up", "-d", "--wait", "postgres")
    try:
        _compose("exec", "-T", "postgres", "createdb", "-U", "postgres", DATABASE)
        for file in ("/baseline/install_all.sql", "/runtime-config/configure_local_runtime.sql"):
            args = ["exec", "-T", "postgres", "psql", "-X", "-v", "ON_ERROR_STOP=1"]
            if "runtime" in file:
                args += ["-v", "app_password=helpdesk"]
            _compose(*args, "-U", "postgres", "-d", DATABASE, "-f", file)
        migration_env = os.environ.copy()
        migration_env["MIGRATION_DATABASE_URL"] = (
            f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}"
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
        for file in (
            "/development/identity_personas.sql",
            "/development/catalogue.sql",
            "/baseline/09_optional_rls.sql",
        ):
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
          reporter_user_id,priority_code,channel_code,created_at,created_by,
          updated_at,updated_by
        ) SELECT
          '{TICKET_ID}','{TENANT_ID}','30000000-0000-0000-0000-000000000002',
          '33000000-0000-0000-0000-000000000001',
          '33100000-0000-0000-0000-000000000001',work_type.work_type_id,
          '32100000-0000-0000-0000-000000000001',
          '32200000-0000-0000-0000-000000000001','SLA integration ticket',
          'Deterministic PostgreSQL SLA lifecycle test.',
          '22000000-0000-0000-0000-000000000005','P1','PORTAL',
          '2026-01-05T09:00:00Z','22000000-0000-0000-0000-000000000005',
          '2026-01-05T09:00:00Z','22000000-0000-0000-0000-000000000005'
        FROM config.work_type AS work_type
        WHERE work_type.work_type_code='INCIDENT' AND work_type.tenant_id IS NULL;
        """
    )


def _event(event_id: int, event_type: str, occurred_at: str, payload: str = "{}") -> None:
    _psql(
        f"""
        INSERT INTO integration.outbox_event(
          outbox_event_id,tenant_id,aggregate_type,aggregate_id,event_type,
          payload_json,created_at,available_at,deduplication_key
        ) VALUES (
          '39100000-0000-0000-0000-{event_id:012d}','{TENANT_ID}','TICKET','{TICKET_ID}',
          '{event_type}','{payload}'::jsonb,'{occurred_at}',clock_timestamp(),
          'sla-integration-{event_id}'
        );
        """
    )


def _worker() -> tuple[SlaWorker, AsyncEngine]:
    settings = WorkerSettings.model_validate(
        {
            "app_env": "integration",
            "worker_database_url": (
                f"postgresql+psycopg://helpdesk_worker_login:helpdesk@127.0.0.1:{PORT}/{DATABASE}"
            ),
            "worker_id": "sla-integration-worker",
            "worker_batch_size": 20,
        }
    )
    engine = create_async_engine(settings.worker_database_url.get_secret_value())
    return SlaWorker(async_sessionmaker(engine, expire_on_commit=False), settings), engine


async def _process_events(count: int) -> SlaWorker:
    worker, engine = _worker()
    try:
        for _ in range(count):
            assert await worker.process_one()
        assert not await worker.process_one()
        return worker
    finally:
        await engine.dispose()


async def _process_due(at: datetime) -> int:
    worker, engine = _worker()
    try:
        return await worker.process_due(at)
    finally:
        await engine.dispose()


async def _process_concurrently() -> tuple[bool, bool]:
    first_worker, first_engine = _worker()
    second_worker, second_engine = _worker()
    try:
        first, second = await asyncio.gather(
            first_worker.process_one(), second_worker.process_one()
        )
        return first, second
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


def _run_events(count: int) -> SlaWorker:
    return asyncio.run(_process_events(count), loop_factory=asyncio.SelectorEventLoop)


def _run_due(at: datetime) -> int:
    return asyncio.run(_process_due(at), loop_factory=asyncio.SelectorEventLoop)


@pytest.mark.integration
def test_worker_lifecycle_is_idempotent_and_tenant_scoped() -> None:
    _event(1, "START_SLA", "2026-01-05T09:00:00Z")
    worker = _run_events(1)
    _psql(
        "UPDATE integration.outbox_event SET status_code='PENDING',processed_at=NULL "
        "WHERE outbox_event_id='39100000-0000-0000-0000-000000000001'"
    )
    duplicate_worker = _run_events(1)

    assert worker.metrics.instances_started == 2
    assert duplicate_worker.metrics.instances_started == 0
    assert _psql(f"SELECT count(*) FROM itsm.ticket_sla WHERE ticket_id='{TICKET_ID}'") == "2"
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_sla "
            "WHERE sla_goal_version_id IN ("
            "'38500000-0000-0000-0000-000000000001',"
            "'38500000-0000-0000-0000-000000000003') "
            "AND business_calendar_version_id="
            "'38100000-0000-0000-0000-000000000001'"
        )
        == "2"
    )
    assert (
        _psql("SELECT has_table_privilege('helpdesk_worker','itsm.ticket_sla_event','INSERT')")
        == "f"
    )
    sla_id = _psql(
        f"SELECT ticket_sla_id FROM itsm.ticket_sla WHERE ticket_id='{TICKET_ID}' LIMIT 1"
    )
    cross_tenant_event = _compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "helpdesk_worker_login",
        "-d",
        DATABASE,
        "-c",
        "BEGIN; SET LOCAL app.tenant_id='20000000-0000-0000-0000-000000000099'; "
        f"SELECT itsm.record_sla_event('{sla_id}','STARTED',now(),'cross-tenant','{{}}');",
        check=False,
    )
    assert cross_tenant_event.returncode != 0
    assert "tenant context" in cross_tenant_event.stderr
    assert _run_due(datetime(2026, 1, 5, 9, 10, tzinfo=UTC)) == 1
    assert (
        _psql(
            "BEGIN; SET LOCAL app.tenant_id='20000000-0000-0000-0000-000000000099'; "
            f"SELECT count(*) FROM itsm.ticket_sla WHERE ticket_id='{TICKET_ID}'; COMMIT;",
            user="helpdesk_worker_login",
        )
        == "0"
    )

    _psql(
        f"UPDATE itsm.ticket SET status_id='32200000-0000-0000-0000-000000000003' "
        f"WHERE ticket_id='{TICKET_ID}'"
    )
    _event(
        3,
        "TICKET_WORKFLOW_TRANSITIONED",
        "2026-01-05T10:00:00Z",
        '{"from_status":"IN_PROGRESS","to_status":"WAITING_FOR_CUSTOMER"}',
    )
    _run_events(1)
    assert (
        _psql(
            "SELECT state_code || ':' || remaining_working_seconds FROM itsm.ticket_sla "
            f"WHERE ticket_id='{TICKET_ID}' AND sla_definition_id="
            "'38200000-0000-0000-0000-000000000002'"
        )
        == "PAUSED:10800"
    )

    _psql(
        f"UPDATE itsm.ticket SET status_id='32200000-0000-0000-0000-000000000002' "
        f"WHERE ticket_id='{TICKET_ID}'"
    )
    _event(
        4,
        "TICKET_WORKFLOW_TRANSITIONED",
        "2026-01-06T10:00:00Z",
        '{"from_status":"WAITING_FOR_CUSTOMER","to_status":"IN_PROGRESS"}',
    )
    _event(5, "AGENT_PUBLIC_RESPONSE_ADDED", "2026-01-06T10:30:00Z")
    _run_events(2)
    assert _psql(f"SELECT first_response_at FROM itsm.ticket WHERE ticket_id='{TICKET_ID}'") == (
        "2026-01-06 10:30:00+00"
    )
    assert (
        _psql(
            "SELECT count(*) FROM itsm.ticket_sla_event AS event "
            "JOIN itsm.ticket_sla AS runtime USING(ticket_sla_id) "
            f"WHERE runtime.ticket_id='{TICKET_ID}' AND event.event_type='STOPPED'"
        )
        == "1"
    )
    _event(6, "CUSTOMER_COMMENT_ADDED", "2026-01-06T10:35:00Z")
    concurrent_results = asyncio.run(
        _process_concurrently(), loop_factory=asyncio.SelectorEventLoop
    )
    assert sorted(concurrent_results) == [False, True]
    assert (
        _psql(
            "SELECT status_code FROM integration.outbox_event WHERE outbox_event_id="
            "'39100000-0000-0000-0000-000000000006'"
        )
        == "PROCESSED"
    )


@pytest.mark.integration
def test_due_warning_breach_and_immutable_records() -> None:
    assert _run_due(datetime(2026, 1, 6, 12, 0, tzinfo=UTC)) >= 1
    assert _run_due(datetime(2026, 1, 6, 14, 0, tzinfo=UTC)) >= 1
    _run_due(datetime(2026, 1, 6, 14, 0, tzinfo=UTC))
    assert _psql(
        "SELECT event_type || ':' || count(*) FROM itsm.ticket_sla_event AS event "
        "JOIN itsm.ticket_sla AS runtime USING(ticket_sla_id) "
        f"WHERE runtime.ticket_id='{TICKET_ID}' "
        "AND event.event_type IN ('WARNING','BREACHED') "
        "GROUP BY event_type ORDER BY event_type"
    ).splitlines() == ["BREACHED:2", "WARNING:2"]
    assert _psql(
        "SELECT event_type || ':' || count(*) FROM integration.outbox_event "
        f"WHERE aggregate_id IN (SELECT ticket_sla_id::text FROM itsm.ticket_sla "
        f"WHERE ticket_id='{TICKET_ID}') AND event_type IN ('SLA_WARNING','SLA_BREACHED') "
        "GROUP BY event_type ORDER BY event_type"
    ).splitlines() == ["SLA_BREACHED:2", "SLA_WARNING:2"]

    immutable = _compose(
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
        "-c",
        "UPDATE config.calendar_working_period SET start_local_time='08:00' "
        "WHERE business_calendar_version_id="
        "'38100000-0000-0000-0000-000000000001'",
        check=False,
    )
    assert immutable.returncode != 0
    assert "immutable" in immutable.stderr

    append_only = _compose(
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
        "-c",
        "UPDATE itsm.ticket_sla_event SET event_data_json='{}'",
        check=False,
    )
    assert append_only.returncode != 0
    assert "append-only" in append_only.stderr
