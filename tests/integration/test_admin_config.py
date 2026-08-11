"""PostgreSQL validation for configuration administration (Task 11.5C).

Runs the real AdminService against a migrated database **through the runtime
login role** (``helpdesk``, member of ``helpdesk_app``) so the read surfaces
and the catalogue visibility toggle are proven against actual grants, not
superuser privileges. Verifies tenant isolation, versioned-configuration
reads, rule summarization of seeded shapes, optimistic concurrency, audit
rows, statement budgets, and that the 0022 grant is exactly column-scoped.
"""

import asyncio
import json
import os
import subprocess
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from apps.api.app.admin.schemas import AdminRequestTypeVisibilityRequest
from apps.api.app.admin.service import AdminService
from apps.api.app.core.context import RequestContext
from apps.api.app.core.exceptions import ConcurrencyError, NotFoundError
from apps.api.app.core.settings import Settings
from apps.api.app.db.unit_of_work import SqlAlchemyUnitOfWork
from apps.api.app.infrastructure.health import ApplicationResources

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "fusion-helpdesk-admin-config-test"
PORT = "55552"
DATABASE = "admin_config_model"
TENANT_ID = UUID("20000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = UUID("20000000-0000-0000-0000-000000000099")
PLATFORM_ADMIN_ID = UUID("22000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("22000000-0000-0000-0000-000000000098")
WORKFLOW_ID = UUID("32000000-0000-0000-0000-000000000001")
FIRST_RESPONSE_SLA_ID = UUID("38200000-0000-0000-0000-000000000001")
RESOLUTION_SLA_ID = UUID("38200000-0000-0000-0000-000000000002")
CALENDAR_ID = UUID("38000000-0000-0000-0000-000000000001")
REPORT_FUSION_ERROR_ID = UUID("33000000-0000-0000-0000-000000000001")
ANALYTICS_ISSUE_ID = UUID("33000000-0000-0000-0000-000000000003")
LIST_STATEMENT_CEILING = 1
DETAIL_STATEMENT_CEILING = 3
MUTATION_STATEMENT_CEILING = 8


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
def admin_config_database() -> Iterator[None]:
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


def _context(
    user_id: UUID, *, roles: tuple[str, ...] = ("PLATFORM_ADMIN",), tenant_id: UUID = TENANT_ID
) -> RequestContext:
    return RequestContext(
        tenant_id,
        user_id,
        f"subject-{user_id}",
        frozenset(roles),
        frozenset(),
        None,
        "corr-admin-config",
        "req-admin-config",
    )


async def _seed_other_tenant(session: AsyncSession) -> None:
    await session.execute(
        text("""
            INSERT INTO identity.tenant(tenant_id,tenant_code,tenant_name)
            VALUES (:tenant_id,'OTHER','Other Tenant')
            ON CONFLICT (tenant_id) DO NOTHING
        """),
        {"tenant_id": OTHER_TENANT_ID},
    )
    await session.execute(
        text("""
            INSERT INTO identity.app_user(
              user_id,tenant_id,external_subject,email_address,display_name,active_flag)
            VALUES (:user_id,:tenant_id,'other-user','other@example.invalid',
              'Other Tenant User',true)
            ON CONFLICT (user_id) DO NOTHING
        """),
        {"user_id": OTHER_USER_ID, "tenant_id": OTHER_TENANT_ID},
    )
    await session.commit()


async def _request_type_state(
    session: AsyncSession, request_type_id: UUID
) -> tuple[bool, bool, datetime]:
    row = (
        await session.execute(
            text("""
                SELECT active_flag,employee_visible_flag,updated_at
                FROM config.request_type WHERE request_type_id=:request_type_id
            """),
            {"request_type_id": request_type_id},
        )
    ).one()
    return (
        cast("bool", row.active_flag),
        cast("bool", row.employee_visible_flag),
        cast("datetime", row.updated_at),
    )


def _queries(statements: list[str]) -> list[str]:
    return [statement for statement in statements if "set_config" not in statement]


@pytest.mark.integration
@pytest.mark.anyio
async def test_config_reads_and_visibility_toggle_under_runtime_role() -> None:  # noqa: PLR0915
    superuser: AsyncEngine = create_async_engine(
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{PORT}/{DATABASE}",
        pool_size=2,
        max_overflow=0,
    )
    runtime: AsyncEngine = create_async_engine(
        f"postgresql+psycopg://helpdesk:helpdesk@127.0.0.1:{PORT}/{DATABASE}",
        pool_size=2,
        max_overflow=0,
    )
    statements: list[str] = []

    @event.listens_for(runtime.sync_engine, "before_cursor_execute")
    def _count(conn: object, cursor: object, sql: str, *args: object) -> None:
        statements.append(sql)

    superuser_maker = async_sessionmaker(superuser, expire_on_commit=False)
    runtime_maker = async_sessionmaker(runtime, expire_on_commit=False)

    def factory(context: RequestContext) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(runtime_maker, context, rls_enabled=False)

    service = AdminService(factory, Settings(), cast("ApplicationResources", object()))
    admin = _context(PLATFORM_ADMIN_ID)
    foreign_admin = _context(OTHER_USER_ID, tenant_id=OTHER_TENANT_ID)
    try:
        async with superuser_maker() as session:
            await _seed_other_tenant(session)

        # Workflow list: single statement, real counts from the fixture.
        statements.clear()
        workflows = await service.workflows(admin, search=None, active=None, limit=25, offset=0)
        assert len(_queries(statements)) <= LIST_STATEMENT_CEILING, "workflow list budget"
        fixture_workflow = next(
            item for item in workflows.items if item.workflow_code == "CATALOGUE_TEST_WORKFLOW"
        )
        assert fixture_workflow.current_version_number == 1
        assert fixture_workflow.current_version_status == "PUBLISHED"
        assert fixture_workflow.status_count == 7
        assert fixture_workflow.transition_count == 9
        assert fixture_workflow.request_type_count == 9

        # Workflow detail: statuses ordered, flags surfaced, rules summarized.
        statements.clear()
        workflow = await service.workflow_detail(admin, WORKFLOW_ID)
        assert len(_queries(statements)) <= DETAIL_STATEMENT_CEILING, "workflow detail budget"
        assert workflow.displayed_version_number == 1
        status_codes = [status.status_code for status in workflow.statuses]
        assert status_codes[0] == "NEW"
        initial = [status for status in workflow.statuses if status.initial_flag]
        assert [status.status_code for status in initial] == ["NEW"]
        terminal = {status.status_code for status in workflow.statuses if status.terminal_flag}
        assert terminal == {"CLOSED", "REJECTED"}
        transitions = {item.transition_code: item for item in workflow.transitions}
        resolve = transitions["RESOLVE"]
        assert resolve.required_fields == ["resolution_code"]
        assert "SET_TIMESTAMP" in resolve.action_types
        assert resolve.from_status_code == "IN_PROGRESS"
        assert resolve.to_status_code == "RESOLVED"
        wait = transitions["WAIT_FOR_CUSTOMER"]
        assert wait.guarded is True
        assert wait.guard_summary == ["summary is set"]
        approval = transitions["APPROVE_ACCESS"]
        assert approval.action_types == ["APPROVAL_CONTINUATION"]
        assert len(workflow.request_types) == 9

        # SLA list and detail: goal values come from published goal versions.
        statements.clear()
        policies = await service.sla_policies(
            admin, search=None, active=None, project_id=None, limit=25, offset=0
        )
        assert len(_queries(statements)) <= LIST_STATEMENT_CEILING, "SLA list budget"
        codes = {item.sla_code for item in policies.items}
        assert {"FIRST_RESPONSE", "RESOLUTION"} <= codes
        first_response = next(item for item in policies.items if item.sla_code == "FIRST_RESPONSE")
        assert first_response.goal_count == 2
        assert first_response.project_key == "ERP"

        statements.clear()
        resolution = await service.sla_policy_detail(admin, RESOLUTION_SLA_ID)
        assert len(_queries(statements)) <= DETAIL_STATEMENT_CEILING, "SLA detail budget"
        assert resolution.pause_condition_summary == ["Ticket status is WAITING_FOR_CUSTOMER"]
        goals = {goal.goal_name: goal for goal in resolution.goals}
        p1_goal = goals["P1 resolution"]
        assert p1_goal.target_minutes == 240
        assert p1_goal.warning_minutes == 60
        assert p1_goal.calendar_code == "UK_BUSINESS_HOURS"
        assert p1_goal.version_status == "PUBLISHED"
        assert p1_goal.match_summary == ["priority_code is P1"]
        assert goals["Default resolution"].match_summary == []
        assert [version.version_number for version in resolution.versions] == [1]
        assert resolution.cycle_counts.running == 0

        # Calendar list and detail: working windows and holidays from the
        # displayed published version.
        statements.clear()
        calendars = await service.calendars(admin, search=None, active=None, limit=25, offset=0)
        assert len(_queries(statements)) <= LIST_STATEMENT_CEILING, "calendar list budget"
        uk_calendar = next(
            item for item in calendars.items if item.calendar_code == "UK_BUSINESS_HOURS"
        )
        assert uk_calendar.linked_goal_count == 4
        assert uk_calendar.timezone_name == "Europe/London"

        statements.clear()
        calendar = await service.calendar_detail(admin, CALENDAR_ID)
        assert len(_queries(statements)) <= DETAIL_STATEMENT_CEILING, "calendar detail budget"
        assert len(calendar.working_periods) == 5
        assert {period.iso_day_of_week for period in calendar.working_periods} == {1, 2, 3, 4, 5}
        assert calendar.working_periods[0].start_local_time == "09:00"
        assert calendar.working_periods[0].end_local_time == "17:00"
        assert [item.exception_date for item in calendar.exceptions] == ["2026-12-25"]
        assert calendar.exceptions[0].exception_type == "CLOSED"
        assert calendar.exceptions[0].start_local_time is None
        assert len(calendar.linked_goals) == 4

        # Catalogue list and detail: form fields, options, conditional rules.
        statements.clear()
        catalogue = await service.request_types(
            admin, search=None, active=None, project_id=None, limit=25, offset=0
        )
        assert len(_queries(statements)) <= LIST_STATEMENT_CEILING, "catalogue list budget"
        assert len(catalogue.items) == 9
        report_error = next(
            item for item in catalogue.items if item.request_type_code == "REPORT_FUSION_ERROR"
        )
        assert report_error.workflow_code == "CATALOGUE_TEST_WORKFLOW"
        assert report_error.current_version_status == "PUBLISHED"

        statements.clear()
        detail = await service.request_type_detail(admin, REPORT_FUSION_ERROR_ID)
        assert len(_queries(statements)) <= DETAIL_STATEMENT_CEILING, "catalogue detail budget"
        assert [field.field_code for field in detail.form_fields] == [
            "summary",
            "description",
            "environment",
        ]
        environment_field = detail.form_fields[2]
        assert environment_field.data_type == "SINGLE_SELECT"
        assert environment_field.condition_summary == ["summary is not empty"]
        option_labels = [option.option_label for option in environment_field.options]
        assert option_labels == ["Production", "Test", "Retired environment"]
        assert environment_field.options[2].active_flag is False
        assert [version.version_number for version in detail.versions] == [1]

        # Cross-tenant isolation: foreign identifiers do not disclose existence
        # and foreign tenants see empty lists.
        foreign_lists = await service.workflows(
            foreign_admin, search=None, active=None, limit=25, offset=0
        )
        assert foreign_lists.items == []
        for call in (
            service.workflow_detail(foreign_admin, WORKFLOW_ID),
            service.sla_policy_detail(foreign_admin, FIRST_RESPONSE_SLA_ID),
            service.calendar_detail(foreign_admin, CALENDAR_ID),
            service.request_type_detail(foreign_admin, REPORT_FUSION_ERROR_ID),
        ):
            with pytest.raises(NotFoundError):
                await call
        with pytest.raises(NotFoundError):
            await service.set_request_type_visibility(
                foreign_admin,
                REPORT_FUSION_ERROR_ID,
                AdminRequestTypeVisibilityRequest(
                    active=False,
                    employee_visible=False,
                    expected_updated_at=datetime.fromisoformat("2030-01-01T00:00:00+00:00"),
                ),
            )

        # Visibility toggle under the runtime role: disable, idempotent
        # repeat, stale-token conflict with rollback, re-enable, audit trail.
        async with superuser_maker() as session:
            active, visible, token = await _request_type_state(session, ANALYTICS_ISSUE_ID)
        assert active is True and visible is True
        statements.clear()
        disabled = await service.set_request_type_visibility(
            admin,
            ANALYTICS_ISSUE_ID,
            AdminRequestTypeVisibilityRequest(
                active=False, employee_visible=False, expected_updated_at=token
            ),
        )
        assert len(_queries(statements)) <= MUTATION_STATEMENT_CEILING, "toggle budget"
        assert disabled.changed is True
        assert disabled.active_flag is False and disabled.employee_visible_flag is False
        repeat = await service.set_request_type_visibility(
            admin,
            ANALYTICS_ISSUE_ID,
            AdminRequestTypeVisibilityRequest(
                active=False, employee_visible=False, expected_updated_at=token
            ),
        )
        assert repeat.changed is False
        with pytest.raises(ConcurrencyError):
            await service.set_request_type_visibility(
                admin,
                ANALYTICS_ISSUE_ID,
                AdminRequestTypeVisibilityRequest(
                    active=True, employee_visible=True, expected_updated_at=token
                ),
            )
        async with superuser_maker() as session:
            active, visible, _ = await _request_type_state(session, ANALYTICS_ISSUE_ID)
        assert active is False and visible is False, "conflict must not write"
        restored = await service.set_request_type_visibility(
            admin,
            ANALYTICS_ISSUE_ID,
            AdminRequestTypeVisibilityRequest(
                active=True,
                employee_visible=True,
                expected_updated_at=disabled.updated_at,
            ),
        )
        assert restored.changed is True and restored.active_flag is True
        with pytest.raises(NotFoundError):
            await service.set_request_type_visibility(
                admin,
                uuid4(),
                AdminRequestTypeVisibilityRequest(
                    active=False,
                    employee_visible=False,
                    expected_updated_at=restored.updated_at,
                ),
            )

        async with superuser_maker() as session:
            rows = (
                await session.execute(
                    text("""
                        SELECT resource_id,change_summary_json::text AS summary
                        FROM audit.audit_event
                        WHERE tenant_id=:tenant_id
                          AND action_code='ADMIN_REQUEST_TYPE_VISIBILITY_CHANGED'
                        ORDER BY audit_event_id
                    """),
                    {"tenant_id": TENANT_ID},
                )
            ).all()
        assert len(rows) == 2, "one audit row per applied change, none for no-ops"
        assert all(row.resource_id == str(ANALYTICS_ISSUE_ID) for row in rows)
        first_summary = json.loads(rows[0].summary)
        second_summary = json.loads(rows[1].summary)
        assert first_summary["active_flag"] == {"from": True, "to": False}
        assert first_summary["employee_visible_flag"] == {"from": True, "to": False}
        assert second_summary["active_flag"] == {"from": False, "to": True}
        for row in rows:
            lowered = row.summary.lower()
            for fragment in ("password", "token", "secret", "issuer", "subject"):
                assert fragment not in lowered

        # The 0022 grant is exactly column-scoped: the runtime role can flip
        # the two visibility flags but cannot touch other columns or delete.
        async with runtime_maker() as session:
            with pytest.raises(ProgrammingError, match="permission denied"):
                await session.execute(
                    text("""
                        UPDATE config.request_type SET request_type_name='hacked'
                        WHERE request_type_id=:request_type_id
                    """),
                    {"request_type_id": ANALYTICS_ISSUE_ID},
                )
        async with runtime_maker() as session:
            with pytest.raises(ProgrammingError, match="permission denied"):
                await session.execute(
                    text("""
                        DELETE FROM config.request_type
                        WHERE request_type_id=:request_type_id
                    """),
                    {"request_type_id": ANALYTICS_ISSUE_ID},
                )
        async with runtime_maker() as session:
            with pytest.raises(ProgrammingError, match="permission denied"):
                await session.execute(text("UPDATE config.workflow SET workflow_name='hacked'"))
    finally:
        await runtime.dispose()
        await superuser.dispose()
