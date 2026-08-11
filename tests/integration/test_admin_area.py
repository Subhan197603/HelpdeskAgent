"""PostgreSQL validation for the administration shell reads (Task 11.5A).

Seeds audit and security events across two tenants, then verifies tenant
isolation, filtering, ordering, and the one-statement budgets of the
overview and audit reads.
"""

import asyncio
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from apps.api.app.admin.repository import AdminRepository

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-admin-test"
PORT = "55553"
DATABASE = "admin_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("20000000-0000-0000-0000-000000000099")
USER_ID = UUID("22000000-0000-0000-0000-000000000001")
BASE_TIME = datetime(2030, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def anyio_backend() -> tuple[str, dict[str, object]]:
    return "asyncio", {"loop_factory": asyncio.SelectorEventLoop}


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
def admin_database() -> Iterator[None]:
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
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


async def _seed(session: object) -> None:
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name)
            VALUES (:tenant_id,'OTHER','Other Tenant')
            ON CONFLICT (tenant_id) DO NOTHING
        """),
        {"tenant_id": OTHER_TENANT_ID},
    )
    audit_rows = [
        (TENANT_ID, "TICKET_TRANSITIONED", "TICKET", "ERP-1", "SUCCESS", 0),
        (TENANT_ID, "ATTACHMENT_FINALIZED", "ATTACHMENT", "a-1", "SUCCESS", 1),
        (TENANT_ID, "TICKET_ROUTED", "TICKET", "ERP-2", "DENIED", 2),
        (OTHER_TENANT_ID, "TICKET_TRANSITIONED", "TICKET", "X-1", "SUCCESS", 0),
    ]
    for tenant_id, action, resource_type, resource_id, outcome, hour_offset in audit_rows:
        await session.execute(  # type: ignore[attr-defined]
            text("""
                INSERT INTO audit.audit_event(
                  tenant_id,actor_id,actor_type,action_code,resource_type,
                  resource_id,change_summary_json,outcome_code,occurred_at)
                VALUES (:tenant_id,:actor,'USER',:action,:resource_type,
                  :resource_id,'{"field":"status"}',:outcome,:occurred_at)
            """),
            {
                "tenant_id": tenant_id,
                "actor": str(USER_ID),
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                "occurred_at": BASE_TIME + timedelta(hours=hour_offset),
            },
        )
    security_rows = [
        (TENANT_ID, "AUTHORIZATION_DENIED", "DENIED", 0),
        (TENANT_ID, "PRIVILEGED_ENDPOINT_ACCESSED", "ALLOWED", 1),
        (OTHER_TENANT_ID, "AUTHORIZATION_DENIED", "DENIED", 0),
    ]
    for tenant_id, event_type, decision, hour_offset in security_rows:
        await session.execute(  # type: ignore[attr-defined]
            text("""
                INSERT INTO audit.security_event(
                  tenant_id,user_id,event_type,resource_type,resource_id,
                  decision_code,event_data_json,occurred_at)
                VALUES (:tenant_id,:user_id,:event_type,'permission',
                  'TICKET_ANALYST_READ',:decision,'{"detail":"seed"}',:occurred_at)
            """),
            {
                "tenant_id": tenant_id,
                "user_id": USER_ID,
                "event_type": event_type,
                "decision": decision,
                "occurred_at": BASE_TIME + timedelta(hours=hour_offset),
            },
        )
    await session.commit()  # type: ignore[attr-defined]


@pytest.mark.integration
@pytest.mark.anyio
async def test_admin_reads_are_tenant_scoped_filtered_and_budgeted() -> None:
    engine: AsyncEngine = create_async_engine(
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}",
        pool_size=2,
        max_overflow=0,
    )
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn: object, cursor: object, sql: str, *args: object) -> None:
        statements.append(sql)

    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await _seed(session)
        async with maker() as session:
            repository = AdminRepository(session)

            statements.clear()
            counts = await repository.overview(TENANT_ID)
            assert len(statements) == 1, "overview budget is one statement"
            assert counts.active_users == 9
            assert counts.support_groups == 2
            assert counts.open_tickets == 0
            assert counts.published_knowledge_documents == 0

            statements.clear()
            events = await repository.audit_events(
                TENANT_ID,
                resource_type=None,
                action_code=None,
                outcome_code=None,
                occurred_from=None,
                occurred_to=None,
                limit=50,
                offset=0,
            )
            assert len(statements) == 1, "audit list budget is one statement"
            assert [row.action_code for row in events] == [
                "TICKET_ROUTED",
                "ATTACHMENT_FINALIZED",
                "TICKET_TRANSITIONED",
            ]
            assert all(row.change_summary == {"field": "status"} for row in events)

            denied = await repository.audit_events(
                TENANT_ID,
                resource_type=None,
                action_code=None,
                outcome_code="DENIED",
                occurred_from=None,
                occurred_to=None,
                limit=50,
                offset=0,
            )
            assert [row.action_code for row in denied] == ["TICKET_ROUTED"]

            paged = await repository.audit_events(
                TENANT_ID,
                resource_type=None,
                action_code=None,
                outcome_code=None,
                occurred_from=None,
                occurred_to=None,
                limit=2,
                offset=1,
            )
            assert [row.action_code for row in paged] == [
                "ATTACHMENT_FINALIZED",
                "TICKET_TRANSITIONED",
            ]

            other = await repository.audit_events(
                OTHER_TENANT_ID,
                resource_type=None,
                action_code=None,
                outcome_code=None,
                occurred_from=None,
                occurred_to=None,
                limit=50,
                offset=0,
            )
            assert [row.resource_id for row in other] == ["X-1"]

            statements.clear()
            security = await repository.security_events(
                TENANT_ID,
                event_type=None,
                decision_code=None,
                occurred_from=None,
                occurred_to=None,
                limit=50,
                offset=0,
            )
            assert len(statements) == 1, "security list budget is one statement"
            assert [row.event_type for row in security] == [
                "PRIVILEGED_ENDPOINT_ACCESSED",
                "AUTHORIZATION_DENIED",
            ]
            assert all(row.details == {"detail": "seed"} for row in security)

            allowed = await repository.security_events(
                TENANT_ID,
                event_type=None,
                decision_code="ALLOWED",
                occurred_from=None,
                occurred_to=None,
                limit=50,
                offset=0,
            )
            assert [row.event_type for row in allowed] == ["PRIVILEGED_ENDPOINT_ACCESSED"]
    finally:
        await engine.dispose()
