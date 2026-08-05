"""PostgreSQL validation for the analyst dashboard aggregates (Task 11.2).

Seeds tickets across explicit UTC windows against a fixed reference time and
asserts every dashboard count, distinct SLA semantics, weekly compliance, the
activity feed, and the five-statement repository budget (plus the shared
queue lookup, six statements total per request).
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

from apps.api.app.reporting.repository import DashboardRepository

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-dashboard-test"
PORT = "55463"
DATABASE = "dashboard_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
ANALYST_ID = UUID("22000000-0000-0000-0000-000000000004")
WORKFLOW_VERSION = UUID("32100000-0000-0000-0000-000000000001")
REFERENCE_NOW = datetime(2030, 6, 15, 18, 0, tzinfo=UTC)


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


def _engine() -> AsyncEngine:
    return create_async_engine(
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}",
        pool_size=2,
        max_overflow=0,
    )


@pytest.fixture(scope="module", autouse=True)
def dashboard_database() -> Iterator[None]:
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
        yield
    finally:
        _compose("down", "--volumes", "--remove-orphans", check=False)


async def _status_ids(session: object) -> tuple[UUID, UUID]:
    row = (
        await session.execute(  # type: ignore[attr-defined]
            text("""
                SELECT
                  (SELECT status_id FROM config.workflow_status
                   WHERE workflow_version_id = :version AND NOT terminal_flag
                   ORDER BY status_id LIMIT 1) AS open_status,
                  (SELECT status_id FROM config.workflow_status
                   WHERE workflow_version_id = :version AND terminal_flag
                   ORDER BY status_id LIMIT 1) AS terminal_status
            """),
            {"version": WORKFLOW_VERSION},
        )
    ).one()
    assert row.open_status is not None and row.terminal_status is not None
    return (row.open_status, row.terminal_status)


async def _seed(session: object) -> None:
    open_status, terminal_status = await _status_ids(session)
    now = REFERENCE_NOW
    fixtures = [
        # (suffix, status, created_at, resolved_at)
        ("a1", open_status, now - timedelta(hours=2), None),
        ("b2", open_status, now - timedelta(hours=26), None),
        ("c3", terminal_status, now - timedelta(hours=72), now - timedelta(hours=1)),
        ("d4", terminal_status, now - timedelta(hours=72), now - timedelta(hours=25)),
        ("e5", open_status, now - timedelta(hours=72), None),
        ("f6", open_status, now - timedelta(hours=72), None),
    ]
    for index, (suffix, status_id, created_at, resolved_at) in enumerate(fixtures, start=1):
        await session.execute(  # type: ignore[attr-defined]
            text("""
                INSERT INTO itsm.ticket(
                  ticket_id,tenant_id,project_id,request_type_id,
                  request_type_version_id,work_type_id,workflow_version_id,
                  status_id,summary,description,reporter_user_id,priority_code,
                  channel_code,created_by,updated_by,created_at,resolved_at)
                SELECT :ticket_id,:tenant_id,request_type.project_id,
                  request_type.request_type_id,
                  request_version.request_type_version_id,
                  request_type.work_type_id,:workflow_version,
                  :status_id,:summary,'Dashboard seed',:analyst_id,'P3',
                  'PORTAL',:analyst_id,:analyst_id,:created_at,:resolved_at
                FROM config.request_type request_type
                JOIN config.request_type_version request_version
                  ON request_version.request_type_id=request_type.request_type_id
                 AND request_version.version_status='PUBLISHED'
                WHERE request_type.request_type_id='33000000-0000-0000-0000-000000000001'
                ON CONFLICT (ticket_id) DO NOTHING
            """),
            {
                "ticket_id": UUID(f"85000000-0000-0000-0000-00000000000{index}"),
                "tenant_id": TENANT_ID,
                "workflow_version": WORKFLOW_VERSION,
                "status_id": status_id,
                "summary": f"Dashboard seed {suffix}",
                "analyst_id": ANALYST_ID,
                "created_at": created_at,
                "resolved_at": resolved_at,
            },
        )
    sla_rows = [
        # (ticket_index, goal_offset, state, target, completed, breached, paused)
        (5, 0, "BREACHED", now - timedelta(hours=4), None, now - timedelta(hours=3), None),
        (5, 2, "BREACHED", now - timedelta(hours=51), None, now - timedelta(hours=50), None),
        (3, 0, "COMPLETED", now - timedelta(hours=2), now - timedelta(hours=1), None, None),
        (6, 0, "RUNNING", now + timedelta(hours=2), None, None, None),
        (6, 2, "RUNNING", now + timedelta(hours=3), None, None, None),
    ]
    for ticket_index, goal_offset, state, target, completed, breached, paused in sla_rows:
        await session.execute(  # type: ignore[attr-defined]
            text("""
                INSERT INTO itsm.ticket_sla(
                  tenant_id,ticket_id,sla_definition_id,sla_goal_id,
                  sla_goal_version_id,business_calendar_version_id,state_code,
                  started_at,target_at,completed_at,breached_at,paused_at,
                  last_calculated_at)
                SELECT :tenant_id,:ticket_id,goal.sla_definition_id,
                  goal.sla_goal_id,goal_version.sla_goal_version_id,
                  goal_version.business_calendar_version_id,:state,
                  :started,:target,:completed,:breached,:paused,:target
                FROM config.sla_goal_version goal_version
                JOIN config.sla_goal goal
                  ON goal.sla_goal_id=goal_version.sla_goal_id
                ORDER BY goal_version.sla_goal_version_id
                OFFSET :goal_offset
                LIMIT 1
            """),
            {
                "goal_offset": goal_offset,
                "tenant_id": TENANT_ID,
                "ticket_id": UUID(f"85000000-0000-0000-0000-00000000000{ticket_index}"),
                "state": state,
                "started": now - timedelta(hours=72),
                "target": target,
                "completed": completed,
                "breached": breached,
                "paused": paused,
            },
        )
    await session.commit()  # type: ignore[attr-defined]


@pytest.mark.integration
@pytest.mark.anyio
async def test_dashboard_aggregates_windows_distinct_sla_and_statement_budget() -> None:
    engine = _engine()
    statements: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _count(conn: object, cursor: object, sql: str, *args: object) -> None:
        statements.append(sql)

    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as session:
            await _seed(session)
        async with maker() as session:
            repository = DashboardRepository(session)
            statements.clear()
            counts = await repository.ticket_counts(TENANT_ID, REFERENCE_NOW)
            breached_open, due_today = await repository.sla_ticket_counts(TENANT_ID, REFERENCE_NOW)
            distribution = await repository.status_distribution(TENANT_ID)
            week = await repository.sla_compliance_week(TENANT_ID, REFERENCE_NOW)
            activity = await repository.recent_activity(TENANT_ID, 10)
            repository_statements = len(statements)

        assert counts.open_now == 4
        assert counts.new_today == 1
        assert counts.new_yesterday_same_elapsed_window == 1
        assert counts.resolved_today == 1
        assert counts.resolved_yesterday_same_elapsed_window == 1
        # Ticket e5 has two breached SLA rows yet counts once; f6 has two
        # running rows targeting today yet counts once.
        assert breached_open == 1
        assert due_today == 1
        assert sum(row.count for row in distribution) == 4
        assert all(row.count > 0 for row in distribution)
        assert week.met == 1
        assert week.breached == 2
        assert 1 <= len(activity) <= 10
        event_ids = [row.event_id for row in activity]
        assert event_ids == sorted(event_ids, reverse=True)
        assert all(row.ticket_key for row in activity)
        # Five aggregate statements here; the endpoint adds one queue lookup
        # for primary_queue, keeping the request at six statements total.
        assert repository_statements == 5
    finally:
        await engine.dispose()
