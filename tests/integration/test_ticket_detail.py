"""PostgreSQL validation for analyst ticket-detail enrichment (Task 11.3).

Verifies SLA summaries, assignment extras, and the attachment metadata list
against seeded rows, plus the three-statement budget of the new repository
reads (detail endpoint total: ticket + comments + extras + SLA = four).
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

from apps.api.app.attachments.repository import AttachmentRepository
from apps.api.app.tickets.repository import TicketRepository

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-ticket-detail-test"
PORT = "55464"
DATABASE = "ticket_detail_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
ANALYST_ID = UUID("22000000-0000-0000-0000-000000000004")
GROUP_ID = UUID("23000000-0000-0000-0000-000000000002")
WORKFLOW_VERSION = UUID("32100000-0000-0000-0000-000000000001")
TICKET_ID = UUID("86000000-0000-0000-0000-000000000001")
NOW = datetime(2030, 6, 15, 18, 0, tzinfo=UTC)


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
def detail_database() -> Iterator[None]:
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


async def _seed(session: object) -> None:
    open_status = (
        await session.execute(  # type: ignore[attr-defined]
            text("""
                SELECT status_id FROM config.workflow_status
                WHERE workflow_version_id = :version AND NOT terminal_flag
                ORDER BY status_id LIMIT 1
            """),
            {"version": WORKFLOW_VERSION},
        )
    ).scalar_one()
    await session.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO itsm.ticket(
              ticket_id,tenant_id,project_id,request_type_id,
              request_type_version_id,work_type_id,workflow_version_id,
              status_id,summary,description,reporter_user_id,priority_code,
              impact_code,urgency_code,channel_code,created_by,updated_by,
              assignment_group_id,assignee_user_id)
            SELECT :ticket_id,:tenant_id,request_type.project_id,
              request_type.request_type_id,
              request_version.request_type_version_id,
              request_type.work_type_id,:workflow_version,
              :status_id,'Detail seed','Detail description',:analyst_id,'P2',
              'MODERATE','HIGH','PORTAL',:analyst_id,:analyst_id,:group_id,:analyst_id
            FROM config.request_type request_type
            JOIN config.request_type_version request_version
              ON request_version.request_type_id=request_type.request_type_id
             AND request_version.version_status='PUBLISHED'
            WHERE request_type.request_type_id='33000000-0000-0000-0000-000000000001'
            ON CONFLICT (ticket_id) DO NOTHING
        """),
        {
            "ticket_id": TICKET_ID,
            "tenant_id": TENANT_ID,
            "workflow_version": WORKFLOW_VERSION,
            "status_id": open_status,
            "analyst_id": ANALYST_ID,
            "group_id": GROUP_ID,
        },
    )
    sla_rows = [
        (0, "RUNNING", NOW + timedelta(hours=2), None, None, None),
        (2, "BREACHED", NOW - timedelta(hours=4), None, NOW - timedelta(hours=3), None),
    ]
    for goal_offset, state, target, completed, breached, paused in sla_rows:
        await session.execute(  # type: ignore[attr-defined]
            text("""
                INSERT INTO itsm.ticket_sla(
                  tenant_id,ticket_id,sla_definition_id,sla_goal_id,
                  sla_goal_version_id,business_calendar_version_id,state_code,
                  started_at,target_at,completed_at,breached_at,paused_at,
                  last_calculated_at,remaining_working_seconds)
                SELECT :tenant_id,:ticket_id,goal.sla_definition_id,
                  goal.sla_goal_id,goal_version.sla_goal_version_id,
                  goal_version.business_calendar_version_id,:state,
                  :started,:target,:completed,:breached,:paused,:target,5400
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
                "ticket_id": TICKET_ID,
                "state": state,
                "started": NOW - timedelta(hours=48),
                "target": target,
                "completed": completed,
                "breached": breached,
                "paused": paused,
            },
        )
    attachments = [
        ("a1", "clean.pdf", "CLEAN", "RELEASED"),
        ("a2", "pending.png", "PENDING", "QUARANTINED"),
        ("a3", "bad.txt", "INFECTED", "REJECTED"),
    ]
    for index, (suffix, filename, scan, quarantine) in enumerate(attachments, start=1):
        await session.execute(  # type: ignore[attr-defined]
            text("""
                INSERT INTO itsm.ticket_attachment(
                  attachment_id,ticket_id,uploaded_by,original_filename,
                  quarantine_object_uri,client_declared_content_type,
                  file_size_bytes,sha256_checksum,malware_scan_status,
                  quarantine_status,security_classification,visibility_code,
                  encryption_status,protected_object_uri,released_at,
                  malware_scanned_at,scanner_engine,scanner_version,rejected_at)
                VALUES (:attachment_id,:ticket_id,:user_id,:filename,
                  :object_key,'application/octet-stream',1234,repeat('a',64),
                  :scan,:quarantine,'PUBLIC','PUBLIC','PROVIDER_MANAGED',
                  CASE WHEN :released THEN CAST(:object_key AS text) END,
                  CASE WHEN :released THEN now() END,
                  CASE WHEN :scanned THEN now() END,
                  CASE WHEN :scanned THEN CAST('seed-scanner' AS text) END,
                  CASE WHEN :scanned THEN CAST('1.0' AS text) END,
                  CASE WHEN :rejected THEN now() END)
                ON CONFLICT (attachment_id) DO NOTHING
            """),
            {
                "attachment_id": UUID(f"87000000-0000-0000-0000-00000000000{index}"),
                "ticket_id": TICKET_ID,
                "user_id": ANALYST_ID,
                "filename": filename,
                "object_key": f"quarantine/{suffix}",
                "scan": scan,
                "quarantine": quarantine,
                "released": quarantine == "RELEASED",
                "scanned": scan in {"CLEAN", "INFECTED"},
                "rejected": quarantine == "REJECTED",
            },
        )
    await session.commit()  # type: ignore[attr-defined]


@pytest.mark.integration
@pytest.mark.anyio
async def test_detail_enrichment_slas_assignment_and_attachment_metadata() -> None:
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
            tickets = TicketRepository(session)
            attachments = AttachmentRepository(session)
            statements.clear()
            extras = await tickets.analyst_extras(TICKET_ID)
            slas = await tickets.ticket_slas(TICKET_ID)
            rows = await attachments.list_for_ticket(TICKET_ID)
            new_statement_count = len(statements)

        assert extras.impact_code == "MODERATE"
        assert extras.urgency_code == "HIGH"
        assert extras.assignment_group_id == GROUP_ID
        assert extras.assignment_group_name
        assert extras.assignee_user_id == ANALYST_ID
        assert extras.assignee_name

        classification_cases = [
            ("MODERATE", "HIGH"),
            (None, "HIGH"),
            ("MODERATE", None),
            (None, None),
        ]
        async with maker() as session:
            tickets = TicketRepository(session)
            for impact, urgency in classification_cases:
                await session.execute(
                    text("""
                        UPDATE itsm.ticket
                        SET impact_code=:impact, urgency_code=:urgency
                        WHERE ticket_id=:ticket_id
                    """),
                    {"impact": impact, "urgency": urgency, "ticket_id": TICKET_ID},
                )
                current = await tickets.analyst_extras(TICKET_ID)
                assert current.impact_code == impact
                assert current.urgency_code == urgency
            await session.rollback()

        assert len(slas) == 2
        states = {row.state_code for row in slas}
        assert states == {"RUNNING", "BREACHED"}
        running = next(row for row in slas if row.state_code == "RUNNING")
        assert running.remaining_working_seconds == 5400
        assert running.breached_at is None
        breached = next(row for row in slas if row.state_code == "BREACHED")
        assert breached.breached_at is not None
        assert all(row.definition_code for row in slas)

        assert [row.malware_scan_status for row in rows] and len(rows) == 3
        by_name = {row.original_filename: row.malware_scan_status for row in rows}
        assert by_name == {
            "clean.pdf": "CLEAN",
            "pending.png": "PENDING",
            "bad.txt": "INFECTED",
        }
        assert all(row.uploaded_by_name for row in rows)

        # The three enrichment reads are one statement each; the endpoint adds
        # the base ticket select and public comments for four/one totals.
        assert new_statement_count == 3
    finally:
        await engine.dispose()
